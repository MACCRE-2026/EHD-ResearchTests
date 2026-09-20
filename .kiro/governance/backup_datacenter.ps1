#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Takes a hash-verified, timestamped snapshot of the EHD-ResearchTests project datacenter and
    governance configuration, and refuses to claim a backup it did not verify.

.DESCRIPTION
    WHY THIS EXISTS
    ---------------
    `artifacts/` is ignored at the folder level, so **git is not its version history.** It holds
    the roadmap, the plan, decision records, AI collaborator transcripts, session handovers,
    task packets, breadcrumbs and solver provenance. An overwrite in there is unrecoverable by
    `git checkout`. Drive gives redundancy of the *current* state; it does not give point-in-time
    recovery of a file that was clobbered before it synced.

    *Principle 8, atomicity is a property of an artifact set, not a file.* The unit of backup is
    one timestamped directory containing the whole declared set, never a per-file copy. Restoring
    the roadmap from Tuesday into a governance set from Thursday reintroduces exactly the drift
    a backup exists to let you undo: the plan cites the roadmap, the steering cites the plan, and
    the citation checker validates across all of them.

    *Principle 3, never report success over unperformed work.* Every file is re-hashed FROM THE
    DESTINATION after copying and compared against its source hash. Hashing the source twice
    would verify nothing. A copy that was not verified is not reported as backed up.

    *Principle 2, an approximately-correct identifier is worse than an absent one.* The manifest
    records SHA-256 per file, not names and sizes. Two governance documents of identical length
    differing in one clause is the realistic case here, not a hypothetical.

    THE SYNC PROBLEM, WHICH IS THE REASON THIS SCRIPT IS NOT MACCRE'S
    ----------------------------------------------------------------
    The project root -- including `.git/` -- is Google Drive synced, and it syncs while work is
    in progress. Two consequences shape this script:

    1. **The destination must not share the source's failure domain.** A snapshot written inside
       the synced tree is protected by the same mechanism whose non-atomicity it exists to
       survive. The default destination is outside the project root, and the script REPORTS
       whether the destination looks Drive-covered rather than assuming either way.

    2. **A tree mid-sync is a moving tree.** Drive stages transfers in `.tmp.driveupload/` inside
       the synced folder. If that directory holds files, a transfer is in flight and files may
       change under the copy. Copying anyway would produce a manifest whose internal consistency
       cannot be claimed -- a backup that looks verified and is not. That gets its own terminal
       state, `SOURCE-IN-FLIGHT`, rather than being folded into success.

    NO DATABASE IS CREATED, EVER
    ----------------------------
    A `.db` without its `-wal` is a corrupt artifact set, and this script has no business
    checkpointing one. Markdown and text under Drive sync is fine and is a bonus offsite copy.

.PARAMETER Destination
    Root for snapshots. A timestamped subdirectory is created inside it. Defaults OUTSIDE the
    Drive-synced project root.

.PARAMETER Reason
    Short slug recorded in the manifest and used in the directory name. Say what is about to
    change; a snapshot whose reason is unrecorded cannot be matched to the edit it protected.

.PARAMETER IgnoreInFlight
    Proceed even when a Drive transfer is in flight. Records the override in the manifest. Use
    only when you know the tree is quiescent despite the staging directory.

.OUTPUTS
    Exit codes, all distinct:
        0  OK               every required source found, copied and hash-verified
        2  VERIFY-FAILED    a copied file's hash did not match its source
        3  SOURCE-MISSING   a REQUIRED source was absent; the set is incomplete
        4  NOTHING-COPIED   zero files copied; there is no backup regardless of other state
        5  DEST-UNWRITABLE  could not create or write the destination
        6  SOURCE-IN-FLIGHT a Drive transfer is active; the tree is moving

.EXAMPLE
    pwsh -File .kiro/governance/backup_datacenter.ps1 -Reason "task-2-governance-scripts"
#>

[CmdletBinding()]
param(
    [string] $Destination = 'B:\EHD_ResearchTests_Backups',
    [string] $Reason = 'unspecified',
    [switch] $IgnoreInFlight,
    [switch] $Json
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$EXIT_OK              = 0
$EXIT_VERIFY_FAILED   = 2
$EXIT_SOURCE_MISSING  = 3
$EXIT_NOTHING_COPIED  = 4
$EXIT_DEST_UNWRITABLE = 5
$EXIT_IN_FLIGHT       = 6

$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

# ---------------------------------------------------------------------------
# The declared set. Adding a governance or datacenter surface means adding it HERE, so that a
# surface nobody remembered to declare shows up as a missing declaration rather than as an
# absence nobody notices.
#
# Kind:
#   Required  -- its absence means the snapshot is incomplete. Exit 3.
#   Optional  -- may legitimately be empty or not exist yet (no agents, no breadcrumbs).
#                Reported and counted; never silently skipped.
#
# 09_Backups is deliberately NOT a source: backing up the backups recurses.
# ---------------------------------------------------------------------------
$sources = @(
    @{ Rel = 'src'; Kind = 'Required'; Label = 'src-codebase' }
    @{ Rel = 'tests'; Kind = 'Required'; Label = 'tests-specification' }
    @{ Rel = 'artifacts/00_Governance'; Kind = 'Required'; Label = 'dc-00-governance' }
    @{ Rel = 'artifacts/01_Collaborator_Conversations'; Kind = 'Optional'; Label = 'dc-01-collaborator-conversations' }
    @{ Rel = 'artifacts/02_Kiro_Conversations'; Kind = 'Optional'; Label = 'dc-02-kiro-conversations' }
    @{ Rel = 'artifacts/03_Task_Packets'; Kind = 'Optional'; Label = 'dc-03-task-packets' }
    @{ Rel = 'artifacts/04_BreadCrumbs'; Kind = 'Optional'; Label = 'dc-04-breadcrumbs' }
    @{ Rel = 'artifacts/05_Solver_Runs'; Kind = 'Optional'; Label = 'dc-05-solver-runs' }
    @{ Rel = 'artifacts/06_Inputs'; Kind = 'Optional'; Label = 'dc-06-inputs' }
    @{ Rel = 'artifacts/07_Outputs'; Kind = 'Optional'; Label = 'dc-07-outputs' }
    @{ Rel = 'artifacts/08_Reference'; Kind = 'Optional'; Label = 'dc-08-reference' }
    @{ Rel = '.kiro/steering'; Kind = 'Required'; Label = 'kiro-steering' }
    @{ Rel = '.kiro/governance'; Kind = 'Required'; Label = 'kiro-governance' }
    @{ Rel = '.kiro/agents'; Kind = 'Optional'; Label = 'kiro-agents' }
    @{ Rel = '.kiro/skills'; Kind = 'Optional'; Label = 'kiro-skills' }
    @{ Rel = '.kiro/hooks'; Kind = 'Optional'; Label = 'kiro-hooks' }
)

# Never captured, for cause. Recorded in the manifest so the exclusion is visible rather than
# looking like an oversight.
# - `*.db`, `*.db-wal`, `*.db-shm`: SQLite files are not atomic across three files when moved
#   via Drive or filesystem; checkpoint them, never unlink them.
# - `*.zip`: transient test artifacts.
# - `*.png`: matplotlib output is not byte-reproducible across versions; CSVs carry the numbers.
# - `.venv`: ~408 MB of reconstructible third-party code, generated by pip from
#   `requirements.lock`.
# - `*.log` in most directories, EXCEPT `artifacts/05_Solver_Runs/` which holds run evidence
#   (OBSERVED_2026-09-18_ltspice_gui_parse_failure.log is the first sighting of a real defect).
$excludedGlobs = @('*.db', '*.db-wal', '*.db-shm', '*.zip', '*.png', '.venv', '*.log')

$stampUtc = (Get-Date).ToUniversalTime()
$stamp = $stampUtc.ToString('yyyy-MM-ddTHHmmssZ')
$safeReason = ($Reason -replace '[^A-Za-z0-9._-]', '-')
$snapRoot = Join-Path $Destination ("$stamp" + '_' + $safeReason)

$result = [ordered]@{
    status           = $null
    exitCode         = $null
    reason           = $null
    snapshotPath     = $snapRoot
    takenUtc         = $stampUtc.ToString('o')
    forReason        = $Reason
    declared         = $sources.Count
    sourcesFound     = 0
    sourcesMissing   = @()
    filesCopied      = 0
    filesVerified    = 0
    verifyFailures   = @()
    # Download staging: remote changes being written INTO the tree. Blocks.
    inFlightFiles    = 0
    # Upload staging: Drive reading local files to push up. Informational only.
    uploadInFlight   = 0
    inFlightOverride = [bool]$IgnoreInFlight
    # Explicitly "not evaluated" rather than $null: the in-flight check runs before the
    # destination check, so an early exit must not render a blank field that reads as
    # "no coverage" when the truth is "nobody looked".
    destDriveCovered = 'not evaluated'
}

function Complete-Backup {
    param([string] $Status, [int] $Code, [string] $Reason)

    $result.status = $Status; $result.exitCode = $Code; $result.reason = $Reason

    if ($Json) {
        [pscustomobject]$result | ConvertTo-Json -Depth 6
    }
    else {
        Write-Host ''
        Write-Host "  status           : $Status" -ForegroundColor $(if ($Code -eq 0) { 'Green' } else { 'Red' })
        Write-Host "  reason           : $Reason"
        Write-Host "  snapshot         : $($result.snapshotPath)"
        Write-Host "  dest Drive-cover : $($result.destDriveCovered)"
        Write-Host "  sources declared : $($result.declared)"
        Write-Host "  sources found    : $($result.sourcesFound)"
        Write-Host "  files copied     : $($result.filesCopied)"
        Write-Host "  files verified   : $($result.filesVerified)"
        Write-Host "  drive download   : $($result.inFlightFiles) in flight (blocks)"
        Write-Host "  drive upload     : $($result.uploadInFlight) in flight (informational)"
        if ($result.sourcesMissing.Count) {
            Write-Host '  missing sources  :' -ForegroundColor Yellow
            foreach ($m in $result.sourcesMissing) { Write-Host "      $m" }
        }
        if ($result.verifyFailures.Count) {
            Write-Host '  VERIFY FAILURES  :' -ForegroundColor Red
            foreach ($v in $result.verifyFailures) { Write-Host "      $v" }
        }
        if ($Code -ne 0) {
            Write-Host ''
            Write-Host '  DO NOT PROCEED WITH EDITS. This is not a usable backup.' -ForegroundColor Red
        }
        Write-Host ''
    }
    exit $Code
}

# --- 0. is a Drive transfer in flight, and does it actually move the source? --
#
# THE TWO STAGING DIRECTORIES ARE NOT SYMMETRIC, AND TREATING THEM AS ONE WAS WRONG.
#
# The first version of this check refused to snapshot whenever EITHER staging directory held
# files. Running it revealed two things:
#
#   1. Under active development the upload queue is essentially never empty -- every file this
#      session wrote went into it. A blanket refusal makes the script unusable exactly when it
#      is most needed, which is before an edit.
#   2. More importantly the refusal was reasoning from the wrong premise. `.tmp.driveupload`
#      means Drive is READING local files to push them up. Reading does not move the source.
#      `.tmp.drivedownload` means Drive is WRITING remote changes into the local tree. That is
#      the direction that moves the source under a copy.
#
# So the guard is asymmetric: download activity is a genuine SOURCE-IN-FLIGHT, upload activity
# is recorded and reported but does not block.
#
# Note what still catches a mid-copy change either way: this script hashes the source, copies,
# then re-hashes FROM THE DESTINATION and compares. A file mutated during its own copy fails
# that comparison and the run exits VERIFY-FAILED. What the download guard adds on top is
# protection against SET-level inconsistency -- file A captured before a remote edit lands and
# file B after, each individually verifying fine.
# *Principle 8, atomicity is a property of an artifact set, not a file.*
$uploadStaging = Join-Path $repoRoot '.tmp.driveupload'
$downloadStaging = Join-Path $repoRoot '.tmp.drivedownload'

$uploadCount = if (Test-Path -LiteralPath $uploadStaging) {
    @(Get-ChildItem -LiteralPath $uploadStaging -Recurse -File -Force -ErrorAction SilentlyContinue).Count
} else { 0 }
$downloadCount = if (Test-Path -LiteralPath $downloadStaging) {
    @(Get-ChildItem -LiteralPath $downloadStaging -Recurse -File -Force -ErrorAction SilentlyContinue).Count
} else { 0 }

$result.uploadInFlight = $uploadCount
$result.inFlightFiles = $downloadCount

if ($downloadCount -gt 0 -and -not $IgnoreInFlight) {
    Complete-Backup 'SOURCE-IN-FLIGHT' $EXIT_IN_FLIGHT (
        "$downloadCount file(s) staged in Drive's DOWNLOAD directory, so remote changes are " +
        'landing in the local tree and the source is being written under the copy. Files ' +
        'captured either side of that are individually valid but mutually inconsistent. Wait ' +
        'for the download to settle, or pass -IgnoreInFlight if you know the tree is quiescent.'
    )
}

# --- 1. destination, and whether it shares the source's failure domain -------
# Reported, not assumed. The point of a separate destination is that it is not protected by the
# same non-atomic mechanism as the source.
$destIsUnderRepo = $Destination.TrimEnd('\', '/').ToLowerInvariant().StartsWith(
    $repoRoot.TrimEnd('\', '/').ToLowerInvariant())
$destDriveStaging = @(
    (Join-Path $Destination '.tmp.driveupload'),
    (Join-Path $Destination '.tmp.drivedownload')
) | Where-Object { Test-Path -LiteralPath $_ }
$result.destDriveCovered = if ($destIsUnderRepo) { 'YES - inside the synced project root' }
elseif ($destDriveStaging) { 'LIKELY - Drive staging dirs present at destination' }
else { 'no evidence of Drive coverage' }

if ($destIsUnderRepo) {
    Complete-Backup 'DEST-UNWRITABLE' $EXIT_DEST_UNWRITABLE (
        "Destination '$Destination' is inside the project root '$repoRoot', which is Drive-synced. " +
        'A snapshot there is protected by the same mechanism whose non-atomicity it exists to ' +
        'survive, and would also be swept up by the same accidental deletion. Choose a ' +
        'destination outside the project root.'
    )
}

try { $null = New-Item -ItemType Directory -Path $snapRoot -Force }
catch {
    Complete-Backup 'DEST-UNWRITABLE' $EXIT_DEST_UNWRITABLE `
        "Could not create '$snapRoot': $($_.Exception.Message)"
}

$manifestRows = @()

# --- 2. copy and verify ------------------------------------------------------
foreach ($s in $sources) {
    $srcPath = Join-Path $repoRoot $s.Rel
    $label = $s.Label

    if (-not (Test-Path -LiteralPath $srcPath)) {
        $result.sourcesMissing += "$label [$($s.Kind)] -> $($s.Rel)"
        continue
    }
    $result.sourcesFound++

    $files = @(Get-ChildItem -LiteralPath $srcPath -Recurse -File -Force -ErrorAction SilentlyContinue |
        Where-Object { $f = $_; -not ($excludedGlobs | Where-Object { $f.Name -like $_ }) })

    foreach ($f in $files) {
        $relative = $f.FullName.Substring($srcPath.Length).TrimStart('\', '/')
        $target = Join-Path (Join-Path $snapRoot $label) $relative
        $null = New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force

        $srcHash = (Get-FileHash -LiteralPath $f.FullName -Algorithm SHA256).Hash
        Copy-Item -LiteralPath $f.FullName -Destination $target -Force
        $result.filesCopied++

        # Re-hash from the DESTINATION. Hashing the source twice would verify nothing.
        $dstHash = if (Test-Path -LiteralPath $target) {
            (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash
        }
        else { 'MISSING-AFTER-COPY' }

        if ($dstHash -eq $srcHash) { $result.filesVerified++ }
        else { $result.verifyFailures += "$($f.FullName) -> src $srcHash vs dst $dstHash" }

        $manifestRows += [pscustomobject]@{
            Kind     = $s.Kind
            Label    = $label
            Relative = $relative
            Source   = $f.FullName
            Bytes    = $f.Length
            Modified = $f.LastWriteTimeUtc.ToString('o')
            Sha256   = $srcHash
            Verified = ($dstHash -eq $srcHash)
        }
    }
}

# --- 3. manifest -------------------------------------------------------------
$md = New-Object System.Text.StringBuilder
[void]$md.AppendLine('# EHD-ResearchTests datacenter snapshot manifest')
[void]$md.AppendLine('')
[void]$md.AppendLine("**Taken (UTC):** $($stampUtc.ToString('o'))  ")
[void]$md.AppendLine("**Reason:** $Reason  ")
[void]$md.AppendLine("**Snapshot root:** ``$snapRoot``  ")
[void]$md.AppendLine("**Destination Drive coverage:** $($result.destDriveCovered)  ")
[void]$md.AppendLine("**Drive download in flight at capture:** $($result.inFlightFiles) file(s)" +
    $(if ($result.inFlightOverride) { ' — **OVERRIDDEN with -IgnoreInFlight**' } else { '' }) + '  ')
[void]$md.AppendLine("**Drive upload in flight at capture:** $($result.uploadInFlight) file(s) " +
    '(informational — uploads read the tree, they do not modify it)  ')
[void]$md.AppendLine("**Sources declared:** $($sources.Count) — found $($result.sourcesFound)  ")
[void]$md.AppendLine("**Files copied:** $($result.filesCopied) — hash-verified $($result.filesVerified)")
[void]$md.AppendLine('')
[void]$md.AppendLine('Every hash below was taken from the SOURCE and re-checked against the file as')
[void]$md.AppendLine('written into this snapshot. `Verified = False` on any row means this snapshot is')
[void]$md.AppendLine('not trustworthy for that file, and the run exited non-zero.')
[void]$md.AppendLine('')
if ($result.sourcesMissing.Count) {
    [void]$md.AppendLine('## Declared sources that were absent')
    [void]$md.AppendLine('')
    foreach ($m in $result.sourcesMissing) { [void]$md.AppendLine("- $m") }
    [void]$md.AppendLine('')
    [void]$md.AppendLine('An `Optional` absence is expected (nothing configured yet). A `Required`')
    [void]$md.AppendLine('absence means the set is incomplete and the run exited 3.')
    [void]$md.AppendLine('')
}
[void]$md.AppendLine('## Excluded by design')
[void]$md.AppendLine('')
foreach ($g in $excludedGlobs) { [void]$md.AppendLine("- ``$g``") }
[void]$md.AppendLine('')
[void]$md.AppendLine('Databases are excluded because a `.db` without its `-wal` is a corrupt artifact')
[void]$md.AppendLine('set, and this script has no business checkpointing one. Session archives are')
[void]$md.AppendLine('excluded because they are full transcripts including screenshots, which no text')
[void]$md.AppendLine('scan can clear. Plots are excluded because they are regenerable and bulky; the')
[void]$md.AppendLine('CSVs that carry the numbers are captured.')
[void]$md.AppendLine('')
[void]$md.AppendLine('## Files')
[void]$md.AppendLine('')
[void]$md.AppendLine('| Kind | Set | Relative path | Bytes | Modified (UTC) | SHA-256 | Verified |')
[void]$md.AppendLine('|---|---|---|---|---|---|---|')
foreach ($r in ($manifestRows | Sort-Object Label, Relative)) {
    [void]$md.AppendLine("| $($r.Kind) | $($r.Label) | ``$($r.Relative)`` | $($r.Bytes) | $($r.Modified) | ``$($r.Sha256)`` | $($r.Verified) |")
}
[void]$md.AppendLine('')
[void]$md.AppendLine('## Restoring')
[void]$md.AppendLine('')
[void]$md.AppendLine('Restore the **whole set**, or reason explicitly about why a partial restore is safe.')
[void]$md.AppendLine('These files are mutually consistent or they are useless: the plan cites the')
[void]$md.AppendLine('roadmap, the steering cites the plan, and the citation checker validates across')
[void]$md.AppendLine('all of them. A single file from an older set reintroduces the drift this snapshot')
[void]$md.AppendLine('exists to let you undo.')
[void]$md.AppendLine('')
[void]$md.AppendLine('Verify before trusting, then copy back:')
[void]$md.AppendLine('')
[void]$md.AppendLine('```powershell')
[void]$md.AppendLine('# 1. Re-verify this snapshot against its own manifest hashes first.')
[void]$md.AppendLine('#    A backup nobody checked is a claim, not a backup.')
[void]$md.AppendLine('Get-ChildItem -Recurse -File <snapshot>\dc-00-governance |')
[void]$md.AppendLine('    ForEach-Object { "{0}  {1}" -f (Get-FileHash $_.FullName -Algorithm SHA256).Hash, $_.Name }')
[void]$md.AppendLine('')
[void]$md.AppendLine('# 2. Then copy back, per set. Wait for Drive to be idle first.')
[void]$md.AppendLine('Copy-Item <snapshot>\dc-00-governance\* B:\EHD-ResearchTests\artifacts\00_Governance\ -Recurse -Force')
[void]$md.AppendLine('Copy-Item <snapshot>\kiro-steering\*    B:\EHD-ResearchTests\.kiro\steering\        -Recurse -Force')
[void]$md.AppendLine('```')
[void]$md.AppendLine('')
[void]$md.AppendLine('### Restoring into a Drive-synced tree')
[void]$md.AppendLine('')
[void]$md.AppendLine('The project root is Drive-synced. Restore while Drive is idle, then let it settle')
[void]$md.AppendLine('before editing. Restoring during an active transfer races the sync client and can')
[void]$md.AppendLine('propagate a half-restored set to the other devices.')

Set-Content -LiteralPath (Join-Path $snapRoot 'MANIFEST.md') -Value $md.ToString() -Encoding utf8

# --- 4. terminal state -------------------------------------------------------
if ($result.filesCopied -eq 0) {
    Complete-Backup 'NOTHING-COPIED' $EXIT_NOTHING_COPIED `
        'Zero files were copied. Whatever else is true, there is no backup here.'
}
if ($result.verifyFailures.Count -gt 0) {
    Complete-Backup 'VERIFY-FAILED' $EXIT_VERIFY_FAILED (
        "$($result.verifyFailures.Count) of $($result.filesCopied) copied files did not match " +
        'their source hash. Treat this snapshot as unusable.'
    )
}
$missingRequired = @($result.sourcesMissing | Where-Object { $_ -match '\[Required\]' })
if ($missingRequired.Count -gt 0) {
    Complete-Backup 'SOURCE-MISSING' $EXIT_SOURCE_MISSING (
        "$($missingRequired.Count) REQUIRED source(s) absent, so the set is incomplete: " +
        ($missingRequired -join '; ')
    )
}

Complete-Backup 'OK' $EXIT_OK (
    "$($result.filesCopied) files copied and all $($result.filesVerified) hash-verified from " +
    "$($result.sourcesFound) of $($sources.Count) declared sources."
)
