# Reset a web/local login password (ASCII only on purpose: Windows PowerShell 5.1 reads BOM-less .ps1 as CP949).
#
# Usage (project root, normal PowerShell):
#   powershell -ExecutionPolicy Bypass -File scripts\reset_password.ps1                    # user jcw1973
#   powershell -ExecutionPolicy Bypass -File scripts\reset_password.ps1 -Username other_id
#   powershell -ExecutionPolicy Bypass -File scripts\reset_password.ps1 -ListOnly          # only list the users
# Options: -Yes (do not ask when the target DB differs from the API login DB)
#          -FromStdin (read the password twice from stdin instead of the hidden prompt; for automated tests)
#
# What it does:
#   1) reads .env and picks the DB to change: AUTH_ADMIN_DATABASE_URL, else PUBLIC_API_AUTH_DATABASE_URL (the DB the API
#      reads for logins), else ALEMBIC_DATABASE_URL. Only host:port/database is printed, never a password.
#   2) lists the users in that DB (so you can see the exact id) and stops if the id is not there
#   3) asks for the new password twice (hidden), sets it (scripts\manage_users.py set-password), which also clears the
#      failed-attempt counter and the lock and signs the user out of every device
#   4) checks that the new password matches what is stored
# The password is sent to python through a pipe (stdin), never on a command line. Nothing secret is printed or logged.
param(
    [string]$Username = "jcw1973",
    [switch]$ListOnly,
    [switch]$Yes,
    [switch]$FromStdin
)

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = New-Object System.Text.UTF8Encoding($false)

$envFile = Join-Path $repoRoot ".env"
if (-not (Test-Path $envFile)) { Write-Host "[ERROR] .env not found: $envFile" -ForegroundColor Red; exit 2 }
$wanted = @("AUTH_ADMIN_DATABASE_URL", "PUBLIC_API_AUTH_DATABASE_URL", "ALEMBIC_DATABASE_URL")
foreach ($line in (Get-Content $envFile -Encoding UTF8)) {
    $t = $line.Trim()
    if ($t -eq "" -or $t.StartsWith("#")) { continue }
    $i = $t.IndexOf("=")
    if ($i -lt 1) { continue }
    $k = $t.Substring(0, $i).Trim()
    if ($wanted -contains $k) { [Environment]::SetEnvironmentVariable($k, $t.Substring($i + 1).Trim().Trim('"'), "Process") }
}

function Describe-Db([string]$url) {
    if ($url -match '^.*@(?<h>[^/:?#@]+)(?::(?<p>\d+))?/(?<d>[^?\s]+)') {
        $port = if ($Matches.p) { $Matches.p } else { "5432" }
        return "$($Matches.h):$port/$($Matches.d)"
    }
    return "(cannot read host/database)"
}

$target = $null
$targetName = $null
foreach ($n in $wanted) {
    $v = [Environment]::GetEnvironmentVariable($n, "Process")
    if ($v) { $target = $v; $targetName = $n; break }
}
if (-not $target) {
    Write-Host "[ERROR] none of AUTH_ADMIN_DATABASE_URL / PUBLIC_API_AUTH_DATABASE_URL / ALEMBIC_DATABASE_URL is set in .env." -ForegroundColor Red
    exit 2
}
$apiAuth = $env:PUBLIC_API_AUTH_DATABASE_URL
$targetDesc = Describe-Db $target
Write-Host "Target DB (from $targetName): $targetDesc"
if ($apiAuth) {
    $apiDesc = Describe-Db $apiAuth
    Write-Host "DB the API uses for logins:    $apiDesc"
    if ($apiDesc -ne $targetDesc) {
        Write-Host "[WARN] These are different databases. A password changed here will NOT work for the web login." -ForegroundColor Yellow
        if (-not $Yes) {
            $answer = Read-Host "Continue anyway? (y/N)"
            if ($answer -notmatch '^[yY]') { Write-Host "Stopped. Nothing was changed."; exit 1 }
        }
    }
} else {
    Write-Host "[WARN] PUBLIC_API_AUTH_DATABASE_URL is not set in .env: the API cannot check logins at all." -ForegroundColor Yellow
    Write-Host "       Run  py -3.12 scripts\setup_local_auth.py  after this (it asks for the member DB address)." -ForegroundColor Yellow
}
$env:AUTH_ADMIN_DATABASE_URL = $target

Write-Host "=== users in this DB ===" -ForegroundColor Cyan
$listOut = & py -3.12 scripts\manage_users.py list 2>&1 | Out-String
$listCode = $LASTEXITCODE
Write-Host $listOut
if ($listCode -ne 0) {
    Write-Host "[ERROR] could not read the user list (exit $listCode). Check that the database is running and the address in .env is right." -ForegroundColor Red
    exit 1
}
if ($ListOnly) { exit 0 }
if ($listOut.ToLower().IndexOf($Username.ToLower()) -lt 0) {
    Write-Host "[STOP] '$Username' is not in the list above. Check the spelling (run again with -Username <id>). Nothing was changed." -ForegroundColor Red
    exit 1
}

function Read-Plain([string]$prompt) {
    if ($FromStdin) { return [Console]::In.ReadLine() }
    $secure = Read-Host -AsSecureString $prompt
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
}
Write-Host "=== new password for '$Username' (8+ characters, input is hidden) ===" -ForegroundColor Cyan
$p1 = Read-Plain "New password"
$p2 = Read-Plain "New password again"
if ([string]::IsNullOrEmpty($p1) -or $p1 -ne $p2) {
    Write-Host "[STOP] the two passwords are empty or different. Nothing was changed." -ForegroundColor Red
    exit 1
}

$setOut = $p1 | & py -3.12 scripts\manage_users.py set-password $Username --password-stdin 2>&1 | Out-String
$setCode = $LASTEXITCODE
Write-Host $setOut
if ($setCode -ne 0) {
    Write-Host "[ERROR] password was NOT changed (exit $setCode). Read the message above (for example the password rules)." -ForegroundColor Red
    exit 1
}
$chk = $p1 | & py -3.12 scripts\manage_users.py verify-password $Username --password-stdin 2>&1 | Out-String
$chkCode = $LASTEXITCODE
Write-Host $chk
$p1 = $null
$p2 = $null
if ($chkCode -ne 0) {
    Write-Host "[WARN] the check after changing did not match. Run this script again." -ForegroundColor Yellow
    exit 1
}
Write-Host "Done. '$Username' was signed out everywhere. Open http://localhost:4000/login and log in with the new password." -ForegroundColor Green
exit 0
