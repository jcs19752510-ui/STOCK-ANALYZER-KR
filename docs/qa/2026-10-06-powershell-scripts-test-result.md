# 내부 테스트 결과서 — Windows PowerShell 스크립트 실행 시험 (DEC-094)

- 작성일: 2026-10-06 / 대상: `scripts/*.ps1` 7개(`fix_local_data`, `register_daily_batch_task`, `restart_local`, `run_daily_batch`, `update_to_latest`, `setup_everything`, `start_local_api`)
- 계기: 사용자 지시 — "에이전트가 할 수 있는 시험은 사용자에게 시키지 말고 직접 한다"(CLAUDE.MD 상시 규칙 1). 이전 결과서들은 "PowerShell이 없어 실행하지 못했다"고 적었으나, PowerShell 7을 내려받아 **실제로 실행**했다.
- 환경: Linux, PowerShell 7.4.5(`pwsh`, 공식 배포본을 내려받아 사용), Python 3.12, PostgreSQL 16 임시 DB(실제 달력 적재·진단 실행). 재현: `PWSH=<pwsh 경로> python tests/e2e/ps1_scripts_check.py`

## 1. 시험 방법
- 스크립트 **원본을 수정하지 않고 그대로** 실행한다.
- Windows에만 있는 부분(작업 스케줄러 `Register-ScheduledTask` 등, 포트 `Get-NetTCPConnection`, `Start-Process`, `Invoke-WebRequest`, `cmd /c`, `py -3.12`, `docker`)은 **호출을 기록하는 대역**(`tests/e2e/ps1/stubs.ps1`과 실행 파일 대역)으로 바꿨다.
- 파이썬 쪽(진단 `diagnose_local_data.py`, 달력 적재 `load_calendar.py`)은 **진짜로** 임시 PostgreSQL에 대고 돌렸다. 일일 배치 본체(`run_daily_batch.py`)는 공공데이터 키가 없어 "공개 전(종료코드 2)" 대역으로 바꿨고, 배치 본체는 pytest 종단 시험(가짜 공공데이터 서버)이 따로 검증한다.
- 시계는 가짜(대기 120·180초가 즉시 끝남).

## 2. 결과 — 22/22 통과
| # | 케이스 | 기대 | 결과 |
|---|---|---|---|
| 1~7 | 구문: 7개 스크립트 | 파싱 오류 0 | 통과 |
| 8 | fix_local_data: 단계 제목 5개 출력 | 모두 출력 | 통과 |
| 9 | 진단 출력이 사라지지 않고 두 번(전·후) 보임 | **이전 결함 회귀 방지**(함수 출력이 파이프라인으로 흘러가 진단 결과가 비어 보이던 문제) | 통과 |
| 10 | 배치 종료코드가 숫자 하나로 표시 | 이전엔 출력 전체가 섞여 나왔음 | 통과 |
| 11 | 달력 2026·2027 파일 적재 단계 실행 | 각 730행 반영 | 통과 |
| 12 | DB 달력이 2027-12-31까지 | 적재됨 | 통과 |
| 13 | 스케줄러 3개 등록: DailyBatch 14:30·18:30 / FreshnessCheck 09:10 / InvestorFlow 20:10 | 이름·시각 일치 | 통과 |
| 14 | 수급 작업이 `collect_investor_flow.py`·`investor_flow.log`를 호출 | 실행 인자 일치 | 통과 |
| 15 | 종료코드 2(진단 후 지연 있음) + RESULT 문구 | 일치 | 통과 |
| 16 | `logs\fix_local_data.log`에 같은 내용 저장 | 저장됨 | 통과 |
| 17 | 두 번째 실행은 스케줄러를 다시 등록하지 않음 | "Scheduled task exists" | 통과 |
| 18 | register `-Remove`: 작업 3개 삭제 | 3회 호출 | 통과 |
| 19 | run_daily_batch.ps1 래퍼(스케줄러가 부르는 파일): .env 주입, 로그 시작·끝(exit=2), 실행 결과 기록 | 일치 | 통과 |
| 20 | restart_local: 옛 프로세스 2개 종료 후 API·웹을 새 창으로 시작 | 일치 | 통과 |
| 21 | restart_local: 두 서비스 응답 확인(4001 `/api/v1/live`, 4000 `/login`) | 일치 | 통과 |
| 22 | restart_local: 응답이 없으면 원인 안내 + 종료코드 1 | "did not answer", rc=1 | 통과 |

## 3. 시험 중 발견·정리한 사항
| # | 발견 | 조치 |
|---|---|---|
| 1 | 시험 대역의 `cmd` 흉내가 경로의 `\`를 지워 파이썬 스크립트를 못 찾음 | 제품 결함이 아니라 대역 문제 — 대역이 `\`를 `/`로 바꾸도록 수정 |
| 2 | 대역의 전역 변수 범위 오류(`$script:`) | 대역을 `$global:`로 수정 |
| 3 | 제품 스크립트는 수정 없이 22개 모두 통과 | — |

## 4. 확인하지 못한 것·위험 (정직하게)
| # | 내용 | 설명 |
|---|---|---|
| 1 | **실제 Windows PowerShell 5.1에서의 동작** | 이 시험은 PowerShell **7.4**(Linux)다. 5.1은 BOM 없는 파일을 CP949로 읽는 등 차이가 있어, 모든 `.ps1`이 영문(ASCII)만 쓰는지 정적 시험(`test_scheduler_scripts.py`)이 따로 확인한다. 7에서 통과한 문법이 5.1에서 안 되는 경우(예: 7 전용 문법)는 스크립트에서 쓰지 않았음을 눈으로 점검했으나 5.1 실행으로는 확인하지 못했다. |
| 2 | Windows 전용 명령의 **실제 인자·반환 모양** | `Register-ScheduledTask`, `Get-ScheduledTask(Info)`, `Get-NetTCPConnection`, `Start-Process`는 대역으로 대신했다. 대역은 공식 문서의 매개변수 이름을 따라 만들었지만 실제 Windows와 100% 같음을 증명하지는 못한다. 이 부분은 사용자 PC 실행으로만 최종 확인된다. |
| 3 | `docker`·`alembic`·`next dev`·실제 포트 | 대역. 앞의 장중 기준 종단 시험(실제 `next dev`·API·DB)이 다른 경로로 확인했다. |
| 4 | `update_to_latest.ps1`, `setup_everything.ps1`, `start_local_api.ps1` | 구문만 통과. 실행(백필·docker)은 외부 의존이 커 대역 시험을 만들지 않았다. |

## 5. 후속
- 이 시험(`tests/e2e/ps1_scripts_check.py`)은 pwsh가 있을 때 언제든 다시 돌릴 수 있다. 없으면 건너뛰며 통과로 세지 않는다.
- 향후 `.ps1` 변경은 이 시험을 통과시킨 뒤 푸시한다(CLAUDE.MD 상시 규칙 1).
