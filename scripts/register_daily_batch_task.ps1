# Registers the Windows Task Scheduler jobs for the daily batch (DEC-047).
# ASCII only on purpose: Windows PowerShell 5.1 reads BOM-less .ps1 files as CP949.
#
# Usage (normal PowerShell, no admin needed for a per-user task):
#   powershell -ExecutionPolicy Bypass -File scripts\register_daily_batch_task.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\register_daily_batch_task.ps1 -Remove
#
# Jobs (idempotent: re-running replaces them):
#   StockScreenerKR-DailyBatch      14:30 and 18:30 every day (ingest + derive + catch-up)
#   StockScreenerKR-FreshnessCheck  09:10 every day (read-only; webhook alert when stale)
# The batch is safe to run several times a day: when data is already current it exits
# without calling the API. If the PC was off, StartWhenAvailable runs it at next boot,
# and the catch-up logic fills any missed trading days.
param([switch]$Remove)

$wrapper = Join-Path $PSScriptRoot "run_daily_batch.ps1"
$names = @("StockScreenerKR-DailyBatch", "StockScreenerKR-FreshnessCheck")

if ($Remove) {
    foreach ($n in $names) {
        Unregister-ScheduledTask -TaskName $n -Confirm:$false -ErrorAction SilentlyContinue
    }
    Write-Host "Removed scheduled tasks."
    exit 0
}

$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 15) `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)

function New-PsAction([string]$extraArgs) {
    $arg = "-NoProfile -ExecutionPolicy Bypass -File `"$wrapper`" $extraArgs"
    New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arg
}

$batchTriggers = @(
    (New-ScheduledTaskTrigger -Daily -At "14:30"),
    (New-ScheduledTaskTrigger -Daily -At "18:30")
)
Register-ScheduledTask -TaskName $names[0] -Force -Settings $settings `
    -Action (New-PsAction "") -Trigger $batchTriggers `
    -Description "Stock screener daily batch (ingest, derive, catch-up)" | Out-Null

Register-ScheduledTask -TaskName $names[1] -Force -Settings $settings `
    -Action (New-PsAction "-Script scripts\check_data_freshness.py -LogName freshness.log") `
    -Trigger (New-ScheduledTaskTrigger -Daily -At "09:10") `
    -Description "Stock screener data freshness check (read-only)" | Out-Null

Get-ScheduledTask -TaskName $names | Format-Table TaskName, State -AutoSize
Write-Host "Done. Set DATA_FRESHNESS_WEBHOOK_URL in .env to receive stale-data alerts."
