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

# migrations first (idempotent): a new table such as kis_daily_bar (0019) must exist before the batch helper steps use it
$migExit = Step "[migrate] alembic upgrade head" "py -3.12 -m alembic upgrade head"
if ($migExit -ne 0) { Write-Host "[WARN] DB migration failed (exit $migExit). Data catch-up continues; newer optional features may be skipped." -ForegroundColor Yellow }

# calendars: load every data\calendar\20xx.yaml (idempotent upsert) so a new year never leaves the batch without a trading calendar
Get-ChildItem (Join-Path $repoRoot "data\calendar") -Filter "20??.yaml" | Sort-Object Name | ForEach-Object {
    $null = Step ("[calendar] load " + $_.Name) ("py -3.12 scripts\load_calendar.py data\calendar\" + $_.Name)
}

$beforeExit = Step "[2/5] diagnosis BEFORE" "py -3.12 scripts\diagnose_local_data.py"
$batchExit = Step "[3/5] catch-up batch (this can take several minutes)" "py -3.12 scripts\run_daily_batch.py"
Write-Host "batch exit code: $batchExit  (0 = ok / nothing to do, 2 = source has not published the day yet, other = failure: read the lines above)"
$afterExit = Step "[4/5] diagnosis AFTER" "py -3.12 scripts\diagnose_local_data.py"

Write-Host ""
Write-Host "=== [5/5] scheduled task ===" -ForegroundColor Cyan
$task = Get-ScheduledTask -TaskName "StockScreenerKR-DailyBatch" -ErrorAction SilentlyContinue
$taskFlow = Get-ScheduledTask -TaskName "StockScreenerKR-InvestorFlow" -ErrorAction SilentlyContinue
if ($null -eq $task -or $null -eq $taskFlow) {
    Write-Host "A scheduled task is missing (daily batch 14:30/18:30, freshness 09:10, investor flow 20:10). Registering all now ..."
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
