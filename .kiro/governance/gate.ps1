#!/usr/bin/env pwsh
<#
.SYNOPSIS
    The Gate — the single, unscopeable verification command for EHD-ResearchTests. Runs every
    check, asserts that each one actually examined something, and refuses to report a pass it
    did not earn.

.DESCRIPTION
    WHY THIS EXISTS
    ---------------
    Decision record: artifacts/00_Governance/2026-09-15_DECISION_the_gate.md

    For four consecutive tasks this project's verification report carried the shape

        mypy --python-version 3.12 src tests     # 15 files, clean

    with a prose caveat that plain `mypy src` checks ZERO files, because pyproject.toml pins
    python_version = "3.11" against numpy 2.5.3's stubs and collection aborts. A scoped
    invocation plus a footnote, four times, accurately reported and never fixed.

    A caveat repeated four times is a defect that has learned to live with us. Nothing enforced
    the full gate, so nothing objected.

    THE DESIGN PRINCIPLE
    --------------------
    Every class of error occurs exactly once in this project's lifetime: the instance that
    discovered it. Reasoning finds an error (model-priced, unavoidable); the catch is converted
    into a deterministic check; the check runs free forever; the class cannot recur.

    So this script is not a fixed configuration. It is a LEDGER of everything this project has
    ever got wrong, and it is expected to grow every time something is caught.

    WHAT IT DELIBERATELY DOES NOT DO
    --------------------------------
    It cannot catch the first instance of anything, it has no opinion on whether the physics is
    right, and it does not visit seams that no test visits. *Principle 6, a green test suite is
    not evidence of a working system.* A green Gate means no KNOWN class of error is present.

    RELATION TO MACCRE's OMNI
    -------------------------
    Omni (C:\OmniBuilder\, for B:\EXO_GANS) is the direct ancestor of this script and this
    project claims no originality for the idea. Two deliberate differences:

    * Omni is system-pathed OUTSIDE its repository, so governance tooling never depends on the
      environment it governs. The Gate is INSIDE the repository, because its checks are
      project-specific and must travel with the code — a check absent from a clone cannot
      protect a cloner, and this repository is intended to become public. The dependency on its
      own environment is the accepted price.
    * Omni runs language tools. The Gate also runs the governance verifiers, because here
      steering, skills, agent seats and model pins drift exactly as readily as code.

    We read omni to understand it. We do not use it here and we do not modify it. The Iron Rule
    holds.

    NO SCOPED VARIANT
    -----------------
    This script takes no path argument and no stage selector, on purpose. `omni qa some_file.py`
    was the failure mode that produced omni's own mandate against scoping; the cheapest way to
    prevent it is to make it inexpressible.

.PARAMETER SkipSlow
    Skip only the slowest stage (pytest's matplotlib-heavy tests are not separable, so this
    skips nothing today and exists to be refused). Reserved; currently ignored with a warning.

.PARAMETER Json
    Emit a machine-readable result object instead of the human report.

.OUTPUTS
    Exit codes, all distinct, so "which gate failed" needs no log reading:
        0  OK                every stage ran and passed
        2  RUFF-FAILED       lint findings
        3  BLACK-FAILED      formatting drift
        4  MYPY-FAILED       type errors
        5  MYPY-CHECKED-NOTHING   mypy ran but examined zero files -- NOT a pass
        6  PYTEST-FAILED     one or more tests failed
        7  PYTEST-UNDER-FLOOR     collected count below the floor; a collection error is hiding
        8  GOVERNANCE-FAILED a governance verifier reported non-zero
        9  TOOLING-ABSENT    the venv interpreter or a required tool is missing; nothing ran
       10  SWEEP-TOO-NARROW  a sweep examined fewer files than expected; breadth was lost
       11  PYRIGHT-FAILED    pyright type errors
       12  CHECKER-DIVERGED  mypy and pyright examined different file sets; a blind spot exists
       13  UNDECLARED-EXCLUSION   a tool config excludes something not declared in ehd-dev-rules.md
  14  PYTEST-COVERAGE-REDUCED  tests skipped, xfailed or deselected; INCOMPLETE, not clean
  15  PYRIGHT-UNPINNED  the node pyright that would actually run is not pinned to the lock

.EXAMPLE
    pwsh -File .kiro/governance/gate.ps1
#>

[CmdletBinding()]
param(
    [switch] $SkipSlow,
    [switch] $Json
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$EXIT_OK                = 0
$EXIT_RUFF              = 2
$EXIT_BLACK             = 3
$EXIT_MYPY              = 4
$EXIT_MYPY_NOTHING      = 5
$EXIT_PYTEST            = 6
$EXIT_PYTEST_FLOOR      = 7
$EXIT_GOVERNANCE        = 8
$EXIT_TOOLING_ABSENT    = 9
$EXIT_SWEEP_NARROW      = 10
$EXIT_PYRIGHT           = 11
$EXIT_CHECKER_DIVERGED  = 12
$EXIT_UNDECLARED_EXCLUSION = 13
$EXIT_PYTEST_COVERAGE   = 14
$EXIT_PYRIGHT_UNPINNED  = 15

$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'

# ---------------------------------------------------------------------------
# The collected-count floor.
#
# RAISE THIS when checks are added. A floor that never moves stops catching collection errors
# as the suite grows: one ImportError in one orphaned module can reduce a suite to zero while
# the report looks entirely normal, and a stale floor of 12 would happily accept that.
#
# History, so the growth is visible and the floor's staleness is self-evident:
#   Task 0 (inherited)  55
#   Task 1              79
#   Task 2              89
#   Task 3             114
#   Task 4             137
#   The Gate           143   <- checks on the Gate itself
#   Breadth hardening  147   <- checks on the sweeps proving their own breadth
#   Task 5             237   <- basis ladder + BreadCrumb PROV corpus
#   Threshold seam     238   <- the Gate's reported thresholds must equal the enforced ones
#   Task 6             289   <- lock/bootstrap checks, MK0 end-to-end chain, stageable-file scan
#   Task 7 (part)      360   <- profile schema, validation-by-rejection, migration, diff, parity
#   Task 7 (rest)      387   <- consumer migration, the drift test, solver-input regeneration diff
#   Profile/fixture    389   <- profiles/ clones empty; the MK0 pin is a tracked test fixture
#   Coverage status    396   <- no-xfail policy, reduced coverage as its own status, and a
#                              PowerShell parse check over all five governance scripts
#   Task 8 (quantity)  448   <- Quantity: dimensions, bands, basis propagation, bound labelling
#   Task 8 (op point)  498   <- OperatingPoint as Quantities; k_geo band propagation demo
#   Task 8 (labelling) 508   <- upper-bound labels structural in CSV headers, axes and captions
#   FR-005 CLI         537   <- ehdsuite schema/list/validate/diff/new/report
#   Task 9             571   <- cross-validation: route agreement + claim adjudication
#   Exemption ledger   589   <- every DESIGN_VALUE_EXEMPTIONS key must be named in the ledger
#   Adapter detection  600   <- detection layer (see the correction below)
#   Path existence     601   <- every project path named in docs or printed output must exist
#   Adapter detection  635   <- src/ehdpsu/detect.py, tests/test_detect.py (45 tests)
#   Detection data     656   <- 21 invariants over the spec table itself: executable-name
#                              provenance, declared default-path and version-probe gaps, the
#                              published signature, version-probe isolation, GUI-launch hazard,
#                              and no dead helpers
#   Task 12            804   <- the adapter layer: five obligations as an ABC, the run-record
#                              gate, `ehdsuite doctor`, and mechanical attribution. Most of the
#                              148 are parameterised over the registry, so a fourth adapter
#                              raises this count without a new test being written
#   Task 13.0          842   <- installing the solvers exposed that detection route 1
#                              (`configured-path`) could never be populated: two working installs
#                              reported tool-absent. tools.local.json, plus the invariant that a
#                              stale configured path is never silent
#   FEMM first run     844   <- running the Lua script for the first time found it could not
#                              solve at all: one block label for three enclosed regions, and a
#                              read-back naming a FEMM function that does not exist. Checks on
#                              the label count, the Lua 4 dialect, and computed-not-described
#                              read-back
#   FEMM first solve   845   <- the script's own Peek cross-check was a category error: it
#                              compared an applied-voltage surface field against an onset field,
#                              a factor of ~7.4 apart. One check that the invalid comparison
#                              cannot return
#   Register floors    854   <- declared registers may not shrink silently. A delegated seat
#                              emptied all seven default_paths tuples and every test passed:
#                              reference data is checked for VALIDITY and never for PRESENCE, so
#                              deletion satisfies every schema check ever written
#   Batch 1 adapters   998   <- Gmsh, Elmer and ParaView adapters registered
#                              (src/ehdpsu/adapters/solvers.py). Most of the contract tests are
#                              parameterised over adapters.ADAPTERS, so three new adapters
#                              multiply them without a new test being written; measured with
#                              `pytest --collect-only -q`, not guessed
#
# Correction, 2026-09-16. The line now reading 600 previously read
# "Task (this packet) 600   <- adapter detection: 21 new tests". Both halves were wrong, and both
# were copied from the executor seat's own completion report rather than counted:
#   - tests/test_detect.py collects 11 tests, not 21.
#   - the 29 tests between 571 and 600 were 18 exemption-ledger tests plus those 11; attributing
#     all 29 to the detection layer is a causal claim nobody measured.
# Corrected beside rather than silently overwritten, because the wrong attribution is itself the
# evidence behind the seat error-rate estimate in
# .kiro/skills/suite-core-oracle/task_ledger.md. Deleting it would delete the finding.
#
# `test_gate_floor_matches_the_current_suite_size` asserts this equals the real collected count,
# as an EQUALITY rather than a lower bound: a floor below the real count is slack that accumulates
# silently, while a floor above it fails immediately and obviously.
# ---------------------------------------------------------------------------
$COLLECTED_FLOOR = 1141

$result = [ordered]@{
    status          = $null
    exitCode        = $null
    reason          = $null
    stagesRun       = @()
    stagesSkipped   = @()
    mypyFileCount   = $null
    pyrightFileCount = $null
    # The node pyright version the run was FORCED to, read from requirements.lock. Reported because
    # "which checker produced this verdict" is unanswerable afterwards otherwise, and a type sweep
    # whose tool version is unrecorded is the same category of claim as a solver run nobody logged.
    pyrightVersion  = $null
    breadth         = [ordered]@{}
    # Deliberately $null here, and assigned from $EXPECTED_SWEEP_FILES where that constant is
    # declared below. It held a hardcoded 15 until 2026-09-15, which was a SECOND representation of
    # the same expectation -- and it drifted the first time the constant moved: the Gate reported
    # "expected >= 15" while enforcing 19, in the same run. Caught by reading its own output.
    # *Principle 4, two representations of one thing will drift*, in the tool built to catch that.
    expectedBreadth = $null
    pytestCollected = $null
    pytestPassed    = $null
    pytestSkipped   = $null
    pytestXfailed   = $null
    pytestDeselected = $null
    collectedFloor  = $COLLECTED_FLOOR
    governance      = @()
    ranUtc          = (Get-Date).ToUniversalTime().ToString('o')
}

function Complete-Gate {
    param([string] $Status, [int] $Code, [string] $Reason)

    $result.status = $Status; $result.exitCode = $Code; $result.reason = $Reason

    if ($Json) {
        [pscustomobject]$result | ConvertTo-Json -Depth 6
    }
    else {
        Write-Host ''
        Write-Host '  ============ THE GATE ============' -ForegroundColor Magenta
        Write-Host "  status          : $Status" -ForegroundColor $(if ($Code -eq 0) { 'Green' } else { 'Red' })
        Write-Host "  reason          : $Reason"
        Write-Host "  stages run      : $($result.stagesRun -join ', ')"
        if ($result.stagesSkipped.Count) {
            Write-Host "  stages SKIPPED  : $($result.stagesSkipped -join ', ')" -ForegroundColor Yellow
        }
        Write-Host "  mypy files      : $($result.mypyFileCount)"
        Write-Host "  pyright files   : $($result.pyrightFileCount) (node pyright pinned to $($result.pyrightVersion))"
        $breadthLine = ($result.breadth.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join '  '
        Write-Host "  sweep breadth   : $breadthLine (expected >= $($result.expectedBreadth))"
        Write-Host "  pytest          : $($result.pytestCollected) collected / $($result.pytestPassed) passed (floor $COLLECTED_FLOOR)"
        # Reported unconditionally, including the zeroes. "0 skipped" is a result; a line that
        # appears only when something is wrong reads as absence rather than as a checked state.
        Write-Host "  pytest coverage : $($result.pytestSkipped) skipped, $($result.pytestXfailed) xfail/xpass, $($result.pytestDeselected) deselected"
        foreach ($g in $result.governance) { Write-Host "  governance      : $g" }
        Write-Host ''
        if ($Code -ne 0) {
            Write-Host '  A red Gate is the intended behaviour of a working Gate.' -ForegroundColor Yellow
            Write-Host '  Fix the cause; do not scope the check.' -ForegroundColor Yellow
        }
        else {
            Write-Host '  Green means no KNOWN class of error is present. It is not evidence' -ForegroundColor DarkGray
            Write-Host '  that the system works: no check visits a seam no test visits.' -ForegroundColor DarkGray
        }
        Write-Host ''
    }
    exit $Code
}

if ($SkipSlow) {
    Write-Host '  -SkipSlow is reserved and currently ignored. The Gate has no scoped variant.' -ForegroundColor Yellow
}

# --- 0. is there anything to run with ---------------------------------------
if (-not (Test-Path -LiteralPath $python)) {
    Complete-Gate 'TOOLING-ABSENT' $EXIT_TOOLING_ABSENT (
        "The venv interpreter is missing at '$python', so NOTHING was checked. This is not a " +
        'pass. Create it with: python -m venv .venv ; ' +
        '.\.venv\Scripts\python.exe -m pip install -e ".[dev]"'
    )
}

# Matplotlib must not try to open a window in a non-interactive run.
$env:MPLBACKEND = 'Agg'

function Invoke-Stage {
    param([string] $Name, [string[]] $Arguments)
    $out = & $python @Arguments 2>&1 | Out-String
    $script:result.stagesRun += $Name
    return @{ Output = $out; Code = $LASTEXITCODE }
}

# ---------------------------------------------------------------------------
# BREADTH.
#
# A test is the scoped check: it proves one property precisely. A whole-codebase static sweep is
# not another narrow check -- it is the ANTIDOTE to the narrowness of all the others, answering
# the one question no test can: did this local change break something lateral or downstream?
#
# From which the asymmetry that governs this section: narrowing a test makes a smaller test, still
# useful. Narrowing a SWEEP destroys its entire purpose, converting the anti-siloing layer into
# one more silo.
#
# The incident: a pyrightconfig.json excluding one package meant two files were never
# type-checked and held six real errors, with nothing reporting it. The config was internally
# consistent and silently narrower than anyone believed.
#
# So every sweep below must PROVE how many files it reached, and the Gate asserts that count
# against this expectation. Trusting a config to be as wide as intended is the same category of
# error as trusting a solver run nobody performed.
#
# RAISE THIS when source or test files are added.
#
# History:
#   Breadth hardening   15
#   Task 5              19   <- src/ehdpsu/{basis,breadcrumb}.py, tests/test_{basis,breadcrumb}.py
#   Task 6              22   <- src/ehdpsu/mk0_reference.py, tests/test_mk0_reproduction.py,
#                               tests/test_environment_lock.py
#   Task 7 (part)       24   <- src/ehdpsu/profile.py, tests/test_profile.py
#   Task 7 (rest)       26   <- tests/test_profile_seam.py, tests/test_solver_inputs.py
#   Profile/fixture     27   <- tests/conftest.py, which owns the frozen reference fixture
#   Task 8 (quantity)   29   <- src/ehdpsu/quantity.py, tests/test_quantity.py
#   Task 8 (op point)   31   <- src/ehdpsu/operating_point.py, tests/test_operating_point.py
#   FR-005 CLI          34   <- src/ehdpsu/{cli,__main__}.py, tests/test_cli.py
#   Task 9              37   <- src/ehdpsu/{claims,crossvalidate}.py, tests/test_crossvalidate.py
#   Adapter detection   39   <- src/ehdpsu/detect.py, tests/test_detect.py
#   Task 12             44   <- src/ehdpsu/adapters/{__init__,base,provenance,solvers}.py and
#                               tests/test_adapters.py
#   Task 13.0           45   <- src/ehdpsu/adapters/toolconfig.py
# ---------------------------------------------------------------------------
$EXPECTED_SWEEP_FILES = 53

# The one seam. The reported expectation and the enforced expectation are the same value, read
# through here, so the summary cannot describe a threshold the Gate is not applying.
$result.expectedBreadth = $EXPECTED_SWEEP_FILES

function Assert-Breadth {
    param([string] $Tool, [int] $Examined)
    $script:result.breadth[$Tool] = $Examined
    if ($Examined -lt $EXPECTED_SWEEP_FILES) {
        Complete-Gate 'SWEEP-TOO-NARROW' $EXIT_SWEEP_NARROW (
            "$Tool examined $Examined file(s), fewer than the $EXPECTED_SWEEP_FILES expected. A " +
            'sweep is whole-codebase or it is not a sweep: a silently narrowed sweep still ' +
            'reports success while the part it stopped reaching goes unchecked. Either a config ' +
            'excludes something undeclared, or the expectation is stale.'
        )
    }
}

# --- 1. ruff ----------------------------------------------------------------
# `--show-files` lists exactly what ruff WOULD check, which is how its breadth is proven. Ruff's
# normal output says nothing about how many files it reached, so a config narrowing it would
# otherwise be invisible.
$ruffFiles = Invoke-Stage 'ruff-breadth' @('-m', 'ruff', 'check', '--show-files', '.')
$ruffCount = @($ruffFiles.Output -split "`n" | Where-Object { $_.Trim() -match '\.py$' }).Count
Assert-Breadth 'ruff' $ruffCount

$ruff = Invoke-Stage 'ruff' @('-m', 'ruff', 'check', '.')
if ($ruff.Code -ne 0) {
    Complete-Gate 'RUFF-FAILED' $EXIT_RUFF (
        "ruff reported findings:`n" + ($ruff.Output.Trim() -split "`n" | Select-Object -Last 12 | Out-String)
    )
}

# --- 2. black ---------------------------------------------------------------
$black = Invoke-Stage 'black' @('-m', 'black', '--check', '.')
# black states its own breadth in the summary: "N files would be left unchanged" and/or
# "N files would be reformatted". Sum them, because a clean run and a dirty run word it
# differently and only the total proves breadth.
$blackCount = 0
foreach ($pattern in @('(\d+) files? would be left unchanged', '(\d+) files? would be reformatted')) {
    $bm = [regex]::Match($black.Output, $pattern)
    if ($bm.Success) { $blackCount += [int]$bm.Groups[1].Value }
}
Assert-Breadth 'black' $blackCount

if ($black.Code -ne 0) {
    Complete-Gate 'BLACK-FAILED' $EXIT_BLACK (
        "black reports formatting drift. Run: .\.venv\Scripts\python.exe -m black .`n" +
        ($black.Output.Trim() -split "`n" | Select-Object -Last 8 | Out-String)
    )
}

# --- 3. mypy, using the PROJECT'S OWN configuration -------------------------
# Deliberately no --python-version override. The whole point of this stage is that the project's
# configured invocation must work. Overriding it here would reproduce the exact defect this
# script was written to end.
$mypy = Invoke-Stage 'mypy' @('-m', 'mypy', 'src', 'tests')

# Harvest the file count from mypy's own summary line, e.g.
#   "Success: no issues found in 15 source files"
#   "Found 3 errors in 2 files (checked 15 source files)"
$fileCount = 0
$m = [regex]::Match($mypy.Output, 'in (\d+) source files?')
if (-not $m.Success) { $m = [regex]::Match($mypy.Output, 'checked (\d+) source files?') }
if ($m.Success) { $fileCount = [int]$m.Groups[1].Value }
$result.mypyFileCount = $fileCount

# This assertion is the reason the Gate exists. `errors prevented further checking` aborts
# collection, so mypy can exit non-zero having examined NOTHING -- which four consecutive task
# reports described as "one tidy error" plus a caveat.
if ($fileCount -eq 0) {
    Complete-Gate 'MYPY-CHECKED-NOTHING' $EXIT_MYPY_NOTHING (
        "mypy ran but examined ZERO source files, so no type checking occurred. This is NOT a " +
        "pass and must not be reported as one, nor worked around with an explicit " +
        "--python-version. Fix the configuration.`n" +
        ($mypy.Output.Trim() -split "`n" | Select-Object -Last 6 | Out-String)
    )
}
if ($mypy.Code -ne 0) {
    Complete-Gate 'MYPY-FAILED' $EXIT_MYPY (
        "mypy found type errors across $fileCount file(s):`n" +
        ($mypy.Output.Trim() -split "`n" | Select-Object -Last 12 | Out-String)
    )
}
Assert-Breadth 'mypy' $fileCount

# --- 3b. pyright, the second whole-codebase sweep ---------------------------
# Two type checkers rather than one because they demonstrably catch different classes. On the run
# that introduced this stage, pyright found three errors mypy did not -- including a real latent
# defect in telemetry.py where a function declared to return DataFrame could return
# `DataFrame | Series`, which mypy missed because it infers pandas loosely under
# `ignore_missing_imports`. Any downstream caller indexing the result would have broken.
#
# PINNING THE THING THAT ACTUALLY RUNS
# ------------------------------------
# `pyright==1.1.414` in requirements.lock pins the **Python wrapper**. The wrapper is not the type
# checker: on first use it downloads a **node package**, and that download is version-unconstrained.
# So the lock pinned the launcher while leaving the checker floating, and the local cache already
# held five node builds (1.1.409 through 1.1.414). requirements.lock's own stated reason for
# pinning dev tooling -- "a pyright release changes what it reports ... which makes it useless as a
# regression signal" -- was therefore not actually being met by the pin that claimed to meet it.
#
# `PYRIGHT_PYTHON_FORCE_VERSION` is the wrapper's documented control for this. It is derived from
# the lock rather than written here as a literal: a second copy of the version would be a second
# representation, and *principle 4, two representations of one thing will drift*, says which way
# that goes. A drifted copy would be invisible, because pinning to the wrong version does not
# error -- it silently type-checks with a different checker than the one the lock names.
$lockPath = Join-Path $repoRoot 'requirements.lock'
$pinnedPyright = $null
if (Test-Path -LiteralPath $lockPath) {
    $pm = [regex]::Match(
        (Get-Content -LiteralPath $lockPath -Raw),
        '(?m)^pyright==([0-9]+\.[0-9]+\.[0-9]+)\s*$'
    )
    if ($pm.Success) { $pinnedPyright = $pm.Groups[1].Value }
}
if (-not $pinnedPyright) {
    Complete-Gate 'PYRIGHT-UNPINNED' $EXIT_PYRIGHT_UNPINNED (
        "no `pyright==<version>` pin could be read from requirements.lock, so the node pyright " +
        'that would run is whatever the wrapper last downloaded. That is not an absent tool and ' +
        'must not be reported as one: pyright would run, examine every file, and produce a ' +
        'verdict from an unknown version. A Gate whose result depends on an unrecorded tool ' +
        'version is not a regression signal.'
    )
}
$env:PYRIGHT_PYTHON_FORCE_VERSION = $pinnedPyright
$result.pyrightVersion = $pinnedPyright

$pyrightJson = Join-Path ([System.IO.Path]::GetTempPath()) "gate_pyright_$PID.json"
$pyrightRaw = & $python @('-m', 'pyright', '--outputjson', 'src', 'tests') 2>&1 | Out-String
$result.stagesRun += 'pyright'
Set-Content -LiteralPath $pyrightJson -Value $pyrightRaw -Encoding utf8

$pyrightParsed = $null
try {
    # pyright prepends npm noise on some installs; take from the first brace.
    $brace = $pyrightRaw.IndexOf('{')
    if ($brace -ge 0) { $pyrightParsed = $pyrightRaw.Substring($brace) | ConvertFrom-Json }
}
catch { $pyrightParsed = $null }
finally { Remove-Item -LiteralPath $pyrightJson -Force -ErrorAction SilentlyContinue }

if ($null -eq $pyrightParsed) {
    Complete-Gate 'PYRIGHT-FAILED' $EXIT_PYRIGHT (
        "pyright output could not be parsed, so it is unknown whether it checked anything. An " +
        "unreadable result is not a pass.`n" +
        ($pyrightRaw.Trim() -split "`n" | Select-Object -Last 8 | Out-String)
    )
}

$pyrightCount = [int]$pyrightParsed.summary.filesAnalyzed
$pyrightErrors = [int]$pyrightParsed.summary.errorCount
$result.pyrightFileCount = $pyrightCount
Assert-Breadth 'pyright' $pyrightCount

if ($pyrightErrors -gt 0) {
    $detail = $pyrightParsed.generalDiagnostics | ForEach-Object {
        "$(Split-Path $_.file -Leaf):$($_.range.start.line + 1) [$($_.rule)] $(($_.message -split "`n")[0])"
    }
    Complete-Gate 'PYRIGHT-FAILED' $EXIT_PYRIGHT (
        "pyright found $pyrightErrors error(s) across $pyrightCount file(s):`n" +
        ($detail | Select-Object -First 12 | Out-String)
    )
}

# --- 3c. the two checkers must examine the SAME set -------------------------
# A silent divergence between them is a blind spot shaped exactly like one tool's config, and it
# would not show up as a failure in either. This is the check that would have caught the
# pyrightconfig exclusion directly.
if ($fileCount -ne $pyrightCount) {
    Complete-Gate 'CHECKER-DIVERGED' $EXIT_CHECKER_DIVERGED (
        "mypy examined $fileCount file(s) and pyright examined $pyrightCount. The two type " +
        'checkers must cover the same set: a divergence means one of them has a blind spot in ' +
        "the shape of the other's configuration, and neither reports it as a failure."
    )
}

# --- 4. pytest --------------------------------------------------------------
$pytest = Invoke-Stage 'pytest' @('-m', 'pytest', '-q')

# Parse the summary line. Judge on COLLECTED, never on passed alone.
#
# Every non-passing outcome is parsed separately, because they mean different things and folding
# them together produces a confident wrong diagnosis.
#
# The bug this replaced, found 2026-09-15 while answering "do we use xfails?": only `(\d+) passed`
# was read, and `collected` fell back to `passed` when `-q` printed no collected line. With any
# skip or xfail, `-q` prints "380 passed, 9 skipped" and NO collected line -- so collected became
# 380, the floor check failed, and the Gate reported PYTEST-UNDER-FLOOR with the message "a
# collection error is hiding". Red for the right reason and blamed on the wrong cause, which sends
# the reader hunting an ImportError that does not exist.
# *Principle 2, an approximately-correct identifier is worse than an absent one.*
#
# THE SECOND BUG IN THIS PARSER, found 2026-09-19 while writing the CRSDL batch specifications.
#
# `Get-PytestCount` matched `(\d+) <word>` anywhere in pytest's ENTIRE output, not on its summary
# line. pytest prints each failing test's source -- docstring included -- in the traceback, and two
# of the new specification files contain the phrase `"1 error"` while explaining why they resolve a
# module dynamically. So `$errored` parsed as 1 from a test's own prose, `collected` was
# reconstructed as 1136 against an actual 1135, and the Gate reported a count one higher than
# reality.
#
# Inflation is the dangerous direction: it would mask a genuine drop in collected tests, which is
# precisely what the floor exists to catch. A test's *prose* could silently raise the Gate's count.
# *Principle 2, an approximately-correct identifier is worse than an absent one* -- the number was
# non-empty, plausible, and wrong.
#
# Fixed by anchoring to the summary line. pytest ends with `52 failed, 1083 passed in 61.65s`, so a
# line carrying both an outcome count and a duration is the only place counts are read from.
function Get-PytestSummaryLine {
    param([string] $Output)
    $lines = @(($Output -split "`r?`n") | Where-Object { $_.Trim() })
    for ($i = $lines.Count - 1; $i -ge 0; $i--) {
        if ($lines[$i] -match '\d+\s+(passed|failed|error|errors|skipped|xfailed|xpassed|deselected|no tests ran)' -and
            $lines[$i] -match '\bin\s+[\d.]+s') {
            return $lines[$i]
        }
    }
    return ''
}

$summaryLine = Get-PytestSummaryLine $pytest.Output

function Get-PytestCount {
    param([string] $Summary, [string] $Word)
    $m = [regex]::Match($Summary, "(\d+) $Word")
    if ($m.Success) { return [int]$m.Groups[1].Value }
    return 0
}

$passed = Get-PytestCount $summaryLine 'passed'
$skipped = Get-PytestCount $summaryLine 'skipped'
$xfailed = Get-PytestCount $summaryLine 'xfailed'
$xpassed = Get-PytestCount $summaryLine 'xpassed'
$failed = Get-PytestCount $summaryLine 'failed'
$errored = Get-PytestCount $summaryLine 'error'
$deselected = Get-PytestCount $summaryLine 'deselected'

$collected = $null
$cm = [regex]::Match($pytest.Output, '(\d+) tests? collected')
if ($cm.Success) {
    $collected = [int]$cm.Groups[1].Value
}
else {
    # No explicit collected line: reconstruct it from EVERY outcome, including failures, rather
    # than from `passed`. Done regardless of the exit code, because a failing run previously left
    # this null and the report rendered "  collected / 394 passed" with a blank -- a blank figure
    # in a report is read as zero or as absence rather than as unknown.
    $sum = $passed + $skipped + $xfailed + $xpassed + $deselected + $failed + $errored
    if ($sum -gt 0) { $collected = $sum }
    # Still null when nothing at all could be parsed, which the check below treats as unreadable.
}

$result.pytestCollected = $collected
$result.pytestPassed = $passed
$result.pytestSkipped = $skipped
$result.pytestXfailed = $xfailed + $xpassed
$result.pytestDeselected = $deselected

if ($pytest.Code -ne 0) {
    Complete-Gate 'PYTEST-FAILED' $EXIT_PYTEST (
        "pytest failed ($collected collected, $passed passed):`n" +
        ($pytest.Output.Trim() -split "`n" | Select-Object -Last 15 | Out-String)
    )
}
if ($null -eq $collected) {
    Complete-Gate 'PYTEST-UNDER-FLOOR' $EXIT_PYTEST_FLOOR (
        'pytest exited zero but its collected count could not be parsed, so it is unknown ' +
        'whether anything ran. An unreadable result is not a pass.'
    )
}
if ($collected -lt $COLLECTED_FLOOR) {
    Complete-Gate 'PYTEST-UNDER-FLOOR' $EXIT_PYTEST_FLOOR (
        "pytest collected $collected test(s), below the floor of $COLLECTED_FLOOR. Tests do not " +
        'vanish on their own: one ImportError in one module aborts collection for everything ' +
        'after it while the report still looks normal. Either a collection error is hiding, or ' +
        'checks were deleted.'
    )
}

# --- coverage reduction: distinct from both PASS and FAIL -------------------------------------
#
# A skipped or xfailed test collected and did not run. The floor cannot see that on its own -- the
# count is satisfied while the coverage is not -- which is the same failure the floor exists to
# catch, one level up.
#
# `SKIPPED`, `NOT-SCANNED` and `INCOMPLETE` are distinct from `CLEAN`. A run with skips is
# incomplete, and it gets its own status rather than being folded into OK.
#
# On xfail specifically: this project has never used one and this is where that becomes a policy
# rather than a habit. An `xfail` is a tolerated known defect, and the answer here to a known-bad
# value is to withhold it and record why -- `sweep_stages.csv` is the live example. A non-strict
# xfail is worse still: it passes whether the test fails OR succeeds, so it conceals a fix as
# readily as a defect.
if ($xfailed -gt 0 -or $xpassed -gt 0 -or $skipped -gt 0 -or $deselected -gt 0) {
    Complete-Gate 'PYTEST-COVERAGE-REDUCED' $EXIT_PYTEST_COVERAGE (
        "pytest collected $collected and ran ${passed}: " +
        "$skipped skipped, $xfailed xfailed, $xpassed xpassed, $deselected deselected. " +
        "Those tests did not verify anything, so this run is INCOMPLETE rather than clean.`n" +
        '  A skip is usually an absent tool -- check whether git, pip or a solver went missing ' +
        "rather than assuming the environment is fine.`n" +
        '  An xfail or xpassed is a policy breach: this project withholds a known-bad value and ' +
        'records why, instead of shipping a test that tolerates it.'
    )
}

# --- 4b. no undeclared exclusions in any tool config ------------------------
# The maccre_tui failure, mechanised. An exclusion is not wrong; an UNDECLARED one is, because it
# narrows a sweep invisibly. `ehd-dev-rules.md` carries the declaration register, and this stage
# asserts that every exclusion appearing in a tool config is named there.
$devRulesPath = Join-Path $repoRoot '.kiro\steering\ehd-dev-rules.md'
if (-not (Test-Path -LiteralPath $devRulesPath)) {
    Complete-Gate 'UNDECLARED-EXCLUSION' $EXIT_UNDECLARED_EXCLUSION (
        "ehd-dev-rules.md is missing, so the exclusion declaration register cannot be read and no " +
        'exclusion can be verified as declared.'
    )
}
$devRules = Get-Content -LiteralPath $devRulesPath -Raw
$result.stagesRun += 'exclusion-declarations'

$configFiles = @('pyproject.toml', 'pyrightconfig.json', 'ruff.toml', 'setup.cfg', 'mypy.ini') |
    ForEach-Object { Join-Path $repoRoot $_ } | Where-Object { Test-Path -LiteralPath $_ }

$undeclared = @()
foreach ($cfg in $configFiles) {
    foreach ($line in (Get-Content -LiteralPath $cfg)) {
        # Match an exclusion KEY being assigned, not a comment discussing one. A checker that
        # cannot distinguish discussing a thing from doing it is not a checker -- that trap has
        # already been hit three times in this project.
        if ($line -match '^\s*(exclude|extend-exclude|ignore|exclude_dirs|excludePatterns?)\s*[:=]') {
            $value = ($line -split '[:=]', 2)[1]
            foreach ($tok in [regex]::Matches($value, '[''"]([^''"]+)[''"]')) {
                $path = $tok.Groups[1].Value
                if ($devRules -notmatch [regex]::Escape($path)) {
                    $undeclared += "$(Split-Path $cfg -Leaf): '$path' excluded but not declared"
                }
            }
        }
    }
}
if ($undeclared.Count -gt 0) {
    Complete-Gate 'UNDECLARED-EXCLUSION' $EXIT_UNDECLARED_EXCLUSION (
        "$($undeclared.Count) undeclared exclusion(s) found. Every exclusion must be named and " +
        "justified in ehd-dev-rules.md, or a sweep is narrower than anyone believes:`n" +
        ($undeclared | Out-String)
    )
}

# --- 5. governance verifiers ------------------------------------------------
# These belong in the Gate because steering, skills, agent seats and model pins drift exactly as
# readily as code. The model pin probe is deliberately EXCLUDED: it invokes an external CLI over
# the network, which makes it slow and non-deterministic. It is run explicitly when a pin changes.
$governanceScripts = @(
    @{ Name = 'verify_citations'; Path = (Join-Path $PSScriptRoot 'verify_citations.ps1') }
    @{ Name = 'verify_no_artifacts_tracked'; Path = (Join-Path $PSScriptRoot 'verify_no_artifacts_tracked.ps1') }
)
$result.stagesSkipped += 'model_pin_probe (external CLI; run explicitly when a pin changes)'

foreach ($g in $governanceScripts) {
    if (-not (Test-Path -LiteralPath $g.Path)) {
        Complete-Gate 'GOVERNANCE-FAILED' $EXIT_GOVERNANCE (
            "$($g.Name) is missing at '$($g.Path)'. A governance check that is absent is not a " +
            'check that passed.'
        )
    }
    $out = & pwsh -NoProfile -File $g.Path 2>&1 | Out-String
    $code = $LASTEXITCODE
    $result.stagesRun += $g.Name
    $result.governance += "$($g.Name) -> exit $code"
    if ($code -ne 0) {
        Complete-Gate 'GOVERNANCE-FAILED' $EXIT_GOVERNANCE (
            "$($g.Name) exited ${code}:`n" +
            ($out.Trim() -split "`n" | Select-Object -Last 12 | Out-String)
        )
    }
}

# --- 6. terminal state ------------------------------------------------------
Complete-Gate 'OK' $EXIT_OK (
    "ruff and black swept $ruffCount/$blackCount files; mypy and pyright (node $pinnedPyright, " +
    "forced from the lock) both examined " +
    "$fileCount (agreeing, expected >= $EXPECTED_SWEEP_FILES); no undeclared exclusions; " +
    "pytest $collected collected / $passed passed at floor $COLLECTED_FLOOR; " +
    "$($governanceScripts.Count) governance verifier(s) passed. " +
    'The model pin probe was NOT run; run it explicitly when a pin changes.'
)
