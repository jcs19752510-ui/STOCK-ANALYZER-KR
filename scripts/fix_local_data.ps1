# One command: diagnose the local data lag, run the catch-up batch, make sure the scheduler exists, diagnose again.
# (ASCII only on purpose: Windows PowerShell 5.1 reads BOM-less .ps1 as CP949.)
#
# Usage (project root, normal PowerShell):
#   powershell -ExecutionPolicy Bypass -File scripts\fix_local_data.ps1
#
# What it does, in order:
#   1) DB container check (docker)         2) diagnosis BEFORE (scripts\diagnose_local_data.py, read-only)
#   3) catch-up batch (scripts\run_daily_batch.py: fills missed trading days, safe to repeat)
#   4) diagnosis AFTER                     5) scheduled task check -> register if missing
# Output is also appended to logs\fix_local_data.log. Secrets are never printed by the called scripts.
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$logDir = Join-Path $repoRoot "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$logFile = Join-Path $logDir "fix_local_data.log"

$envFile = Join-Path $repoRoot ".env"
if (-not (Test-Path $envFile)) { Write-Host "[ERROR] .env not found: $envFile" -ForegroundColor Red; exit 1 }
Get-Content $envFile -Encoding utf8 | ForEach-Object {
    $line = $_.Trim()
    if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
        $k, $v = $line.Split("=", 2)
        [System.Environment]::SetEnvironmentVariable($k.Trim(), $v.Trim().Trim('"'))
    }
}

# Runs a command, shows every line, appends it to the log, and returns ONLY the exit code.
function Step([string]$title, [string]$cmd) {
    Write-Host ""
    Write-Host "=== $title ===" -ForegroundColor Cyan
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    [System.IO.File]::AppendAllText($logFile, "===== $stamp $title =====`r`n")
    cmd /c "chcp 65001 >nul & $cmd 2>&1" | ForEach-Object {
        Write-Host $_
        [System.IO.File]::AppendAllText($logFile, "$_`r`n")
    }
    return [int]$LASTEXITCODE
}

Write-Host "=== [1/5] DB container ===" -ForegroundColor Cyan
docker start stock-screener-pg | Out-Null
docker exec stock-screener-pg pg_isready
if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] DB is not ready. Start Docker Desktop and run this script again." -ForegroundColor Red; exit 1 }

$beforeExit = Step "[2/5] diagnosis BEFORE" "py -3.12 scripts\diagnose_local_data.py"
$batchExit = Step "[3/5] catch-up batch (this can take several minutes)" "py -3.12 scripts\run_daily_batch.py"
Write-Host "batch exit code: $batchExit  (0 = ok / nothing to do, 2 = source has not published the day yet, other = failure: read the lines above)"
$afterExit = Step "[4/5] diagnosis AFTER" "py -3.12 scripts\diagnose_local_data.py"

Write-Host ""
Write-Host "=== [5/5] scheduled task ===" -ForegroundColor Cyan
$task = Get-ScheduledTask -TaskName "StockScreenerKR-DailyBatch" -ErrorAction SilentlyContinue
if ($null -eq $task) {
    Write-Host "Scheduled task is NOT registered. Registering now (14:30 and 18:30 every day) ..."
    powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "register_daily_batch_task.ps1")
} else {
    $info = Get-ScheduledTaskInfo -TaskName "StockScreenerKR-DailyBatch"
    Write-Host "Scheduled task exists. State: $($task.State)  LastRun: $($info.LastRunTime)  LastResult: $($info.LastTaskResult)  NextRun: $($info.NextRunTime)"
}

Write-Host ""
if ($afterExit -eq 0) {
    Write-Host "RESULT: data is up to date. Reload the page (Ctrl+Shift+R)." -ForegroundColor Green
} else {
    Write-Host "RESULT: still behind. Read the [AFTER] verdict above. If it says 'normal delay', the source (public data portal) has not published those days yet; nothing is broken." -ForegroundColor Yellow
}
Write-Host "Full output saved to logs\fix_local_data.log"
exit $afterExit
