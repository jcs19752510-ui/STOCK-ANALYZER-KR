# Windows-only cmdlets replaced by recording stubs so the real .ps1 scripts can run on Linux PowerShell (ASCII only).
# Used by tests/e2e/ps1_scripts_check.py. State and call log are files named by env HARNESS_LOG / HARNESS_STATE.
$global:Log = $env:HARNESS_LOG
$global:State = $env:HARNESS_STATE
function Write-Call([string]$text) { Add-Content -Path $global:Log -Value $text -Encoding utf8 }
function Registered-Names { if (Test-Path $global:State) { @(Get-Content $global:State) } else { @() } }

function Get-ScheduledTask {
    param([string[]]$TaskName, $ErrorAction)
    $have = Registered-Names
    foreach ($n in $TaskName) { if ($have -contains $n) { [pscustomobject]@{ TaskName = $n; State = "Ready" } } }
}
function Get-ScheduledTaskInfo { param([string]$TaskName) [pscustomobject]@{ LastRunTime = "2026-10-06 18:30"; LastTaskResult = 2; NextRunTime = "2026-10-07 14:30" } }
function New-ScheduledTaskSettingsSet { param([switch]$StartWhenAvailable, [switch]$AllowStartIfOnBatteries, [switch]$DontStopIfGoingOnBatteries, $RestartCount, $RestartInterval, $ExecutionTimeLimit) "settings" }
function New-ScheduledTaskAction { param([string]$Execute, [string]$Argument) [pscustomobject]@{ Execute = $Execute; Argument = $Argument } }
function New-ScheduledTaskTrigger { param([switch]$Daily, [string]$At) [pscustomobject]@{ At = $At } }
function Register-ScheduledTask {
    param([string]$TaskName, [switch]$Force, $Settings, $Action, $Trigger, [string]$Description)
    $times = ($Trigger | ForEach-Object { $_.At }) -join ","
    Write-Call "REGISTER $TaskName at=$times args=$($Action.Argument)"
    Add-Content -Path $global:State -Value $TaskName -Encoding utf8
}
function Unregister-ScheduledTask { param([string]$TaskName, $Confirm, $ErrorAction) Write-Call "UNREGISTER $TaskName" }

# restart_local.ps1 helpers
function Get-NetTCPConnection { param($LocalPort, $State, $ErrorAction) if ($env:HARNESS_PORTS_BUSY -eq "1") { [pscustomobject]@{ OwningProcess = 4242 } } }
function Stop-Process { param($Id, [switch]$Force, $ErrorAction) Write-Call "STOP-PROCESS $Id" }
function Start-Process { param($FilePath, $ArgumentList) Write-Call "START-PROCESS $FilePath $($ArgumentList -join ' ')" }
function Invoke-WebRequest {
    param($Uri, [switch]$UseBasicParsing, $TimeoutSec)
    Write-Call "GET $Uri"
    if ($env:HARNESS_WEB_DOWN -eq "1") { throw "connection refused" }
    [pscustomobject]@{ StatusCode = 200 }
}

# fake clock so 120s/180s waits finish instantly
$global:Now = [datetime]"2026-10-06T21:00:00"
function Get-Date { param([string]$Format) if ($Format) { $global:Now.ToString($Format) } else { $global:Now } }
function Start-Sleep { param($Seconds, $Milliseconds) if ($Seconds) { $global:Now = $global:Now.AddSeconds($Seconds) } }
