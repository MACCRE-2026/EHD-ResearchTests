<#
.SYNOPSIS
    One command from a clean clone to a verified working environment.

.DESCRIPTION
    Creates .venv, installs the exact pins from requirements.lock, installs this project
    editable, and then PROVES the result rather than asserting it: it imports the package and
    reproduces the MK0 reference figures.

    The venv is deliberately NOT vendored in the repository. Decided 2026-09-15: it is ~408 MB,
    and `pyvenv.cfg` plus `Scripts\*.exe` embed absolute paths, so a committed venv would only
    work on the machine that built it. Reproducibility comes from an exact lock plus this script.
    See artifacts/00_Governance/2026-09-15_PLAN_ehd_modeling_suite.md, appended decisions.

    Every step's outcome is COUNTED before anything is reported as done --
    *principle 3, never report success over unperformed work*. A partially installed environment
    gets its own distinct exit code rather than being folded into success.

.PARAMETER Recreate
    Delete an existing .venv and build it fresh. Without this, an existing .venv is reused and
    installed into, which is idempotent but will not repair a venv built on a different Python.

.EXAMPLE
    .\bootstrap.ps1

.EXAMPLE
    .\bootstrap.ps1 -Recreate

.NOTES
    Exit codes
      0  OK                    environment installed and MK0 figures reproduced
      2  NO-PYTHON             no interpreter found at all
      3  PYTHON-TOO-OLD        found an interpreter, but below 3.12
      4  VENV-CREATE-FAILED    python -m venv did not produce a usable interpreter
      5  LOCK-MISSING          requirements.lock absent
      6  LOCK-INSTALL-FAILED   pip install -r requirements.lock returned non-zero
      7  PROJECT-INSTALL-FAILED  pip install -e . returned non-zero
      8  LOCK-DRIFT            installed set does not match requirements.lock
      9  VERIFY-FAILED         package will not import, or MK0 figures did not reproduce

    This script does NOT run the Gate. The Gate is the whole-codebase sweep and takes minutes;
    run it separately once this finishes:  pwsh -File .kiro\governance\gate.ps1
#>

[CmdletBinding()]
param(
    [switch] $Recreate
)

$ErrorActionPreference = 'Stop'

$repoRoot = $PSScriptRoot
$venvDir = Join-Path $repoRoot '.venv'
$venvPython = Join-Path $venvDir 'Scripts\python.exe'
$lockFile = Join-Path $repoRoot 'requirements.lock'

# Minimum supported Python. Narrowed from 3.11 on 2026-09-15: numpy 2.5.3's stubs use `type`
# statements, so mypy cannot parse them while targeting 3.11 and aborts having checked ZERO
# files. Under this dependency set 3.11 is unverifiable rather than merely untested, and
# claiming a version the Gate cannot check is the drift *principle 5* describes.
$minMajor = 3
$minMinor = 12

function Stop-Bootstrap {
    param([string] $Status, [int] $Code, [string] $Reason)
    Write-Host ''
    Write-Host "  ==== BOOTSTRAP: $Status ===="
    Write-Host "  $Reason"
    Write-Host ''
    exit $Code
}

function Write-Step {
    param([string] $Message)
    Write-Host "  [bootstrap] $Message"
}

Write-Host ''
Write-Host '  ==== EHD-ResearchTests bootstrap ===='

# --- 0. the lock must exist before anything is created ---------------------------------------
# Checked first, so a missing lock fails before a 400 MB venv is built for nothing.
if (-not (Test-Path -LiteralPath $lockFile)) {
    Stop-Bootstrap 'LOCK-MISSING' 5 (
        "requirements.lock not found at $lockFile. Regenerate it from a known-good environment " +
        "with `pip freeze --all`, or check out a revision that carries it."
    )
}

# --- 1. find an interpreter -------------------------------------------------------------------
if ($Recreate -and (Test-Path -LiteralPath $venvDir)) {
    Write-Step "removing existing .venv (-Recreate)"
    Remove-Item -LiteralPath $venvDir -Recurse -Force
}

if (-not (Test-Path -LiteralPath $venvPython)) {
    $candidates = @(
        @{ Exe = 'py'; Args = @('-3.12') },
        @{ Exe = 'py'; Args = @('-3') },
        @{ Exe = 'python'; Args = @() },
        @{ Exe = 'python3'; Args = @() }
    )

    $chosen = $null
    $bestSeen = $null
    foreach ($candidate in $candidates) {
        if (-not (Get-Command $candidate.Exe -ErrorAction SilentlyContinue)) { continue }
        $probe = & $candidate.Exe @($candidate.Args + @(
                '-c', 'import sys; print("%d.%d.%d" % sys.version_info[:3])'
            )) 2>&1
        if ($LASTEXITCODE -ne 0) { continue }
        $version = [version]("$probe".Trim())
        $bestSeen = if ($bestSeen -and $bestSeen -gt $version) { $bestSeen } else { $version }
        if ($version.Major -gt $minMajor -or
            ($version.Major -eq $minMajor -and $version.Minor -ge $minMinor)) {
            $chosen = $candidate
            Write-Step "using $($candidate.Exe) $($candidate.Args -join ' ') -> Python $version"
            break
        }
    }

    if (-not $chosen -and -not $bestSeen) {
        Stop-Bootstrap 'NO-PYTHON' 2 (
            'No Python interpreter found on PATH (tried py, python, python3). Install Python ' +
            "$minMajor.$minMinor or later from python.org and re-run."
        )
    }
    if (-not $chosen) {
        Stop-Bootstrap 'PYTHON-TOO-OLD' 3 (
            "The newest interpreter found is Python $bestSeen, below the required " +
            "$minMajor.$minMinor. This is not a style preference: below 3.12, mypy cannot parse " +
            'numpy''s stubs and aborts having checked zero files, so the type sweep would report ' +
            'an exit code over no work at all.'
        )
    }

    # --- 2. create the venv -------------------------------------------------------------------
    Write-Step 'creating .venv'
    & $chosen.Exe @($chosen.Args + @('-m', 'venv', $venvDir))
    if (-not (Test-Path -LiteralPath $venvPython)) {
        Stop-Bootstrap 'VENV-CREATE-FAILED' 4 (
            "python -m venv completed but $venvPython does not exist. The venv is unusable; " +
            'nothing further was installed.'
        )
    }
}
else {
    Write-Step '.venv already present, installing into it (use -Recreate to rebuild)'
}

$venvVersion = (& $venvPython -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])').Trim()
Write-Step "venv interpreter: Python $venvVersion"

# --- 3. install the locked dependencies -------------------------------------------------------
Write-Step 'installing requirements.lock'
& $venvPython -m pip install --disable-pip-version-check --quiet -r $lockFile
if ($LASTEXITCODE -ne 0) {
    Stop-Bootstrap 'LOCK-INSTALL-FAILED' 6 (
        "pip install -r requirements.lock exited $LASTEXITCODE. The environment is PARTIALLY " +
        'installed; do not run the Gate against it and do not treat any result from it as ' +
        'meaningful.'
    )
}

# --- 4. install the project itself ------------------------------------------------------------
# `--no-deps` because the lock already supplies every dependency at an exact version. Without it
# pip re-resolves numpy, scipy and pandas and may pull versions the lock does not name, which
# would defeat the lock while appearing to succeed.
#
# Build isolation still fetches setuptools>=61 from PyPI at build time, per pyproject.toml's
# build-requires, and that fetch is NOT pinned by requirements.lock. Stated rather than glossed:
# the lock covers the runtime and tooling environment, not the build backend.
Write-Step 'installing ehdpsu (editable, --no-deps)'
& $venvPython -m pip install --disable-pip-version-check --quiet --no-deps -e $repoRoot
if ($LASTEXITCODE -ne 0) {
    Stop-Bootstrap 'PROJECT-INSTALL-FAILED' 7 (
        "pip install -e . exited $LASTEXITCODE. Dependencies are installed but the project is " +
        'not importable.'
    )
}

# --- 5. verify the installed set against the lock ---------------------------------------------
# The install exiting zero is not evidence that the environment matches the lock: a pre-existing
# venv can carry extra or newer packages that pip had no reason to touch.
$lockPins = @(Get-Content -LiteralPath $lockFile |
    ForEach-Object { $_.Trim() } |
    Where-Object { $_ -and -not $_.StartsWith('#') })
$installed = @(& $venvPython -m pip freeze --all |
    ForEach-Object { $_.Trim() } |
    Where-Object { $_ -and $_ -notmatch '^-e ' -and $_ -notmatch '^(ehdpsu|pip)==' })

$missing = @($lockPins | Where-Object { $installed -notcontains $_ })
$extra = @($installed | Where-Object { $lockPins -notcontains $_ })

if ($missing.Count -gt 0 -or $extra.Count -gt 0) {
    $detail = ''
    if ($missing.Count -gt 0) { $detail += "`n  locked but not installed: $($missing -join ', ')" }
    if ($extra.Count -gt 0) { $detail += "`n  installed but not locked: $($extra -join ', ')" }
    Stop-Bootstrap 'LOCK-DRIFT' 8 (
        "the installed environment does not match requirements.lock.$detail`n" +
        '  Re-run with -Recreate for a clean build, or regenerate the lock if the change is ' +
        'intended.'
    )
}
Write-Step "verified $($lockPins.Count) pinned package(s) match the installed set"

# --- 6. prove it works, rather than reporting that it installed -------------------------------
Write-Step 'reproducing the MK0 reference figures'
& $venvPython -m pytest (Join-Path $repoRoot 'tests\test_mk0_reproduction.py') -q
$reproCode = $LASTEXITCODE
if ($reproCode -ne 0) {
    Stop-Bootstrap 'VERIFY-FAILED' 9 (
        "the MK0 reproduction test exited $reproCode. The environment installed cleanly and the " +
        'physics does not reproduce in it, which is a finding about this machine or about the ' +
        'code -- not a bootstrap problem to retry.'
    )
}

Stop-Bootstrap 'OK' 0 (
    "Python $venvVersion, $($lockPins.Count) pinned package(s) verified against " +
    "requirements.lock, ehdpsu installed editable, MK0 reference figures reproduced.`n" +
    "  Activate with:  .\.venv\Scripts\Activate.ps1`n" +
    "  This did NOT run the whole-codebase sweep. For that:  " +
    'pwsh -File .kiro\governance\gate.ps1'
)
