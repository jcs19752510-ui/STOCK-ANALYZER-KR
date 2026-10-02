# Start the public API for local use (port 4001).
# The API does NOT read .env by itself, so this script copies only the needed
# keys from .env into this process environment, then starts the official launcher.
# Secret values are never printed. Keep this file ASCII-only (Windows PowerShell 5.1).
#
# Usage (repo root):  powershell -ExecutionPolicy Bypass -File scripts\start_local_api.ps1

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"

$envFile = Join-Path $repoRoot ".env"
if (-not (Test-Path $envFile)) { Write-Host "[ERROR] .env not found: $envFile"; exit 1 }

$keys = @(
  "PUBLIC_API_DATABASE_URL",
  "PUBLIC_API_CORS_ALLOWED_ORIGINS",
  "PUBLIC_API_INTERNAL_TOKEN",
  "LOCAL_INTRADAY_ENABLED",
  "KIS_APP_KEY",
  "KIS_APP_SECRET"
)

$loaded = @()
foreach ($line in (Get-Content $envFile -Encoding UTF8)) {
  $t = $line.Trim()
  if ($t -eq "" -or $t.StartsWith("#")) { continue }
  $i = $t.IndexOf("=")
  if ($i -lt 1) { continue }
  $k = $t.Substring(0, $i).Trim()
  if ($keys -contains $k) {
    [Environment]::SetEnvironmentVariable($k, $t.Substring($i + 1).Trim(), "Process")
    $loaded += $k
  }
}

if (-not $env:PUBLIC_API_PORT) { $env:PUBLIC_API_PORT = "4001" }

Write-Host "Loaded from .env (values hidden):"
foreach ($k in $keys) {
  $mark = "missing"
  if ($loaded -contains $k) { $mark = "set" }
  Write-Host ("  {0,-34} {1}" -f $k, $mark)
}
if ($loaded -notcontains "PUBLIC_API_DATABASE_URL") {
  Write-Host "[WARN] PUBLIC_API_DATABASE_URL is missing: data APIs will return 503."
}
Write-Host "Starting API on port $($env:PUBLIC_API_PORT) ... (Ctrl+C to stop)"
py -3.12 scripts\run_public_api.py
