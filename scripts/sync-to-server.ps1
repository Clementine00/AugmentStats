<#
.SYNOPSIS
    Ships newly exported games to the AugmentStats server and ingests them there.

.DESCRIPTION
    The server owns the database. This script copies only the game files the
    server does not already have, then runs ingest over SSH and reports what
    landed. It never copies the database itself -- raw JSON is the transport, so
    the server's database is always rebuildable from the files it holds.

    Only scp is used, because rsync would have to exist on both ends and Windows
    has no rsync.

.PARAMETER Server
    SSH target, e.g. user@host. If omitted, falls back to the AUGMENTSTATS_SERVER
    environment variable, then to a `server.local` file in the repo root. That
    file is git-ignored so the address stays out of the public repository.

.PARAMETER RemotePath
    Where the checkout lives on the server. Defaults to /srv/augmentstats.

.PARAMETER SkipPull
    Skip updating the server's checkout. By default the server runs `git pull`
    first, so it never ingests with code older than main.

.PARAMETER LocalRaw
    Folder of exported games to ship. Defaults to data/raw next to this script.

.EXAMPLE
    .\sync-to-server.ps1
    Copies any games the server is missing and ingests them.
#>
[CmdletBinding()]
param(
    [string]$Server,
    [string]$RemotePath = "/srv/augmentstats",
    [string]$LocalRaw,
    [switch]$SkipPull
)

$ErrorActionPreference = "Stop"

# Resolved here rather than as param() defaults: under [CmdletBinding()], Windows
# PowerShell leaves $PSScriptRoot empty while evaluating defaults when the script
# is launched via `powershell -File`.
$repoRoot = Split-Path -Parent $PSScriptRoot
if (-not $LocalRaw) {
    $LocalRaw = Join-Path $repoRoot "data\raw"
}

if (-not $Server) { $Server = $env:AUGMENTSTATS_SERVER }
if (-not $Server) {
    $serverFile = Join-Path $repoRoot "server.local"
    if (Test-Path $serverFile) {
        $Server = (Get-Content $serverFile -Raw).Trim()
    }
}
if (-not $Server) {
    throw ("No server configured. Pass -Server user@host, set AUGMENTSTATS_SERVER, " +
           "or write the target into a 'server.local' file in the repo root.")
}

if (-not (Test-Path $LocalRaw)) {
    throw "No local game folder at '$LocalRaw'. Run scripts\export-games.ps1 first."
}

$localFiles = @(Get-ChildItem -Path $LocalRaw -Filter *.json -File)
if ($localFiles.Count -eq 0) {
    Write-Host "No exported games in $LocalRaw. Nothing to sync."
    return
}

Write-Host "Server:  $Server"
Write-Host "Remote:  $RemotePath"
Write-Host "Local:   $($localFiles.Count) exported game(s)"

# Bring the server's checkout up to date before it ingests anything. Nothing else
# deploys code to the server -- merging a PR does not touch it -- so without this
# it silently runs whatever commit was last pulled. The data directories are
# git-ignored, so a pull cannot disturb the database or the exported games.
if (-not $SkipPull) {
    Write-Host ""
    Write-Host "Updating server checkout..."
    $pullOutput = & ssh -o BatchMode=yes $Server "cd $RemotePath && git pull --ff-only 2>&1 && git log --oneline -1"
    if ($LASTEXITCODE -ne 0) {
        # A failed pull leaves the server on older-but-working code, so this is
        # not worth blocking the export on -- but it must be loud, since the
        # whole point is to stop silent drift.
        Write-Warning "Could not update the server checkout (exit code $LASTEXITCODE):"
        $pullOutput | ForEach-Object { Write-Warning "  $_" }
        Write-Warning "Continuing with the code already on the server."
    }
    else {
        Write-Host "  now at: $(@($pullOutput)[-1])"
    }
}

# Ask the server what it already has. `|| true` keeps a first-run empty folder
# from tripping the non-zero exit.
$remoteList = & ssh -o BatchMode=yes $Server "ls $RemotePath/data/raw/*.json 2>/dev/null | xargs -r -n1 basename || true"
$remoteNames = @($remoteList | Where-Object { $_ })
Write-Host "Server already has $($remoteNames.Count) game(s)."

$missing = @($localFiles | Where-Object { $remoteNames -notcontains $_.Name })
if ($missing.Count -eq 0) {
    Write-Host ""
    Write-Host "Server is already up to date. Nothing to copy."
    return
}

Write-Host ""
Write-Host "Copying $($missing.Count) new game(s)..."
& scp -q $missing.FullName "${Server}:$RemotePath/data/raw/"
if ($LASTEXITCODE -ne 0) {
    throw "scp failed with exit code $LASTEXITCODE -- nothing was ingested."
}

Write-Host "Ingesting on the server..."
# Ingest reports one line per file, including every game already present. Only the
# failures and the closing summary are worth surfacing here.
$ingestOutput = & ssh -o BatchMode=yes $Server "cd $RemotePath && python3 -m augmentstats ingest"
if ($LASTEXITCODE -ne 0) {
    $ingestOutput | ForEach-Object { Write-Host "  $_" }
    throw "Remote ingest failed with exit code $LASTEXITCODE."
}

$failures = @($ingestOutput | Where-Object { $_ -match "^failed" })
foreach ($line in $failures) {
    Write-Warning $line
}

$summary = @($ingestOutput | Where-Object { $_ -match "imported.*skipped.*failed" })[-1]
if ($summary) {
    Write-Host "  $summary"
}

$total = & ssh -o BatchMode=yes $Server "cd $RemotePath && sqlite3 augmentstats.db 'SELECT COUNT(*) FROM games;'"
Write-Host ""
Write-Host "Done. Server now holds $total game(s)."
