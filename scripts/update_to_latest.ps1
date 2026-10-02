# One-shot "bring data up to date" helper for the local Windows PC (ASCII only on purpose:
# Windows PowerShell 5.1 reads BOM-less .ps1 files as CP949).
#
# Usage (project root, normal PowerShell):
#   powershell -ExecutionPolicy Bypass -File scripts\update_to_latest.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\update_to_latest.ps1 -Days 130 -SkipBackfill
#
# Steps: [0] check DB container  [1] backfill dry-run (no API calls, shows expected call count)
#        [2] backfill  [3] daily batch (catch-up of missed trading days)  [4] freshness check
# Reads .env (BATCH_DATABASE_URL, GOV_DATA_PORTAL_SERVICE_KEY, ...) into the process environment.
# The backfill script does NOT read .env by itself, this wrapper does it for every step.
# Log: logs\update_to_latest.log   (secrets are never printed by the called scripts)
param(
    [int]$Days = 130,
    [int]$MaxCalls = 400,
    [double]$Sleep = 0.3,
    [switch]$SkipBackfill,
    [switch]$Yes
)

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
$env:PYTHONUTF8 = "1"

$logDir = Join-Path $repoRoot "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$logFile = Join-Path $logDir "update_to_latest.log"

$envFile = Join-Path $repoRoot ".env"
if (-not (Test-Path $envFile)) {
    Write-Host "[ERROR] .env not found at $envFile" -ForegroundColor Red
    exit 1
}
Get-Content $envFile -Encoding utf8 | ForEach-Object {
    $line = $_.Trim()
    if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
        $key, $value = $line.Split("=", 2)
        [System.Environment]::SetEnvironmentVariable($key.Trim(), $value.Trim().Trim('"'))
    }
}
foreach ($name in @("BATCH_DATABASE_URL", "GOV_DATA_PORTAL_SERVICE_KEY")) {
    if (-not [System.Environment]::GetEnvironmentVariable($name)) {
        Write-Host "[ERROR] $name is not set in .env" -ForegroundColor Red
        exit 1
    }
}

function Run-Step([string]$title, [string]$cmdline) {
    Write-Host ""
    Write-Host "=== $title ===" -ForegroundColor Cyan
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    [System.IO.File]::AppendAllText($logFile, "===== $stamp $title =====`r`n")
    cmd /c "chcp 65001 >nul & $cmdline >>`"$logFile`" 2>&1"
    $code = $LASTEXITCODE
    Write-Host "exit code: $code   (details: logs\update_to_latest.log)"
    return $code
}

# [0] DB container
Write-Host "=== [0] check DB container ===" -ForegroundColor Cyan
docker start stock-screener-pg | Out-Null
docker exec stock-screener-pg pg_isready
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] database is not ready. Start Docker Desktop and retry." -ForegroundColor Red
    exit 1
}

if (-not $SkipBackfill) {
    # [1] dry-run: shows the plan and expected number of API calls, makes no API call
    $code = Run-Step "[1] backfill dry-run" "py -3.12 scripts\backfill_ohlcv.py --dry-run --days $Days"
    Write-Host ""
    Get-Content $logFile -Tail 12
    if (-not $Yes) {
        $answer = Read-Host "Expected calls shown above. Check your daily API quota. Continue with the real backfill? (y/N)"
        if ($answer -ne "y") { Write-Host "Stopped before backfill."; exit 0 }
    }
    # [2] backfill (idempotent, resumes where it stopped)
    $code = Run-Step "[2] backfill" "py -3.12 scripts\backfill_ohlcv.py --days $Days --sleep $Sleep --max-calls $MaxCalls"
    if ($code -ne 0) {
        Write-Host "[ERROR] backfill failed (exit $code). Fix the cause, then run this script again (it resumes)." -ForegroundColor Red
        exit $code
    }
}

# [3] daily batch (catch-up of missed trading days, then derive)
$code = Run-Step "[3] daily batch" "py -3.12 scripts\run_daily_batch.py"
if ($code -eq 2) {
    Write-Host "Latest trading day is not published yet (exit 2). This is normal; run again later." -ForegroundColor Yellow
} elseif ($code -ne 0) {
    Write-Host "[ERROR] daily batch failed (exit $code)." -ForegroundColor Red
    exit $code
}

# [4] freshness
$code = Run-Step "[4] freshness check" "py -3.12 scripts\check_data_freshness.py"
Get-Content $logFile -Tail 3
if ($code -eq 0) { Write-Host "DONE: data is up to date." -ForegroundColor Green } else { Write-Host "Data is still behind (exit $code). See logs\update_to_latest.log" -ForegroundColor Yellow }
exit $code
