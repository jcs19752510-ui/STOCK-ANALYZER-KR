# 일일 배치 운영 Runbook (DEC-047, 2026-10-02)

## 1. 구성
| 작업 | 스크립트 | 주기(KST) | 역할 |
|---|---|---|---|
| 일일 배치 | `scripts/run_daily_batch.py` | 매일 14:30, 18:30 | 종목 마스터 갱신 → 수집(Ingestion) → 가공(Derivation). 빠진 거래일 따라잡기 |
| 신선도 점검 | `scripts/check_data_freshness.py` | 매일 09:10 | 읽기 전용. 발행 거래일이 기대보다 1거래일 넘게 늦으면 종료코드 1 + 웹훅 알림 |

- 하루 두 번 실행해도 안전하다(이미 최신이면 API를 호출하지 않고 종료). 14:30은 +1영업일 공개 데이터가 올라온 뒤를 노린 시각이고, 18:30은 늦게 올라온 경우의 재시도다. **정확한 공개 시각은 아직 실측하지 못했다**(공공데이터포털 문서 미확정, `run_ingestion.py` docstring) — 로그에서 14:30 실행이 "아직 배포되지 않았을 수 있습니다"로 끝나는 일이 잦으면 시각을 늦춘다.
- 따라잡기: 최근 10거래일(`DAILY_BATCH_CATCHUP_DAYS`) 중 가공이 검증까지 끝나지 않은 날을 오래된 순으로 채운다. 며칠 실패하거나 PC가 꺼져 있었어도 다음 실행이 스스로 복구한다. 더 이전 날짜가 막히면 그 뒤로 넘어가지 않고 중단한다.
- 종료코드: `0` 정상/할 일 없음, `2` 대상 거래일 데이터 미배포(다음 실행에서 재시도), 그 외 실패.

## 2. 설치
- **Windows(현재 개발 PC)**: `powershell -ExecutionPolicy Bypass -File scripts\register_daily_batch_task.ps1` (제거: `-Remove`). 같은 이름 작업은 교체되며, PC가 꺼져 있었으면 켜진 뒤 실행(StartWhenAvailable)한다. **기존 07:00 작업은 이 스크립트가 같은 이름(`StockScreenerKR-DailyBatch`)으로 교체한다.**
- **Linux/컨테이너**: `scripts/crontab.example` 참조.
- `.env`에 `BATCH_DATABASE_URL`, `GOV_DATA_PORTAL_SERVICE_KEY`, `DART_API_KEY`가 있어야 하고, 알림을 받으려면 `DATA_FRESHNESS_WEBHOOK_URL`(Slack/Discord 호환)을 추가한다.

## 3. 점검·장애 대응
1. `logs/daily_batch.log`(배치), `logs/freshness.log`(신선도) 확인. 헤더/푸터에 종료코드가 남는다.
2. 수동 실행: `py -3.12 scripts/run_daily_batch.py` (한 날짜만: `py -3.12 -m services.ingestion_batch.run_ingestion --trade-date YYYY-MM-DD` 후 `run_derivation`).
3. `ModuleNotFoundError` → 스케줄러가 `py -3.12`를 쓰는지 확인(DEC-036). 캘린더 오류 → `scripts/load_calendar.py`로 휴장일 캘린더 갱신.
4. 수집이 3일 연속 실패하면 서킷브레이커가 격상한다(설계 §5-4).

## 4. 연간 작업
- **실적 재수집(R6)**: 매년 4월 5일경 이후 사업보고서가 공시되면 `py -3.12 scripts/enrich_earnings.py` 실행(약 30분, 개발 DB 기준 2,600여 종목). 금융회사 등 매출 계정이 없는 종목은 "-"로 표시된다.
- **휴장일 캘린더**: 매년 말 다음 연도 캘린더를 `scripts/load_calendar.py`로 적재한다.
