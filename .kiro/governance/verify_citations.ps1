#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Verifies that every doctrine principle citation in this workspace resolves to exactly one
    statement in the canonical doctrine, and that no document here restates the set.

.DESCRIPTION
    THE INCIDENT THIS ENCODES
    -------------------------
    On 2026-09-10 the MACCRE Systems coordination README carried a RESTATED set of six
    principles against the canonical eight, renumbered. The numbers COLLIDED: README 5 and 6
    were canonical 7 and 8, while canonical 5 and 6 were absent from it entirely. A citation of
    "principle 5" therefore resolved to two different statements depending only on which
    document the reader happened to open. Nobody noticed for weeks, because each document was
    internally consistent -- which is exactly why this has to be checked ACROSS documents
    rather than within one.

    The fix that incident produced was to cite by number AND NAME together. That pairing makes
    a stale citation self-evidently stale instead of silently wrong, and check 3 below is what
    enforces it.

    WHY THIS PROJECT NEEDS ITS OWN COPY
    -----------------------------------
    EHD-ResearchTests is not a MACCRE Systems project. The doctrine reaches it because it sits
    at user scope, and this project adopts it deliberately by citation. So this workspace
    accumulates citations that the MACCRE-side checker does not scan, and the Iron Rule means
    this project does not edit MACCRE's copy to widen its scope. Hence a local copy with a
    local ScanPath.

    WHAT IT CHECKS
    --------------
    1. The canonical set is well formed: exactly eight `## N. Name` headings, 1..8, no gaps, no
       duplicates. A malformed canon makes every other check meaningless, so this fails first
       and loudly rather than validating citations against a broken map.
    2. Every `principle N` / `doctrine N` citation names a number that exists in the canon.
    3. Where a citation carries a name alongside the number, the name matches the canonical
       name for that number. This is the check that would have caught the original drift,
       because both documents' numbers existed -- it was the pairing that was wrong.
    4. No document here RESTATES the set. A numbered list item whose text matches a canonical
       principle name is a second representation, and
       *principle 4, two representations of one thing will drift*, says what happens next.

.PARAMETER Canonical
    The authoritative doctrine file at user scope.

.PARAMETER ScanPath
    Files or directories to scan for citations. Defaults to this workspace's steering,
    governance, agents and skills directories plus the governance tier of the datacenter.

.OUTPUTS
    Exit codes, all distinct:
        0  OK                   every citation resolved; no restatements
        2  CITATION-UNRESOLVED  a cited number does not exist, or its name does not match
        3  CANONICAL-MALFORMED  the doctrine is not eight contiguous numbered principles
        4  NOTHING-SCANNED      no documents were read; there is no result to report
        5  RESTATEMENT-FOUND    a document restates principles instead of citing them

.EXAMPLE
    pwsh -File .kiro/governance/verify_citations.ps1
#>

[CmdletBinding()]
param(
    [string]   $Canonical = "$env:USERPROFILE\.kiro\steering\maccre-systems-doctrine.md",
    [string[]] $ScanPath,
    [switch]   $Json
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$EXIT_OK          = 0
$EXIT_UNRESOLVED  = 2
$EXIT_MALFORMED   = 3
$EXIT_NOTHING     = 4
$EXIT_RESTATEMENT = 5

$EXPECTED_COUNT = 8

# Resolve the repo root from this script's location: .kiro/governance/<script> -> repo root.
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

if (-not $ScanPath -or $ScanPath.Count -eq 0) {
    $ScanPath = @(
        (Join-Path $repoRoot '.kiro/steering')
        (Join-Path $repoRoot '.kiro/governance')
        (Join-Path $repoRoot '.kiro/agents')
        (Join-Path $repoRoot '.kiro/skills')
        (Join-Path $repoRoot 'artifacts/00_Governance')
        (Join-Path $repoRoot 'docs')
        (Join-Path $repoRoot 'README.md')
    )
}

$result = [ordered]@{
    status         = $null
    exitCode       = $null
    reason         = $null
    canonicalFile  = $Canonical
    canonicalCount = 0
    canonical      = @()
    filesScanned   = 0
    citationsFound = 0
    unresolved     = @()
    nameMismatches = @()
    restatements   = @()
    checkedUtc     = (Get-Date).ToUniversalTime().ToString('o')
}

function Complete-Check {
    param([string] $Status, [int] $Code, [string] $Reason)

    $result.status = $Status; $result.exitCode = $Code; $result.reason = $Reason

    if ($Json) {
        [pscustomobject]$result | ConvertTo-Json -Depth 6
    }
    else {
        Write-Host ''
        Write-Host "  status          : $Status" -ForegroundColor $(if ($Code -eq 0) { 'Green' } else { 'Red' })
        Write-Host "  reason          : $Reason"
        Write-Host "  canonical count : $($result.canonicalCount) (expected $EXPECTED_COUNT)"
        Write-Host "  files scanned   : $($result.filesScanned)"
        Write-Host "  citations found : $($result.citationsFound)"
        foreach ($group in @(
                @{ Name = 'UNRESOLVED CITATIONS'; Items = $result.unresolved },
                @{ Name = 'NAME MISMATCHES'; Items = $result.nameMismatches },
                @{ Name = 'RESTATEMENTS'; Items = $result.restatements }
            )) {
            if ($group.Items.Count) {
                Write-Host "  $($group.Name):" -ForegroundColor Red
                foreach ($i in $group.Items) { Write-Host "      $i" }
            }
        }
        if ($Code -ne 0) {
            Write-Host ''
            Write-Host '  Not a clean result. Do not report the doctrine as consistent.' -ForegroundColor Yellow
        }
        Write-Host ''
    }
    exit $Code
}

# --- 1. parse and validate the canon ---------------------------------------
if (-not (Test-Path -LiteralPath $Canonical)) {
    Complete-Check 'CANONICAL-MALFORMED' $EXIT_MALFORMED (
        "Canonical doctrine not found at '$Canonical'. Without the canon there is no map to " +
        'resolve citations against, so this is not a pass.'
    )
}

$canonText = Get-Content -LiteralPath $Canonical -Raw
$canonMap = @{}
foreach ($m in [regex]::Matches($canonText, '(?m)^##\s+(\d+)\.\s+(.+?)\s*$')) {
    $num = [int]$m.Groups[1].Value
    $name = $m.Groups[2].Value.Trim()
    if ($canonMap.ContainsKey($num)) {
        Complete-Check 'CANONICAL-MALFORMED' $EXIT_MALFORMED (
            "Principle $num is declared twice in the canon: '$($canonMap[$num])' and '$name'. " +
            'A duplicated number means a citation cannot resolve, which is the whole defect.'
        )
    }
    $canonMap[$num] = $name
}

$result.canonicalCount = $canonMap.Count
$result.canonical = @($canonMap.Keys | Sort-Object | ForEach-Object { "$_. $($canonMap[$_])" })

if ($canonMap.Count -ne $EXPECTED_COUNT) {
    Complete-Check 'CANONICAL-MALFORMED' $EXIT_MALFORMED (
        "Found $($canonMap.Count) numbered principles, expected $EXPECTED_COUNT. Either the " +
        'doctrine changed or this script is stale -- and it must be the doctrine that decides ' +
        'which, not this script silently accepting a new count. Principles are never ' +
        'renumbered and never deleted; a withdrawn one keeps its number.'
    )
}
for ($i = 1; $i -le $EXPECTED_COUNT; $i++) {
    if (-not $canonMap.ContainsKey($i)) {
        Complete-Check 'CANONICAL-MALFORMED' $EXIT_MALFORMED (
            "Principle numbering has a gap at $i. Contiguity matters: a gap is how a " +
            'renumbering starts.'
        )
    }
}

# --- 2. gather documents ----------------------------------------------------
$docs = @()
foreach ($p in $ScanPath) {
    if (-not (Test-Path -LiteralPath $p)) { continue }
    if (Test-Path -LiteralPath $p -PathType Container) {
        $docs += @(Get-ChildItem -LiteralPath $p -Recurse -File -Filter '*.md' -ErrorAction SilentlyContinue)
        $docs += @(Get-ChildItem -LiteralPath $p -Recurse -File -Filter '*.ps1' -ErrorAction SilentlyContinue)
    }
    else { $docs += @(Get-Item -LiteralPath $p) }
}

# The canon cites itself constantly and legitimately restates its own set.
$canonResolved = (Resolve-Path -LiteralPath $Canonical).Path
$docs = @($docs | Where-Object { $_.FullName -ne $canonResolved } | Sort-Object FullName -Unique)
$result.filesScanned = $docs.Count

if ($docs.Count -eq 0) {
    Complete-Check 'NOTHING-SCANNED' $EXIT_NOTHING (
        'Zero documents were scanned, so zero citations were checked. This is NOT a pass; it ' +
        'usually means a ScanPath is wrong.'
    )
}

# --- 3. check citations and restatements ------------------------------------
# Normalise for name comparison: lowercase, strip punctuation, collapse whitespace, so a name
# matches regardless of surrounding prose and emphasis markers.
function Get-Normalised {
    param([string] $Text)
    $t = $Text.ToLowerInvariant()
    $t = $t -replace '[^a-z0-9 ]', ' '
    $t = $t -replace '\s+', ' '
    return $t.Trim()
}

$canonNormalised = @{}
foreach ($k in $canonMap.Keys) { $canonNormalised[$k] = Get-Normalised $canonMap[$k] }

foreach ($d in $docs) {
    $lines = Get-Content -LiteralPath $d.FullName
    $rel = $d.FullName.Replace($repoRoot, '').TrimStart('\', '/')

    for ($ln = 0; $ln -lt $lines.Count; $ln++) {
        $line = $lines[$ln]

        # --- citations: "principle 3", "Doctrine 8", optionally followed by the name
        foreach ($c in [regex]::Matches($line, '(?i)\b(?:principles?|doctrine)\s+(\d+)\b(.{0,90})')) {
            $num = [int]$c.Groups[1].Value
            $tail = $c.Groups[2].Value
            $result.citationsFound++

            if (-not $canonMap.ContainsKey($num)) {
                $result.unresolved += "${rel}:$($ln + 1): cites principle $num, which does not exist in the canon"
                continue
            }

            # If a name accompanies the number, it must be the right name. This is the check
            # that catches drift while both numbers still exist.
            $tailNorm = Get-Normalised $tail
            if ($tailNorm.Length -ge 12) {
                $expected = $canonNormalised[$num]
                $matchesExpected = $tailNorm.StartsWith($expected.Substring(0, [Math]::Min(20, $expected.Length)))
                $looksLikeAnother = $false
                $otherNum = $null
                foreach ($k in $canonNormalised.Keys) {
                    if ($k -eq $num) { continue }
                    $other = $canonNormalised[$k]
                    if ($tailNorm.StartsWith($other.Substring(0, [Math]::Min(20, $other.Length)))) {
                        $looksLikeAnother = $true; $otherNum = $k; break
                    }
                }
                if ($looksLikeAnother -and -not $matchesExpected) {
                    $result.nameMismatches += (
                        "${rel}:$($ln + 1): cites principle $num but names principle $otherNum " +
                        "('$($canonMap[$otherNum])'). Canonical $num is '$($canonMap[$num])'."
                    )
                }
            }
        }

        # --- restatement: a numbered list item reproducing a canonical principle name
        $li = [regex]::Match($line, '^\s{0,3}(\d+)[.)]\s+\*{0,2}(.{10,120})')
        if ($li.Success) {
            $itemNum = [int]$li.Groups[1].Value
            $itemNorm = Get-Normalised $li.Groups[2].Value
            foreach ($k in $canonNormalised.Keys) {
                $cn = $canonNormalised[$k]
                $probe = $cn.Substring(0, [Math]::Min(28, $cn.Length))
                if ($itemNorm.StartsWith($probe)) {
                    $note = if ($itemNum -eq $k) {
                        "restates principle $k as list item $itemNum"
                    }
                    else {
                        "restates principle $k AS NUMBER $itemNum -- a renumbering, which is how the original collision happened"
                    }
                    $result.restatements += "${rel}:$($ln + 1): $note"
                    break
                }
            }
        }
    }
}

# --- 4. terminal state ------------------------------------------------------
if ($result.unresolved.Count -gt 0 -or $result.nameMismatches.Count -gt 0) {
    Complete-Check 'CITATION-UNRESOLVED' $EXIT_UNRESOLVED (
        "$($result.unresolved.Count) unresolved citation(s) and " +
        "$($result.nameMismatches.Count) number/name mismatch(es) across $($result.filesScanned) files."
    )
}
if ($result.restatements.Count -gt 0) {
    Complete-Check 'RESTATEMENT-FOUND' $EXIT_RESTATEMENT (
        "$($result.restatements.Count) restatement(s) of the canonical set found. Each is a " +
        'second representation and will drift. Replace with a citation by number and name.'
    )
}

Complete-Check 'OK' $EXIT_OK (
    "$($result.citationsFound) citation(s) across $($result.filesScanned) files all resolve " +
    "against $($result.canonicalCount) canonical principles, and no document restates the set."
)
