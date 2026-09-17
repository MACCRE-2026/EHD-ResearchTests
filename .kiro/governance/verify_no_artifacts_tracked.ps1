#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Verifies that the project datacenter never entered the git index, that it is actively
    ignored, and that no directory in this repository sits in a MIXED tracked/ignored state.

.DESCRIPTION
    THE INCIDENT THIS ENCODES
    -------------------------
    `.gitignore` carried this line, and nothing else about the datacenter:

        !artifacts/.gitkeep

    A negation with NO preceding ignore rule for `artifacts/` silently does nothing. Git does
    not warn. So the folder was never ignored at all, four generated files were committed
    inside it, and the repository sat in a MIXED state -- part tracked, part untracked, with a
    line in `.gitignore` that read as though the matter had been handled.

    That mattered because `artifacts/` holds AI collaborator transcripts and session handovers
    containing framing and persona material, and the remote is intended to become public. The
    folder-level ignore is the only enforcement between that content and a public URL.

    WHY MIXED IS REPORTED AS A DEFECT AND NOT AN OBSERVATION
    -------------------------------------------------------
    `.gitignore` only prevents UNTRACKED files from being added. Anything already tracked stays
    tracked forever and keeps being committed regardless of the ignore rule. So a MIXED
    directory is a live hole that looks closed. It needs a decision (`git rm --cached`), which
    is a mutation, so this script reports and proposes; it does not fix.

    WHAT IT CHECKS
    --------------
    1. Nothing under `artifacts/` is in the index. `git ls-files` is authoritative here --
       `git status` is not, because a staged rename or deletion makes an already-removed path
       appear there and read like residue.
    2. `artifacts/` is ACTIVELY ignored, proven with `git check-ignore` against a path that
       does not exist. Distinct from check 1: that one proves nothing is tracked now, this one
       proves a new file could not become tracked.
    3. No ignored directory anywhere in the repo is in a MIXED state.
    4. No tracked file lives at a path this project has declared must stay untracked.

    A note on scope, because it is the whole point of stating one: this inspects the WORKING
    TREE and the INDEX. It does not inspect history. Content committed and later removed is
    still in the object database and still public if it was ever pushed. This script can
    therefore never justify "the repository is clean" -- only "no findings in the index".

.PARAMETER RepoRoot
    Repository root. Defaults to two levels above this script.

.OUTPUTS
    Exit codes, all distinct:
        0  OK               datacenter absent from the index, actively ignored, no MIXED dirs
        2  TRACKED-IN-DC    one or more files under artifacts/ are in the index
        3  NOT-IGNORED      artifacts/ is not actually ignored by git
        4  MIXED-DIRECTORY  an ignored directory holds tracked files
        5  GIT-UNUSABLE     git is absent or the path is not a repository; nothing was checked

.EXAMPLE
    pwsh -File .kiro/governance/verify_no_artifacts_tracked.ps1
#>

[CmdletBinding()]
param(
    [string] $RepoRoot,
    [switch] $Json
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$EXIT_OK          = 0
$EXIT_TRACKED     = 2
$EXIT_NOT_IGNORED = 3
$EXIT_MIXED       = 4
$EXIT_GIT_UNUSABLE = 5

if (-not $RepoRoot) {
    $RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}

# Directories this project has declared must never hold tracked content.
$MUST_STAY_UNTRACKED = @('artifacts', '.venv', '.tmp.driveupload', '.tmp.drivedownload')

$result = [ordered]@{
    status          = $null
    exitCode        = $null
    reason          = $null
    repoRoot        = $RepoRoot
    trackedInDc     = @()
    notIgnored      = @()
    mixedDirs       = @()
    ignoredDirsSeen = 0
    trackedTotal    = 0
    checkedUtc      = (Get-Date).ToUniversalTime().ToString('o')
}

function Complete-Check {
    param([string] $Status, [int] $Code, [string] $Reason)

    $result.status = $Status; $result.exitCode = $Code; $result.reason = $Reason

    if ($Json) {
        [pscustomobject]$result | ConvertTo-Json -Depth 6
    }
    else {
        Write-Host ''
        Write-Host "  status            : $Status" -ForegroundColor $(if ($Code -eq 0) { 'Green' } else { 'Red' })
        Write-Host "  reason            : $Reason"
        Write-Host "  tracked files     : $($result.trackedTotal)"
        Write-Host "  ignored dirs seen : $($result.ignoredDirsSeen)"
        foreach ($group in @(
                @{ Name = 'TRACKED INSIDE A MUST-STAY-UNTRACKED DIR'; Items = $result.trackedInDc },
                @{ Name = 'NOT ACTUALLY IGNORED'; Items = $result.notIgnored },
                @{ Name = 'MIXED TRACKED/IGNORED DIRECTORIES'; Items = $result.mixedDirs }
            )) {
            if ($group.Items.Count) {
                Write-Host "  $($group.Name):" -ForegroundColor Red
                foreach ($i in $group.Items) { Write-Host "      $i" }
            }
        }
        Write-Host ''
        Write-Host '  Scope: working tree and index only. History was NOT scanned.' -ForegroundColor DarkGray
        if ($Code -ne 0) {
            Write-Host '  Remedy for a tracked remnant is `git rm --cached -- <path>`, which is a' -ForegroundColor Yellow
            Write-Host '  mutation. This script reports; the operator decides.' -ForegroundColor Yellow
        }
        Write-Host ''
    }
    exit $Code
}

function Invoke-Git {
    param([string[]] $Arguments)
    $out = & git -C $RepoRoot @Arguments 2>&1
    return @{ Output = $out; Code = $LASTEXITCODE }
}

# --- 0. is git usable at all -------------------------------------------------
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Complete-Check 'GIT-UNUSABLE' $EXIT_GIT_UNUSABLE (
        'git is not on PATH, so NOTHING was checked. This is not a pass.'
    )
}
$probe = Invoke-Git @('rev-parse', '--is-inside-work-tree')
if ($probe.Code -ne 0) {
    Complete-Check 'GIT-UNUSABLE' $EXIT_GIT_UNUSABLE (
        "'$RepoRoot' is not a git work tree (git exit $($probe.Code)). Nothing was checked."
    )
}

$allTracked = @((Invoke-Git @('ls-files')).Output | Where-Object { $_ })
$result.trackedTotal = $allTracked.Count

# A repo with zero tracked files would make every check below vacuously pass.
if ($result.trackedTotal -eq 0) {
    Complete-Check 'GIT-UNUSABLE' $EXIT_GIT_UNUSABLE (
        'The index holds zero files. Every check below would pass vacuously, so this is ' +
        'reported as unusable rather than clean.'
    )
}

# --- 1. nothing tracked inside a must-stay-untracked directory ---------------
foreach ($dir in $MUST_STAY_UNTRACKED) {
    $tracked = @((Invoke-Git @('ls-files', '--', $dir)).Output | Where-Object { $_ })
    foreach ($t in $tracked) {
        $result.trackedInDc += "$t  (inside '$dir', which must never hold tracked content)"
    }
}

# --- 2. those directories are ACTIVELY ignored -------------------------------
# Probe a path that does not exist, with --no-index, so the answer reflects the ignore rules
# rather than the current index state.
foreach ($dir in $MUST_STAY_UNTRACKED) {
    $probePath = "$dir/__verify_ignore_probe__.tmp"
    $chk = Invoke-Git @('check-ignore', '-q', '--no-index', $probePath)
    if ($chk.Code -ne 0) {
        $result.notIgnored += "$dir/ is NOT ignored (check-ignore exit $($chk.Code)). A negation without a matching ignore rule does nothing."
    }
}

# --- 3. MIXED tracked/ignored directories ------------------------------------
# Gather ignored directory paths git itself reports, then ask whether any hold tracked files.
#
# NOTE ON THE FLAGS, because getting this wrong produced a silent false pass during
# development: this deliberately uses the DEFAULT untracked mode, NOT
# `--untracked-files=all`. In `all` mode git expands every ignored directory into its
# individual files -- 13,626 of them here -- and none of those paths ends in `/`, so a
# directory filter matches ZERO entries and the check passes having examined nothing. The
# default mode collapses ignored directories to `dir/` entries, which is what this needs.
#
# That failure was precisely *principle 3, never report success over unperformed work*,
# occurring inside the script written to enforce it. Hence the zero-count guard below.
$ignoredEntries = @((Invoke-Git @(
            'status', '--porcelain', '--ignored'
        )).Output | Where-Object { $_ -match '^!!\s' } | ForEach-Object { ($_ -replace '^!!\s+', '').Trim('"') })

$ignoredDirs = @($ignoredEntries | Where-Object { $_.EndsWith('/') } | Sort-Object -Unique)
$result.ignoredDirsSeen = $ignoredDirs.Count

# This repository ignores .venv/, artifacts/, the caches and the Drive staging dirs, so a
# count of zero means the enumeration failed rather than that the repo is tidy.
if ($result.ignoredDirsSeen -eq 0) {
    Complete-Check 'GIT-UNUSABLE' $EXIT_GIT_UNUSABLE (
        'Zero ignored directories were enumerated, so the MIXED check examined nothing. This ' +
        'repository has ignore rules for artifacts/, .venv/ and several caches, so an empty ' +
        'enumeration is a broken query -- not a clean result.'
    )
}

foreach ($d in $ignoredDirs) {
    $clean = $d.TrimEnd('/')
    if (-not $clean) { continue }
    $tracked = @((Invoke-Git @('ls-files', '--', $clean)).Output | Where-Object { $_ })
    if ($tracked.Count -gt 0) {
        $result.mixedDirs += (
            "$clean : MIXED -- ignored by a rule yet holds $($tracked.Count) tracked file(s). " +
            "An ignore rule does nothing for already-tracked files; this hole looks closed."
        )
    }
}

# --- 4. terminal state -------------------------------------------------------
if ($result.trackedInDc.Count -gt 0) {
    Complete-Check 'TRACKED-IN-DC' $EXIT_TRACKED (
        "$($result.trackedInDc.Count) file(s) tracked inside a directory declared untracked. " +
        'artifacts/ holds conversation transcripts and the remote is intended to become public.'
    )
}
if ($result.notIgnored.Count -gt 0) {
    Complete-Check 'NOT-IGNORED' $EXIT_NOT_IGNORED (
        "$($result.notIgnored.Count) declared-untracked directory/ies are not actually ignored. " +
        'Nothing is tracked in them yet, which is luck rather than enforcement.'
    )
}
if ($result.mixedDirs.Count -gt 0) {
    Complete-Check 'MIXED-DIRECTORY' $EXIT_MIXED (
        "$($result.mixedDirs.Count) directory/ies are in a MIXED tracked/ignored state. This " +
        'needs a decision, not a note.'
    )
}

Complete-Check 'OK' $EXIT_OK (
    "$($result.trackedTotal) tracked file(s) checked: none inside " +
    "$($MUST_STAY_UNTRACKED.Count) declared-untracked directories, all of which are actively " +
    "ignored, and none of $($result.ignoredDirsSeen) ignored directories is MIXED. " +
    'History not scanned.'
)
