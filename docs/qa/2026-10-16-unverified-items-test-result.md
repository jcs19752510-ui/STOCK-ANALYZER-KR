# "확인하지 못한 것" 3건 개발 시험 결과서 (DEC-103, 2026-10-16)

범위: 직전 결과서들에서 "이 환경에서 확인 못 함"으로 남긴 ① 실제 KIS 응답 지연·호출 한도 ② Windows PowerShell 5.1·작업 스케줄러 ③ 증권사 약관(일봉 DB 캐시).
환경: Linux 컨테이너(PowerShell 7.4.5 설치 가능, Windows 아님), 앱키 없음, 외부 접속은 프록시 경유.
**결론: 3건 모두 이 환경에서 끝까지 확인할 수는 없다. 할 수 있는 만큼 했고, 남은 것은 사용자 PC에서만 확인된다.**

## 1. 실제 KIS 응답 지연·호출 한도
| 시도 | 결과 |
|---|---|
| `openapi.koreainvestment.com:9443`, `apiportal.koreainvestment.com:443` TLS 접속 | **둘 다 실패(응답 코드 000)** — 이 환경의 프록시가 막고 있다(7.2초 대기 후 실패, 개발자포털은 DNS 실패 `ENOTFOUND`) |
| 앱키 | 이 세션에 없음(CLAUDE.MD 규칙 2: 앱키 응답은 에이전트가 할 수 없는 항목) |
| 대안 | `scripts/kis_speed_probe.py`(DEC-102)를 만들어 사용자 PC에서 한 번에 측정. 모의 서버(지연·초당 한도 주입) 5건 + 종단 실행 통과 |
- 판정: **미확인(이 환경 불가).** 사용자 PC에서 `py -3.12 scripts\kis_speed_probe.py` 한 번이면 된다.

## 2. Windows PowerShell 5.1 · 작업 스케줄러
방법: Linux에서는 5.1을 실행할 수 없으므로 소스를 기준으로 정적 점검했다. PSScriptAnalyzer(호환 프로필)는 PSGallery 접속이 막혀 설치하지 못했다.
| 점검 | 결과 |
|---|---|
| `scripts/*.ps1` 8개(시험용 stubs 제외) 중 한글 등 비ASCII 포함 파일 | `run_daily_batch.ps1` 1개뿐(1170바이트). **이 파일은 UTF-8 BOM이 있어** 5.1이 올바르게 읽는다. 나머지 7개는 순수 ASCII라 인코딩 영향 없음 |
| BOM이 없어졌다고 가정하고 cp949·cp1252로 오독시킨 시뮬레이션 | 따옴표·괄호·중괄호·`$`·`|`·`;`·`[]` 개수 변화 없음(문법이 깨지지 않고 글자만 깨지는 수준) |
| PowerShell 6+ 전용 구성요소(`$IsWindows`, `-SkipHttpErrorCheck`, `?? ?. && \|\|`, `-AdditionalChildPath`, `-Parallel`, `-AsHashtable`, `utf8NoBOM` 등) | **0건** (첫 검출 1건은 `-Filter "20??.yaml"` 와일드카드 오탐) |
| 파일 읽기·쓰기 | `Get-Content`/`Add-Content` 모두 `-Encoding utf8` 명시 |
| 웹 요청 | `Invoke-WebRequest ... -UseBasicParsing` 사용(5.1에서 권장) |
| 작업 스케줄러 명령 | `New-ScheduledTaskSettingsSet`(`-StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount -RestartInterval -ExecutionTimeLimit`), `New-ScheduledTaskAction -Execute powershell.exe`(=5.1), `New-ScheduledTaskTrigger -Daily -At`, `Register-ScheduledTask -Force`, `Get-ScheduledTask(Info)` — 모두 5.1의 `ScheduledTasks` 모듈에 있는 이름·매개변수다(**지식 기준이며 이 환경에서 실행으로 확인한 것은 아님**) |
| 고정 시험 | `tests/unit/test_ps1_windows_compat.py` 16건 통과(위 규칙을 앞으로도 강제: 6+ 전용 금지, 비ASCII는 BOM 필수) |
| 기존 | PowerShell 7 하네스 `ps1_scripts_check.py` 23/23(스케줄러 명령은 기록 대역으로 검증) |
- 판정: **정적 점검 통과. 5.1 실제 실행·실제 작업 스케줄러 등록은 미확인.** 사용자 PC에서 `scripts\fix_local_data.ps1`(스케줄러 등록 포함)을 실행하고 `Get-ScheduledTask -TaskName StockScreenerKR-*`로 3개가 보이면 확인 완료.

## 3. 증권사 약관(일봉 DB 캐시)
방법: 웹 검색 2회 + 개발자포털 직접 조회(접속 불가).
- **약관 원문은 찾지 못했다.** 저장·재배포·상업적 이용에 관한 조항을 직접 확인하지 못했다.
- 검색으로 확인된 공개 정보(근거: [KIS Developers 제휴 안내](https://apiportal.koreainvestment.com/provider), [제휴 신청](https://apiportal.koreainvestment.com/provider-apply)):
  - 오픈API로 **외부 고객(제3자)에게 서비스를 제공**하려는 법인은 별도 제휴 대상이고, 제도권 금융회사가 아니면 제휴가 불가하다는 안내가 있다.
  - **시세정보 API 이용 시 KRX·해외거래소와 정보이용계약을 체결했는지 확인**하라는 안내가 있다.
  - 서비스 신청 시 고객 이용약관 동의가 필수다.
- 이 프로젝트에의 의미(법률 판단 아님): 서비스가 **본인 PC 전용·본인 사용**이면 "제3자 제공"에 해당하지 않을 가능성이 크지만, 일봉을 DB에 저장하는 것이 약관상 허용되는지는 **원문을 읽어야 안다.** 사이트를 다른 사람에게 보이게 하거나 Render 등에 올릴 경우에는 제3자 제공·거래소 정보이용계약 쟁점이 생긴다(이번에 Render를 쓰지 않기로 해 이 위험은 줄었다).
- 판정: **미확인.** 사용자가 KIS Developers 로그인 후 이용약관 전문에서 "저장/재배포/제3자 제공/상업적 이용" 조항을 확인하거나, 고객센터에 문의해야 한다. 불명확하면 일봉 캐시(`kis_daily_bar`)는 본인 PC 전용으로만 쓰고 외부에 공개하지 않는다.

## 4. 다시 돌린 회귀
- 전체 회귀(4분할 병렬, 조각별 독립 DB): 1506 통과 / 1 건너뜀 / 0 실패, 2분 14초(`2ff4e4e` 기준). 이후 추가분은 `test_ps1_windows_compat.py` 16건(별도 통과).

## 5. 재현 방법
```
source /tmp/claude-0/pgenv.sh
python -m pytest tests/unit/test_ps1_windows_compat.py -q
curl -sS -m 8 -o /dev/null -w "%{http_code}\n" https://openapi.koreainvestment.com:9443/   # 이 환경: 000(차단)
```
