# Restart the whole local setup in one go (ASCII only on purpose: Windows PowerShell 5.1 reads BOM-less .ps1 as CP949).
#   1) make sure the DB container is running   2) stop old API (4001) / web (4000) processes
#   3) start the API (scripts\start_local_api.ps1) and the web (npx next dev -p 4000) in their own windows
#   4) wait until both answer, then open the browser
# Usage (project root):  powershell -ExecutionPolicy Bypass -File scripts\restart_local.ps1
# Options: -NoBrowser (do not open the browser)
param([switch]$NoBrowser)

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Stop-Port([int]$port) {
    $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    foreach ($c in $conns) {
        try { Stop-Process -Id $c.OwningProcess -Force -ErrorAction Stop; Write-Host "stopped old process on port $port (pid $($c.OwningProcess))" } catch { }
    }
}
function Wait-Url([string]$url, [int]$seconds) {
    $end = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $end) {
        try { $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 5; if ($r.StatusCode -lt 500) { return $true } } catch {
            if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -lt 500) { return $true }
        }
        Start-Sleep -Seconds 2
    }
    return $false
}

Write-Host "=== [1/4] DB container ===" -ForegroundColor Cyan
docker start stock-screener-pg | Out-Null
docker exec stock-screener-pg pg_isready
if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] DB is not ready. Start Docker Desktop and run this script again." -ForegroundColor Red; exit 1 }

Write-Host "=== [2/4] stop old processes ===" -ForegroundColor Cyan
Stop-Port 4001
Stop-Port 4000

Write-Host "=== [3/4] start API and web (two new windows) ===" -ForegroundColor Cyan
$apiCmd = "Set-Location '$repoRoot'; powershell -ExecutionPolicy Bypass -File scripts\start_local_api.ps1"
Start-Process powershell -ArgumentList @("-NoExit", "-Command", $apiCmd) | Out-Null
$webCmd = "Set-Location '$repoRoot\frontend'; npx next dev -p 4000"
Start-Process powershell -ArgumentList @("-NoExit", "-Command", $webCmd) | Out-Null

Write-Host "=== [4/4] wait until both answer ===" -ForegroundColor Cyan
$apiOk = Wait-Url "http://127.0.0.1:4001/api/v1/live" 120
if ($apiOk) { Write-Host "API (4001): OK" -ForegroundColor Green } else { Write-Host "[ERROR] API (4001) did not answer in 120s. Read the API window (last lines) for the reason." -ForegroundColor Red }
$webOk = Wait-Url "http://localhost:4000/login" 180
if ($webOk) { Write-Host "Web (4000): OK" -ForegroundColor Green } else { Write-Host "[ERROR] Web (4000) did not answer in 180s. Read the web window (last lines) for the reason." -ForegroundColor Red }
if ($apiOk -and $webOk -and -not $NoBrowser) { Start-Process "http://localhost:4000/screener/pattern" | Out-Null }
if (-not ($apiOk -and $webOk)) { exit 1 }
