# One command for the recommended order (ASCII only on purpose: Windows PowerShell 5.1 reads BOM-less .ps1 as CP949).
#   1) bring data up to date   (scripts\update_to_latest.ps1: backfill plan -> backfill -> daily batch -> freshness)
#   2) register the scheduled tasks (scripts\register_daily_batch_task.ps1) and show their state
#   3) optional: store a Slack/Discord webhook URL in .env for stale-data alerts
#   4) print the screen-check steps (Chrome device mode) and open the page
#
# Usage (project root, normal PowerShell):
#   git pull origin PROD_SCH
#   powershell -ExecutionPolicy Bypass -File scripts\setup_everything.ps1
# Options: -SkipBackfill (backfill already done)   -Yes (skip the backfill confirmation question)
param(
    [switch]$SkipBackfill,
    [switch]$Yes
)

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "##### STEP 1/4  bring data up to date #####" -ForegroundColor Magenta
$args1 = @("-ExecutionPolicy", "Bypass", "-File", (Join-Path $PSScriptRoot "update_to_latest.ps1"))
if ($SkipBackfill) { $args1 += "-SkipBackfill" }
if ($Yes) { $args1 += "-Yes" }
& powershell.exe @args1
$code1 = $LASTEXITCODE
if ($code1 -ne 0 -and $code1 -ne 2) {
    Write-Host "[STOP] step 1 failed (exit $code1). Fix it first, then run this script again (it resumes)." -ForegroundColor Red
    exit $code1
}
if ($code1 -eq 2) {
    Write-Host "[NOTE] latest trading day is not published yet (exit 2). Continuing; run step 1 again this evening." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "##### STEP 2/4  register scheduled tasks #####" -ForegroundColor Magenta
& powershell.exe -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "register_daily_batch_task.ps1")
if ($LASTEXITCODE -ne 0) {
    Write-Host "[WARN] registration returned exit $LASTEXITCODE. If it says access denied, run PowerShell as Administrator and retry this step." -ForegroundColor Yellow
}
Get-ScheduledTask -TaskName "StockScreenerKR-*" -ErrorAction SilentlyContinue |
    Get-ScheduledTaskInfo -ErrorAction SilentlyContinue |
    Format-Table TaskName, LastRunTime, LastTaskResult, NextRunTime -AutoSize
Write-Host "Expected: two tasks (DailyBatch 14:30/18:30, FreshnessCheck 09:10). The PC and Docker must be on at those times."

Write-Host ""
Write-Host "##### STEP 3/4  optional stale-data alert (webhook) #####" -ForegroundColor Magenta
$envFile = Join-Path $repoRoot ".env"
$hasHook = (Test-Path $envFile) -and (Select-String -Path $envFile -Pattern "^\s*DATA_FRESHNESS_WEBHOOK_URL=" -Quiet)
if ($hasHook) {
    Write-Host "DATA_FRESHNESS_WEBHOOK_URL is already set in .env."
} else {
    $url = Read-Host "Paste a Slack/Discord webhook URL for alerts (press Enter to skip)"
    if ($url) {
        if ($url -notmatch "^https://") {
            Write-Host "[SKIP] not an https:// URL. Nothing was written." -ForegroundColor Yellow
        } else {
            Add-Content -Path $envFile -Value "`r`nDATA_FRESHNESS_WEBHOOK_URL=$url" -Encoding utf8
            Write-Host "Saved to .env (keep it secret; .env is not committed)."
        }
    } else {
        Write-Host "Skipped."
    }
}

Write-Host ""
Write-Host "##### STEP 4/4  screen check (5 minutes) #####" -ForegroundColor Magenta
Write-Host @"
1. Make sure the app is running:  API on :4001 and frontend on :4000 (see the local server guide).
2. Chrome opens next. Press F12, then Ctrl+Shift+M (device toolbar).
3. Switch the device to iPhone SE, iPhone 14, Galaxy S20 and check:
   - no horizontal scrolling, no cut-off text
   - tabs and buttons are easy to tap
   - tapping the chart shows the selected bar's values
4. Open also: /  /screener  /screener/pattern  /stocks
5. Screenshot anything odd and send it to me.
"@
Start-Process "http://localhost:4000/stocks/005930"
Write-Host "Done. Report: the last lines of step 1 output, the task table above, and any odd screen."
exit 0
