<#
.SYNOPSIS
    Exports recent ARAM Mayhem games from the running League client into data/raw/
    for augmentstats to ingest.

.DESCRIPTION
    Auto-detects the League client's lockfile (port + password) from the running
    LeagueClientUx.exe process, asks the client for your recent match history,
    filters it down to the Mayhem queue, and downloads any game not already
    present in the output folder as raw JSON (via curl.exe -o, which writes the
    HTTP response bytes directly -- unlike `curl.exe ... > file.json`, this avoids
    PowerShell re-encoding the output as UTF-16).

.PARAMETER OutDir
    Folder to write <gameId>.json files into. Defaults to data/raw next to this
    script. Point this at wherever your augmentstats checkout's data/raw actually
    lives if this script isn't running from inside the repo.

.PARAMETER QueueId
    Riot queueId to filter match history down to. 2400 = ARAM Mayhem as observed
    in the sample game used to build this project; adjust if Riot changes it.

.PARAMETER Count
    How many of your most recent games to check (across all queues, before the
    QueueId filter is applied). The client hands back a single page of its most
    recent games and ignores paging arguments, so this trims that page rather
    than fetching more. How big that page is depends on the client's own cache
    (20 and 50 have both been observed); asking for more than it returns cannot
    reach further back and will warn.

.PARAMETER LockfilePath
    Skip auto-detection and point directly at a lockfile, e.g. if
    LeagueClientUx.exe isn't discoverable via Get-CimInstance for some reason.

.EXAMPLE
    .\export-games.ps1
    Downloads any new Mayhem games from your last 20 matches into ..\data\raw

.EXAMPLE
    .\export-games.ps1 -Count 50 -OutDir "D:\dev\AugmentStats\data\raw"
#>
[CmdletBinding()]
param(
    [string]$OutDir,
    [int]$QueueId = 2400,
    [int]$Count = 20,
    [string]$LockfilePath
)

$ErrorActionPreference = "Stop"

# Resolved here rather than as a param() default: under [CmdletBinding()], Windows
# PowerShell leaves $PSScriptRoot empty while evaluating param defaults when the
# script is launched via `powershell -File`, which made the default blow up in
# Join-Path. It is populated normally once the body runs.
if (-not $OutDir) {
    $OutDir = Join-Path $PSScriptRoot "..\data\raw"
}

function Find-Lockfile {
    param([string]$Explicit)

    if ($Explicit) {
        if (-not (Test-Path $Explicit)) {
            throw "No lockfile found at -LockfilePath '$Explicit'."
        }
        return $Explicit
    }

    $proc = Get-CimInstance Win32_Process -Filter "Name='LeagueClientUx.exe'" | Select-Object -First 1
    if (-not $proc) {
        throw "LeagueClientUx.exe isn't running. Start the League client and get to the client home screen, then re-run this script."
    }

    $installDir = Split-Path $proc.ExecutablePath
    $lockfile = Join-Path $installDir "lockfile"
    if (-not (Test-Path $lockfile)) {
        throw "LeagueClientUx.exe is running but no lockfile was found at '$lockfile'. Pass -LockfilePath explicitly."
    }
    return $lockfile
}

$lockfilePath = Find-Lockfile -Explicit $LockfilePath
Write-Host "Using lockfile: $lockfilePath"

# Lockfile format: processName:pid:port:password:protocol
$parts = (Get-Content $lockfilePath -Raw).Trim().Split(':')
if ($parts.Count -lt 5) {
    throw "Unexpected lockfile format in '$lockfilePath'."
}
$port = $parts[2]
$password = $parts[3]
$authHeader = "riot:$password"
$base = "https://127.0.0.1:$port"

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

# The LCU ignores begIndex/endIndex on this endpoint -- it accepts the arguments
# (unknown ones 400) but always returns the same newest page regardless of the
# values, so paging deeper is not possible and $Count is applied client-side below.
Write-Host "Fetching recent match history..."
$historyJson = curl.exe -sk -u $authHeader "$base/lol-match-history/v1/products/lol/current-summoner/matches"
$history = $historyJson | ConvertFrom-Json

if (-not $history.games -or -not $history.games.games) {
    Write-Host "Unexpected response from match history endpoint:"
    Write-Host $historyJson
    throw "Could not find games list in the response. The LCU endpoint or response shape may have changed."
}

$returnedGames = @($history.games.games)
if ($Count -gt $returnedGames.Count) {
    Write-Warning ("Asked to check $Count games but the client only returns its most recent " +
        "$($returnedGames.Count). Games older than that cannot be exported -- run this more often " +
        "so they do not fall off the end of the client's history.")
}

$allGames = @($returnedGames | Select-Object -First $Count)
$mayhemGames = @($allGames | Where-Object { $_.queueId -eq $QueueId })
Write-Host "Checked $($allGames.Count) recent game(s); $($mayhemGames.Count) with queueId $QueueId."

$imported = 0
$skipped = 0
foreach ($g in $mayhemGames) {
    $gameId = $g.gameId
    $outFile = Join-Path $OutDir "$gameId.json"
    if (Test-Path $outFile) {
        $skipped++
        continue
    }
    Write-Host "Downloading game $gameId..."
    curl.exe -sk -u $authHeader "$base/lol-match-history/v1/games/$gameId" -o $outFile
    $imported++
}

Write-Host ""
Write-Host "$imported new game(s) downloaded to $OutDir, $skipped already present."
Write-Host "Now run: python -m augmentstats ingest"
