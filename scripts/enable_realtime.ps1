# Turn on the personal local realtime mode in one go (ASCII only on purpose: Windows PowerShell 5.1 reads BOM-less .ps1 as CP949).
#
# Usage (project root, normal PowerShell):
#   powershell -ExecutionPolicy Bypass -File scripts\enable_realtime.ps1
# Options: -NoRestart (do not restart the servers)   -SkipSmoke (skip the broker check)
#          -FromStdin (read key and secret from stdin, 2 lines; for automated tests)   -RepoRoot <dir> (tests)
#
# What it does:
#   1) .env: makes sure LOCAL_INTRADAY_ENABLED=true, KIS_APP_KEY and KIS_APP_SECRET are set.
#      If the key/secret are missing it first looks in the older .env.bak-* backups of this folder (restores them, values hidden),
#      otherwise it asks for them (hidden input). Other lines are kept. The old file is saved as .env.bak-realtime-<time>.
#   2) frontend\.env.local: makes sure NEXT_PUBLIC_LOCAL_INTRADAY_ENABLED=true.
#   3) runs scripts\kis_smoke_test.py (read-only broker check; prints no secrets).
#   4) restarts the API and the web (scripts\restart_local.ps1) because both read these settings only at start.
# Secrets are never printed or logged.
param(
    [string]$RepoRoot = "",
    [switch]$NoRestart,
    [switch]$SkipSmoke,
    [switch]$FromStdin
)

if (-not $RepoRoot) { $RepoRoot = Split-Path -Parent $PSScriptRoot }
Set-Location $RepoRoot
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$utf8 = New-Object System.Text.UTF8Encoding($false)
$envFile = Join-Path $RepoRoot ".env"
$webFile = Join-Path $RepoRoot "frontend\.env.local"
if (-not (Test-Path $envFile)) { Write-Host "[ERROR] .env not found: $envFile" -ForegroundColor Red; exit 2 }

function Read-Raw([string]$path) {
    if (-not (Test-Path $path)) { return "" }
    return [System.IO.File]::ReadAllText($path, $utf8).TrimStart([char]0xFEFF)
}
function Split-Lines([string]$raw) {
    $lines = @($raw -split "`r?`n")
    while ($lines.Count -gt 0 -and $lines[$lines.Count - 1].Trim() -eq "") { $lines = @($lines | Select-Object -First ($lines.Count - 1)) }
    return $lines
}
function Get-Val([string[]]$lines, [string]$key) {
    foreach ($l in $lines) {
        $t = $l.Trim()
        if ($t.StartsWith("#")) { continue }
        $i = $t.IndexOf("=")
        if ($i -gt 0 -and $t.Substring(0, $i).Trim() -eq $key) { return $t.Substring($i + 1).Trim().Trim('"').Trim("'") }
    }
    return ""
}
function Set-Val([string[]]$lines, [string]$key, [string]$value) {
    $out = @()
    $done = $false
    foreach ($l in $lines) {
        $t = $l.Trim()
        $i = $t.IndexOf("=")
        if ((-not $t.StartsWith("#")) -and $i -gt 0 -and $t.Substring(0, $i).Trim() -eq $key) {
            if (-not $done) { $out += "$key=$value"; $done = $true }
            continue
        }
        $out += $l
    }
    if (-not $done) { $out += "$key=$value" }
    return $out
}
function Write-Lines([string]$path, [string[]]$lines, [string]$nl) {
    $dir = Split-Path -Parent $path
    if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }
    [System.IO.File]::WriteAllText($path, (($lines -join $nl) + $nl), $utf8)
}
function Read-Secret([string]$prompt) {
    if ($FromStdin) { return [Console]::In.ReadLine() }
    $s = Read-Host -AsSecureString $prompt
    $b = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($s)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($b) } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($b) }
}

$raw = Read-Raw $envFile
$nl = if ($raw.Contains("`r`n")) { "`r`n" } else { "`n" }
$lines = Split-Lines $raw
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"

# --- 1) key and secret
$key = Get-Val $lines "KIS_APP_KEY"
$secret = Get-Val $lines "KIS_APP_SECRET"
if (-not $key -or -not $secret) {
    $restored = $null
    $backups = @(Get-ChildItem -Path $RepoRoot -Filter ".env.bak-*" -File -Force -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending)
    foreach ($b in $backups) {
        $bl = Split-Lines (Read-Raw $b.FullName)
        $bk = Get-Val $bl "KIS_APP_KEY"
        $bs = Get-Val $bl "KIS_APP_SECRET"
        if ($bk -and $bs) { $key = $bk; $secret = $bs; $restored = $b.Name; break }
    }
    if ($restored) {
        Write-Host "KIS_APP_KEY / KIS_APP_SECRET were missing in .env: restored from $restored (values hidden)." -ForegroundColor Yellow
    } else {
        Write-Host "KIS_APP_KEY / KIS_APP_SECRET are not in .env or its backups. Enter them (input is hidden; real-account keys from KIS Developers)." -ForegroundColor Cyan
        $key = Read-Secret "KIS_APP_KEY"
        $secret = Read-Secret "KIS_APP_SECRET"
    }
}
if ([string]::IsNullOrWhiteSpace($key) -or [string]::IsNullOrWhiteSpace($secret)) {
    Write-Host "[STOP] key or secret is empty. Nothing was changed." -ForegroundColor Red
    exit 1
}
Copy-Item -Path $envFile -Destination "$envFile.bak-realtime-$stamp"
$lines = Set-Val $lines "LOCAL_INTRADAY_ENABLED" "true"
$lines = Set-Val $lines "KIS_APP_KEY" $key.Trim()
$lines = Set-Val $lines "KIS_APP_SECRET" $secret.Trim()
Write-Lines $envFile $lines $nl
$key = $null
$secret = $null
Write-Host ".env: LOCAL_INTRADAY_ENABLED / KIS_APP_KEY / KIS_APP_SECRET are set (backup: .env.bak-realtime-$stamp)." -ForegroundColor Green

# --- 2) web setting
$webRaw = Read-Raw $webFile
$webNl = if ($webRaw.Contains("`r`n")) { "`r`n" } else { "`n" }
$webLines = Split-Lines $webRaw
if (Test-Path $webFile) { Copy-Item -Path $webFile -Destination "$webFile.bak-realtime-$stamp" }
$webLines = Set-Val $webLines "NEXT_PUBLIC_LOCAL_INTRADAY_ENABLED" "true"
Write-Lines $webFile $webLines $webNl
Write-Host "frontend\.env.local: NEXT_PUBLIC_LOCAL_INTRADAY_ENABLED=true" -ForegroundColor Green

# --- 3) broker check
if (-not $SkipSmoke) {
    Write-Host "=== broker check (kis_smoke_test.py, read-only) ===" -ForegroundColor Cyan
    foreach ($line in (Get-Content $envFile -Encoding UTF8)) {
        $t = $line.Trim()
        if ($t -eq "" -or $t.StartsWith("#")) { continue }
        $i = $t.IndexOf("=")
        if ($i -lt 1) { continue }
        $k = $t.Substring(0, $i).Trim()
        if (@("KIS_APP_KEY", "KIS_APP_SECRET", "LOCAL_INTRADAY_ENABLED") -contains $k) { [Environment]::SetEnvironmentVariable($k, $t.Substring($i + 1).Trim().Trim('"').Trim("'"), "Process") }
    }
    $env:PYTHONUTF8 = "1"
    & py -3.12 scripts\kis_smoke_test.py 2>&1 | ForEach-Object { "$_" }
    $smoke = $LASTEXITCODE
    if ($smoke -ne 0) {
        Write-Host "[WARN] the broker check did not pass (exit $smoke). Settings are saved. Read the lines above, fix the cause, then run this script again." -ForegroundColor Yellow
        exit 3
    }
}

# --- 4) restart
if ($NoRestart) {
    Write-Host "Done (no restart). Run scripts\restart_local.ps1 to apply." -ForegroundColor Green
    exit 0
}
Write-Host "=== restarting API and web ===" -ForegroundColor Cyan
& powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "restart_local.ps1")
exit $LASTEXITCODE
