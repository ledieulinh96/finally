# Start FinAlly in Docker (Windows PowerShell). Idempotent.
# Usage: .\scripts\start_windows.ps1 [-Build] [-NoOpen]
param(
    [switch]$Build,
    [switch]$NoOpen
)
$ErrorActionPreference = "Stop"

$Image = "finally"
$Container = "finally"
$Volume = "finally-data"
$Port = if ($env:FINALLY_PORT) { $env:FINALLY_PORT } else { "8000" }
$Url = "http://localhost:$Port"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Error "docker is not installed or not on PATH."; exit 1
}
docker info *> $null
if ($LASTEXITCODE -ne 0) { Write-Error "The Docker daemon is not running. Start Docker Desktop and retry."; exit 1 }

docker image inspect $Image *> $null
if ($Build -or $LASTEXITCODE -ne 0) {
    Write-Host "Building image '$Image'..."
    docker build -t $Image $Root
    if ($LASTEXITCODE -ne 0) { Write-Error "docker build failed"; exit 1 }
}

$running = (docker inspect -f '{{.State.Running}}' $Container 2>$null)
if ($running -eq "true" -and -not $Build) {
    Write-Host "FinAlly is already running at $Url"
    if (-not $NoOpen) { Start-Process $Url }
    exit 0
}

docker container inspect $Container *> $null
if ($LASTEXITCODE -eq 0) { docker rm -f $Container | Out-Null }

# Fail early and clearly if the host port is taken.
$holder = (docker ps --filter "publish=$Port" --format '{{.Names}}' 2>$null | Select-Object -First 1)
$listener = $null
try { $listener = Get-NetTCPConnection -LocalPort ([int]$Port) -State Listen -ErrorAction Stop | Select-Object -First 1 } catch { }
if ($holder -or $listener) {
    $who = if ($holder) { "container '$holder'" } else { "process id $($listener.OwningProcess)" }
    Write-Host "Error: host port $Port is already in use by $who." -ForegroundColor Red
    Write-Host "  Pick a free port, e.g.:  `$env:FINALLY_PORT=8012; .\scripts\start_windows.ps1"
    exit 1
}

$envArgs = @()
if (Test-Path (Join-Path $Root ".env")) {
    $envArgs = @("--env-file", (Join-Path $Root ".env"))
} else {
    Write-Warning ".env not found - starting without it (AI chat needs OPENROUTER_API_KEY; see .env.example)."
}

$runOut = docker run -d --name $Container -v "${Volume}:/app/db" -p "${Port}:8000" @envArgs $Image 2>&1
if ($LASTEXITCODE -ne 0) {
    docker rm -f $Container *> $null
    if ("$runOut" -match "port is already allocated|address already in use") {
        Write-Host "Error: host port $Port is already in use. Set `$env:FINALLY_PORT to a free port and retry." -ForegroundColor Red
    } else {
        Write-Host "Error: docker run failed: $runOut" -ForegroundColor Red
    }
    exit 1
}

Write-Host -NoNewline "Waiting for FinAlly to become healthy"
for ($i = 0; $i -lt 30; $i++) {
    try {
        $r = Invoke-WebRequest -Uri "$Url/api/health" -UseBasicParsing -TimeoutSec 2
        if ($r.StatusCode -eq 200) { break }
    } catch { }
    Write-Host -NoNewline "."
    Start-Sleep -Seconds 1
}
Write-Host ""
Write-Host "FinAlly is running at $Url"
Write-Host "Logs: docker logs -f $Container    Stop: .\scripts\stop_windows.ps1"
if (-not $NoOpen) { Start-Process $Url }
