# 로컬(Windows) 개발환경 전용 스케줄러 실행 래퍼.
#
# scripts/run_daily_batch.py(플랫폼 무관 드라이버) 자체는 어떤 스케줄러
# 기술로 호출해도 상관없다. 이 파일은 그 중 "Windows 작업 스케줄러가
# .ps1을 직접 실행"하는 방식을 이 개발 PC에 붙이기 위한 얇은 래퍼일 뿐이다
# — 나중에 실제 호스팅 플랫폼이 정해지면(리눅스 서버/컨테이너 등) 이 파일
# 대신 그 플랫폼의 cron/Scheduled Job이 run_daily_batch.py를 직접 호출하면
# 되고, 이 파일은 쓰지 않게 된다.
#
# 역할: repo 루트의 .env를 읽어 환경변수로 주입 + 실행 로그를
# logs/daily_batch.log에 타임스탬프와 함께 append(.gitignore 처리됨).
#
# 주의(PowerShell 5.1 특성): 네이티브 프로세스(python.exe)의 stderr를
# `2>&1`/`*>>`로 PowerShell 파이프라인에 직접 섞으면 각 줄이
# ErrorRecord로 래핑되어 `$ErrorActionPreference` 설정에 따라 의도치 않게
# 예외로 취급될 수 있다. 이를 피하기 위해 `cmd /c`로 감싸 순수 텍스트
# 스트림으로 리다이렉트한다(한글 깨짐 방지를 위해 `chcp 65001` + `PYTHONUTF8=1`).

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$logDir = Join-Path $repoRoot "logs"
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
}
$logFile = Join-Path $logDir "daily_batch.log"

$envFile = Join-Path $repoRoot ".env"
if (Test-Path $envFile) {
    Get-Content $envFile -Encoding utf8 | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
            $key, $value = $line.Split("=", 2)
            [System.Environment]::SetEnvironmentVariable($key.Trim(), $value.Trim())
        }
    }
}
$env:PYTHONUTF8 = "1"
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

# 헤더/푸터는 일부러 영문만 쓴다 — Windows PowerShell 5.1은 BOM 없는 .ps1
# 파일을 시스템 기본 ANSI 코드페이지(CP949)로 읽어, 스크립트 소스에 직접
# 적은 한글 리터럴이 "파싱 시점"에 이미 깨지는 것을 실측으로 확인했다
# (출력 인코딩 문제가 아니라 소스 파싱 문제라 -Encoding 계열로는 못 고침).
# python이 실제로 출력하는 한글(PYTHONUTF8=1, 데이터로 흘러들어옴)은 이
# 문제가 없어 그대로 둔다.
$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
[System.IO.File]::AppendAllText($logFile, "===== $timestamp KST run start =====`r`n", $utf8NoBom)

cmd /c "chcp 65001 >nul & python scripts\run_daily_batch.py >>`"$logFile`" 2>&1"
$exitCode = $LASTEXITCODE

$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
[System.IO.File]::AppendAllText($logFile, "===== $timestamp KST run end (exit=$exitCode) =====`r`n", $utf8NoBom)

exit $exitCode
