# 내부 테스트 결과서 — 일일 배치 스케줄링 (R5, DEC-047·DEC-053)

- 작성일: 2026-10-02 (KST) / 대상 브랜치: `PROD_SCH`
- 판정: **조건부 통과** — 배치·따라잡기·미배포 재시도·시도 상한·신선도 알림은 **실제 PostgreSQL + 모의 공공데이터 서버 + 실제 `run_daily_batch.py` 실행**으로 종단 검증해 통과. **Windows 작업 스케줄러 등록(`register_daily_batch_task.ps1`)은 이 환경(Linux, PowerShell 없음)에서 실행·검증하지 못했다** — 사용자 PC에서 1회 실행 후 §6 확인 절차로 확인해야 한다.

## 1. 범위
| 구성 | 파일 | 검증 방식 |
|---|---|---|
| 일일 배치(종목 마스터→수집→가공, 따라잡기) | `scripts/run_daily_batch.py`, `shared/batch_catchup.py` | 단위 + **종단(실DB·모의 서버)** |
| 신선도 점검·웹훅 알림 | `scripts/check_data_freshness.py` | 단위 + **종단** |
| 작업 등록(Windows) | `scripts/register_daily_batch_task.ps1`, `run_daily_batch.ps1`(인자 확장) | **정적 검토만(미실행)** |
| 작업 등록(Linux cron) | `scripts/crontab.example` | 정적 검토 |
| 시험 도구 | `scripts/mock_gov_data_server.py`(모의 공공데이터포털) | 종단 테스트에서 사용 |

## 2. 환경
임시 PostgreSQL 16(실제 마이그레이션 0001~0013), 모의 공공데이터 서버(실제와 같은 요청 파라미터·응답 봉투, `basDt`별 호출 통계, 미배포 날짜 지정), 로컬 웹훅 수신 서버, 실제 현재 시각(기대값은 같은 캘린더 로직으로 계산). 캘린더는 평일=거래일(마감 15:30) 단순 모델.

## 3. 종단 시험 결과 (`tests/integration/test_daily_batch_e2e.py`, 5건 모두 통과, 약 87초)
| # | 시나리오 | 기대 | 결과 |
|---|---|---|---|
| S-1 | 빈 DB에서 첫 실행 | 최근 6거래일을 **오래된 순**으로 수집·가공, 마지막 발행일 = 대상 거래일, 수집 이력이 오름차순 | ✅ |
| S-2 | 이미 최신인 상태에서 재실행 | 종료코드 0, "할 일이 없습니다", **공공데이터 호출 0건 증가·종목 마스터 갱신도 생략** | ✅ (결함 보완 후) |
| S-3 | 대상(최신) 거래일 미배포 | 종료코드 **2**, 직전 거래일까지 발행, 신선도 점검은 허용 지연 이내라 정상 → 공개 후 재실행 시 복구(종료 0, 발행일 = 대상) | ✅ |
| S-4 | 과거 거래일 하나가 영구 0건 | 3회 시도 후 **더는 호출하지 않고** 경고에 날짜 표시 | ✅ |
| S-5 | 발행일이 5거래일 뒤처짐 | 신선도 점검 종료코드 1 + 웹훅 1회(날짜 포함) → `--no-notify`면 알림 없음 → 웹훅이 죽어 있어도 종료코드 1 유지+경고 | ✅ |
단위: `tests/unit/test_batch_catchup.py` 9건(계획·오름차순·상한·결측·중단 규칙) 통과.

## 4. 발견한 결함과 조치
| # | 심각도 | 내용 | 발견 방법 | 조치·재검증 |
|---|---|---|---|---|
| B1 | Medium | 이미 최신인 날에도 매 실행이 **종목 마스터 갱신으로 공공데이터를 1회 호출**했다(런북·결과서의 "호출하지 않는다"와 불일치). 하루 2회 실행 시 일일 호출 한도를 불필요하게 소모 | 종단 S-2에서 호출 통계가 3→4로 증가 | 계획을 먼저 세워 할 일이 없으면 종목 마스터 갱신까지 건너뛰고 종료. S-2 재통과 |
| B2 | Medium | 직전 이력이 없어 가공이 항상 PARTIAL(검증 미통과)로 끝나는 과거 날짜(예: 처음 수집한 가장 오래된 날)가 **영구히 "미완료"로 남아 매 실행마다 재수집** | 종단 S-2 초기 실패 분석 | 과거 거래일의 실패·PARTIAL 3회 누적 시 재시도 중단+경고(최신일 제외). S-4로 검증 |
| B3 | Low(시험 준비) | 종목 마스터가 비어 있는 빈 DB에서 최신일이 미배포면 첫날 가공이 0건으로 실패 | 종단 S-3 초기 | 운영에서는 마스터가 이전 실행으로 이미 존재 → 시험이 마스터를 미리 채우도록 수정(코드 결함 아님, 기록) |
참고: 첫 배포(빈 DB) 직후 최신일이 미배포인 날에는 종목 마스터가 비어 가공이 실패할 수 있다 — 다음 실행(공개 후)에서 복구된다.

## 5. 한계·미검증
1. **Windows 작업 스케줄러 등록 스크립트 미실행.** PowerShell이 없는 환경이라 문법·동작을 실행으로 확인하지 못했다. 코드는 표준 cmdlet(`New-ScheduledTaskTrigger`, `Register-ScheduledTask`, `-StartWhenAvailable`, 재시작 3회/15분)만 사용하고 비ASCII 문자를 쓰지 않았다(PowerShell 5.1의 CP949 파싱 문제 회피). → §6 절차로 PC에서 확인.
2. 실제 공공데이터포털의 **정확한 공개 시각**과 **일일 호출 한도**는 미확인(서비스키 필요). 14:30·18:30은 가정이며 로그로 조정한다(§6-5).
3. 모의 서버는 정상 응답·0건 응답만 흉내 낸다. 실제 서버의 5xx·게이트웨이 오류(XML 응답) 재시도 동작은 기존 단위 테스트(`test_gov_data_client.py`)에 의존한다.
4. 캘린더는 평일=거래일 단순 모델이다. 실제 휴장일 캘린더(`scripts/load_calendar.py`)로의 동작은 기존 캘린더 단위·통합 테스트에 의존한다.
5. PC 절전·꺼짐 상태에서의 `StartWhenAvailable` 동작은 Windows에서만 확인 가능하다.

## 6. 사용자 PC에서 확인 절차(등록 후)
1. 등록: `powershell -ExecutionPolicy Bypass -File scripts\register_daily_batch_task.ps1` → 표에 두 작업이 `Ready`.
2. 확인: `Get-ScheduledTask StockScreenerKR-* | Get-ScheduledTaskInfo | Format-List TaskName,LastRunTime,LastTaskResult,NextRunTime`
3. 수동 시험 실행: `Start-ScheduledTask -TaskName StockScreenerKR-DailyBatch` → 1~2분 뒤 `logs\daily_batch.log` 끝에서 `exit=0`(또는 미배포면 `exit=2`) 확인. (`LastTaskResult`는 0 또는 2가 정상)
4. 누락 거래일(09-22·23·30, 10-01)이 채워졌는지: 로그의 "처리 대상 거래일(오래된 순)"과 종료 `[완료]`.
5. 14:30 실행이 `[대기]`(종료 2)로 끝나는 날이 잦으면 공개 시각이 더 늦은 것 → 등록 스크립트의 시각을 늦추고 재등록.
6. 이상 시: `logs\daily_batch.log`, `logs\freshness.log` 내용(앱키·서비스키 제외)을 알려 주세요.

## 7. 재현
```
# PostgreSQL을 띄우고 batch_worker·api_service 역할을 만든 뒤
TEST_PG_ADMIN_PSQL="psql -h <호스트> -p <포트> -U postgres" ALEMBIC_DATABASE_URL=… BATCH_DATABASE_URL=… PUBLIC_API_DATABASE_URL=… \
py -3.12 -m pytest tests/integration/test_daily_batch_e2e.py tests/unit/test_batch_catchup.py -q
py -3.12 scripts/mock_gov_data_server.py --port 9300   # 수동 시험용(실제 데이터 아님)
```
