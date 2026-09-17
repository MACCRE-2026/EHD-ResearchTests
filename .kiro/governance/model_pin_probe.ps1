#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Compares every `model:` pin in this workspace's agent profiles against the models Kiro CLI
    actually reports, and refuses to say "no drift" unless it counted something.

.DESCRIPTION
    THE FAILURE THIS EXISTS TO PREVENT
    ----------------------------------
    A `model:` pin that does not match a real model ID does not error. Kiro falls back to the
    default model and emits a warning. So a seat the operator believes costs 0.05x silently
    bills at 1x, and the only evidence is a warning nobody read. With this project's seats
    spanning 0.05x to 2.2x, that is up to a 44x cost error per call.

    Display names are not IDs. This is not hypothetical here: the model wanted for the cheap
    executor seat was referred to in conversation as "Qwen3 Code Next", the picker shows
    "Qwen3 Coder Next", and the callable identifier is `qwen3-coder-next`. Neither prose form
    would have resolved, and both would have silently fallen back to `auto` at 1.0x -- a 20x
    error. The enumeration is the only authority.

    WHY THIS IS NOT MACCRE'S COPY
    -----------------------------
    Two reasons. The Iron Rule means this project does not edit MACCRE's script to widen its
    scan path. And MACCRE's version resolves the CLI with `Get-Command` alone, which produced a
    confident FALSE NEGATIVE on this machine:

        Kiro CLI 2.21.4 was installed and working. `Get-Command kiro-cli` found nothing, because
        the installer had written to the USER `Path` and the agent's shell had inherited its
        environment BEFORE that write. Separately, `Test-Path 'C:\Program Files\Kiro-Cli'` was
        also false -- correctly, because the installer's own success message names a directory
        it never checked and the real install landed in
        %LOCALAPPDATA%\Kiro-Cli. Two checks, each correct in isolation, jointly reported a
        working tool as absent.

    A probe that reports a present tool missing is a scoped check masquerading as a finding, and
    it is worse than no probe: it justifies writing profiles unpinned when pinning was available.
    *Principle 2, an approximately-correct identifier is worse than an absent one.*

    So resolution here tries, in order: an explicit -CliPath, the process PATH, the Machine and
    User registry PATH scopes, and the known default install locations. Only when every route
    misses is absence concluded -- and "not on the process path, other routes unchecked" is a
    DIFFERENT terminal state from "searched everywhere, genuinely absent".

    *Principle 3, never report success over unperformed work.* Six distinct non-success terminal
    states, none folded into either "no drift" or a generic failure. Only a non-zero model count
    compared against at least one pin can return OK.

    WHY IT REPORTS RATHER THAN REPAIRS
    ----------------------------------
    Writes to .kiro/agents/** prompt for approval by design, so a probe cannot silently rewrite
    a profile. That is the correct shape: this reports drift, a human decides. Do not add a -Fix
    switch.

.PARAMETER AgentRoot
    Directory of agent profiles to scan. Defaults to .kiro/agents relative to the repo root.

.PARAMETER CliPath
    Explicit path to kiro-cli.exe. Bypasses all discovery. Use when the shell environment is
    known stale.

.OUTPUTS
    Exit codes, all distinct and all meaningful:
        0  OK              every pin resolved against a non-empty model list
        2  DRIFT           one or more pins did not resolve
        3  TOOL-ABSENT     every resolution route was tried and found nothing
        4  LIST-UNUSABLE   model list empty, unparsable, or zero-length
        5  NO-PINS         profiles were read but none pin a model; nothing to compare
        6  NO-PROFILES     agent directory absent or contains no profiles
        7  TOOL-UNRESOLVED not on the process PATH and the fallback routes were inconclusive

.EXAMPLE
    pwsh -File .kiro/governance/model_pin_probe.ps1
    pwsh -File .kiro/governance/model_pin_probe.ps1 -CliPath "$env:LOCALAPPDATA\Kiro-Cli\kiro-cli.exe"
#>

[CmdletBinding()]
param(
    [string] $AgentRoot,
    [string] $CliPath,
    [switch] $Json
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$EXIT_OK             = 0
$EXIT_DRIFT          = 2
$EXIT_TOOL_ABSENT    = 3
$EXIT_LIST_UNUSABLE  = 4
$EXIT_NO_PINS        = 5
$EXIT_NO_PROFILES    = 6
$EXIT_TOOL_UNRESOLVED = 7

$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

$result = [ordered]@{
    status         = $null
    exitCode       = $null
    reason         = $null
    cliPath        = $null
    cliResolvedVia = $null
    routesTried    = @()
    modelCount     = 0
    modelIds       = @()
    profilesFound  = 0
    pinsFound      = 0
    pins           = @()
    drifted        = @()
    probeRunUtc    = (Get-Date).ToUniversalTime().ToString('o')
}

function Complete-Probe {
    param([string] $Status, [int] $Code, [string] $Reason)

    $result.status = $Status; $result.exitCode = $Code; $result.reason = $Reason

    if ($Json) {
        [pscustomobject]$result | ConvertTo-Json -Depth 6
    }
    else {
        Write-Host ''
        Write-Host "  status        : $Status" -ForegroundColor $(if ($Code -eq 0) { 'Green' } else { 'Red' })
        Write-Host "  reason        : $Reason"
        Write-Host "  cli path      : $($result.cliPath)"
        Write-Host "  resolved via  : $($result.cliResolvedVia)"
        Write-Host "  models listed : $($result.modelCount)"
        Write-Host "  profiles read : $($result.profilesFound)"
        Write-Host "  pins found    : $($result.pinsFound)"
        if ($result.pinsFound -gt 0) {
            foreach ($p in $result.pins) {
                $mark = if ($result.drifted -contains $p.pin) { 'DRIFT ' } else { 'ok    ' }
                Write-Host ("  $mark        : {0}  <- {1}" -f $p.pin, $p.profile)
            }
        }
        if ($Code -ne 0) {
            Write-Host ''
            Write-Host '  This is NOT a clean result. Nothing above should be read as "no drift".' -ForegroundColor Yellow
        }
        Write-Host ''
    }
    exit $Code
}

# --- 0. locate the agent profiles -------------------------------------------
if (-not $AgentRoot) { $AgentRoot = Join-Path $repoRoot '.kiro/agents' }

$profiles = @()
if (Test-Path -LiteralPath $AgentRoot) {
    $profiles = @(Get-ChildItem -LiteralPath $AgentRoot -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Extension -in @('.md', '.json') })
}
$result.profilesFound = $profiles.Count

if ($profiles.Count -eq 0) {
    Complete-Probe 'NO-PROFILES' $EXIT_NO_PROFILES (
        "No agent profiles found under '$AgentRoot'. Nothing to check; this is not a pass."
    )
}

# --- 1. harvest the pins -----------------------------------------------------
foreach ($f in $profiles) {
    $text = Get-Content -LiteralPath $f.FullName -Raw
    foreach ($m in [regex]::Matches($text, '(?m)^\s*(?:model|"model")\s*:\s*"?([^"\r\n#]+?)"?\s*,?\s*$')) {
        $pin = $m.Groups[1].Value.Trim()
        if ($pin) { $result.pins += [pscustomobject]@{ pin = $pin; profile = $f.Name } }
    }
}
$result.pinsFound = $result.pins.Count

# --- 2. resolve the CLI, through every route, in order -----------------------
# Deliberately NOT `Get-Command` alone. See the docstring: that alone produced a confident
# false negative on a machine where the tool was installed and working.
$cli = $null

function Test-Candidate {
    param([string] $Path, [string] $Via)
    if ([string]::IsNullOrWhiteSpace($Path)) { return $null }
    $script:result.routesTried += "$Via -> $Path"
    if (Test-Path -LiteralPath $Path -PathType Leaf) {
        $script:result.cliResolvedVia = $Via
        return $Path
    }
    return $null
}

# Route 1: explicit parameter. Highest authority; if given and wrong, say so rather than
# silently falling through to a different binary than the operator named.
if ($CliPath) {
    $cli = Test-Candidate -Path $CliPath -Via 'explicit -CliPath'
    if (-not $cli) {
        Complete-Probe 'TOOL-ABSENT' $EXIT_TOOL_ABSENT (
            "-CliPath '$CliPath' does not exist. Not falling back to discovery: an explicit " +
            'path that is wrong is a different problem from one that was never given.'
        )
    }
}

# Route 2: the process PATH.
if (-not $cli) {
    $found = Get-Command 'kiro-cli' -ErrorAction SilentlyContinue
    if ($found) {
        $result.routesTried += "process PATH -> $($found.Source)"
        $result.cliResolvedVia = 'process PATH'
        $cli = $found.Source
    }
    else { $result.routesTried += 'process PATH -> not found' }
}

# Route 3: the registry PATH scopes. This is the route that fixes the stale-environment false
# negative -- the installer writes here, and a shell started earlier never sees it.
if (-not $cli) {
    foreach ($scope in @('Machine', 'User')) {
        $raw = [Environment]::GetEnvironmentVariable('Path', $scope)
        if (-not $raw) { continue }
        foreach ($dir in ($raw -split ';')) {
            if ([string]::IsNullOrWhiteSpace($dir)) { continue }
            $candidate = Join-Path $dir.Trim() 'kiro-cli.exe'
            $cli = Test-Candidate -Path $candidate -Via "registry PATH ($scope)"
            if ($cli) { break }
        }
        if ($cli) { break }
    }
}

# Route 4: known default install locations. The installer's own success message names
# "C:\Program Files\Kiro-Cli\" unconditionally without checking, and on this machine the real
# location was %LOCALAPPDATA%. Both are probed, and neither is trusted over the other.
if (-not $cli) {
    foreach ($known in @(
            (Join-Path $env:LOCALAPPDATA 'Kiro-Cli\kiro-cli.exe'),
            'C:\Program Files\Kiro-Cli\kiro-cli.exe',
            'C:\Program Files (x86)\Kiro-Cli\kiro-cli.exe'
        )) {
        $cli = Test-Candidate -Path $known -Via 'known install location'
        if ($cli) { break }
    }
}

if (-not $cli) {
    Complete-Probe 'TOOL-ABSENT' $EXIT_TOOL_ABSENT (
        'kiro-cli was not found by any resolution route (explicit path, process PATH, ' +
        "Machine/User registry PATH, known install locations). $($result.routesTried.Count) " +
        'route(s) tried, all negative, so NO model IDs were enumerated and NO pin was verified. ' +
        "Note that 'kiro' may resolve to the IDE launcher, which is not the CLI. Until this is " +
        'resolved, treat every pin as unverified.'
    )
}
$result.cliPath = $cli

if ($result.pinsFound -eq 0) {
    Complete-Probe 'NO-PINS' $EXIT_NO_PINS (
        "Read $($result.profilesFound) profile(s) and found no 'model:' pin in any of them. " +
        'Nothing to compare, so this is not a pass. Unpinned seats run on the default model.'
    )
}

# --- 3. enumerate the models -------------------------------------------------
$raw = $null
try {
    $stdout = Join-Path ([System.IO.Path]::GetTempPath()) "kc_models_$PID.json"
    $stderr = Join-Path ([System.IO.Path]::GetTempPath()) "kc_models_$PID.err"
    $proc = Start-Process -FilePath $cli `
        -ArgumentList 'chat', '--list-models', '--format', 'json' `
        -NoNewWindow -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    if (-not $proc.WaitForExit(120000)) {
        $proc.Kill()
        Complete-Probe 'LIST-UNUSABLE' $EXIT_LIST_UNUSABLE (
            'kiro-cli did not return a model list within 120s and was killed. A timeout is not ' +
            'an empty drift set.'
        )
    }
    $raw = if (Test-Path -LiteralPath $stdout) { Get-Content -LiteralPath $stdout -Raw } else { $null }
}
catch {
    Complete-Probe 'LIST-UNUSABLE' $EXIT_LIST_UNUSABLE `
        "kiro-cli was found at '$cli' but invoking --list-models threw: $($_.Exception.Message)"
}
finally {
    Remove-Item -LiteralPath $stdout, $stderr -Force -ErrorAction SilentlyContinue
}

if ([string]::IsNullOrWhiteSpace($raw)) {
    Complete-Probe 'LIST-UNUSABLE' $EXIT_LIST_UNUSABLE `
        'kiro-cli returned no output. An empty list is not an empty drift set.'
}

$parsed = $null
try { $parsed = $raw | ConvertFrom-Json }
catch {
    $head = $raw.Substring(0, [Math]::Min(300, $raw.Length))
    Complete-Probe 'LIST-UNUSABLE' $EXIT_LIST_UNUSABLE `
        "kiro-cli output did not parse as JSON. First 300 chars follow, verbatim:`n$head"
}

# A bare `[]` parses successfully and yields $null here. That is the single most important input
# this probe will ever see -- a CLI that is installed, authenticated and reporting nothing -- so
# it gets an explicit guard rather than falling through the shape detection below.
if ($null -eq $parsed) {
    Complete-Probe 'LIST-UNUSABLE' $EXIT_LIST_UNUSABLE (
        'kiro-cli returned valid JSON that parsed to nothing at all -- an empty array or null. ' +
        'The CLI is present and answered; it just named no models. That is a broken or ' +
        'unauthenticated CLI, not an empty drift set.'
    )
}

# The JSON shape is not published, so accept the plausible shapes rather than assuming one.
# Anything unrecognised is unusable, never silently empty.
$ids = @()
if ($parsed.PSObject.Properties.Name -contains 'models') {
    $ids = @($parsed.models | ForEach-Object {
            if ($_.PSObject.Properties.Name -contains 'model_id') { $_.model_id }
            elseif ($_.PSObject.Properties.Name -contains 'id') { $_.id }
            elseif ($_.PSObject.Properties.Name -contains 'model_name') { $_.model_name }
        })
}
elseif ($parsed -is [System.Array]) {
    $ids = @($parsed | ForEach-Object {
            if ($_ -is [string]) { $_ }
            elseif ($_.PSObject.Properties.Name -contains 'model_id') { $_.model_id }
            elseif ($_.PSObject.Properties.Name -contains 'id') { $_.id }
        })
}

$ids = @($ids | Where-Object { $_ } | Sort-Object -Unique)
$result.modelIds = $ids
$result.modelCount = $ids.Count

if ($result.modelCount -eq 0) {
    Complete-Probe 'LIST-UNUSABLE' $EXIT_LIST_UNUSABLE (
        'The model list parsed but yielded zero identifiers, so the JSON shape is not one this ' +
        'probe recognises. Zero models compared against any pin cannot be a pass.'
    )
}

# --- 4. compare --------------------------------------------------------------
foreach ($p in $result.pins) {
    if ($ids -notcontains $p.pin) { $result.drifted += $p.pin }
}
$result.drifted = @($result.drifted | Sort-Object -Unique)

if ($result.drifted.Count -gt 0) {
    Complete-Probe 'DRIFT' $EXIT_DRIFT (
        "$($result.drifted.Count) pin(s) did not resolve against $($result.modelCount) " +
        "enumerated model IDs: $($result.drifted -join ', '). A wrong pin does not error -- it " +
        'silently falls back to the default model and bills at that rate.'
    )
}

Complete-Probe 'OK' $EXIT_OK (
    "all $($result.pinsFound) pin(s) across $($result.profilesFound) profile(s) resolve against " +
    "$($result.modelCount) enumerated model IDs (CLI resolved via $($result.cliResolvedVia))."
)
