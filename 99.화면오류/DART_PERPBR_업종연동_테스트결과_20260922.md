# DART 연동(PER/PBR·업종분류 실데이터) 내부테스트 결과서

- **테스트 일시**: 2026-09-22 17:13 ~ 20:50 KST (약 3시간 37분)
- **테스터**: Claude (AI 어시스턴트, 사용자 요청에 따른 실측 테스트)
- **대상 기능**: 조건 스크리닝 PER/PBR 필터·정렬, 종목상세 PER/PBR 백분위, 홈 화면 "업종별 거래대금 상위"
- **테스트 목적**: 공공데이터포털이 PER/PBR을 제공하지 않는 문제(DEF-005)를 DART(전자공시시스템) OpenAPI로 대체 해결하는 신규 연동을, 실제 인증키·실제 상장기업 데이터로 전 과정 검증
- **선행 조사**: KRX Open API(무료, 8개 API 전수 실측) — PER/PBR·업종분류 없음 확인. KRX Data Marketplace 해당 상품 — "데이터상품" 메뉴의 **유료 구매** 항목으로 확인(사용자 실측 스크린샷). 두 경로 모두 배제 후 DART로 전환.

---

## 1. 구현 범위

| 구분 | 파일 | 내용 |
|---|---|---|
| DB 마이그레이션 | `db/alembic/versions/0010_create_raw_internal_corp_financials.py` | `raw_internal.raw_corp_financials` 신설(당기순이익/자본총계 원문), batch_worker 전용 권한(api_service 무권한, 기존 보안 패턴 동일) |
| DART API 클라이언트 | `services/ingestion_batch/dart_client.py` (신규) | 고유번호 매핑(`corpCode.xml`), 기업개황(업종코드), 재무제표(당기순이익/자본총계) 조회. 재시도·요청 페이싱 포함 |
| 업종코드 조회 | `services/ingestion_batch/ksic_lookup.py` (신규) + `data/reference/ksic_codes.csv` (신규, FinanceData/KSIC 공개 코드표) | DART 업종코드 -> 한글 업종명 변환 |
| DB 모델/저장소 | `services/ingestion_batch/models.py`, `repository.py` | `RawCorpFinancials` 모델, `upsert_corp_financials`/`upsert_stock_sector`/`compute_per_pbr`/`apply_dart_valuation` 추가 |
| 배치 연동 | `services/ingestion_batch/run_ingestion.py` | 기존 시가총액(`market_cap`)과 DART 재무 원문을 조합해 PER/PBR 계산·반영하는 단계 추가(보조 단계 — 실패해도 OHLCV 성공에 영향 없음) |
| 수집 스크립트 | `scripts/enrich_corp_financials.py` (신규) | 업종·재무원문 수집 오케스트레이션. 200건마다 중간 커밋, 분기 재수집 정책 자동 판단(`resolve_target_report`) |
| 환경설정 | `.env`, `.env.example`, `services/ingestion_batch/core/config.py` | `DART_API_KEY` 추가 |
| 보안 | `.gitignore` | `99.화면오류/*.png` 추가(인증키가 찍힌 화면 캡처가 실수로 커밋되는 것 방지) |
| 테스트 | `tests/unit/test_dart_client.py`, `test_ksic_lookup.py`, `test_enrich_corp_financials.py`, `test_ingestion_repository.py` (전부 신규) | 아래 2절 참조 |

---

## 2. 단위 테스트 결과

```
python -m pytest tests/unit -q
213 passed, 2 warnings in 3.82s
```

기존 184건(이전 세션 기준) + 이번 기능 신규 29건(dart_client 15, ksic_lookup 5, enrich_corp_financials 6, ingestion_repository 4 — 도중 발견한 버그 회귀테스트 포함) 전부 통과. `ruff check` 전 파일 통과.

DB에 실제로 쓰는 로직(`ON CONFLICT` 사용)은 SQLite로 대체 검증이 불가능해(이 프로젝트 기존 원칙, `test_run_ingestion.py`/`test_seed_stock_master.py`와 동일) 3절의 로컬 Docker PostgreSQL 실측으로 별도 검증했다.

---

## 3. 실측 검증 (로컬 Docker PostgreSQL + 실제 DART/공공데이터포털 API)

### 3-1. 마이그레이션 적용
`alembic upgrade head` 정상 적용(0009 → 0010). `raw_internal.raw_corp_financials` 테이블·권한(batch_worker: SELECT/INSERT/UPDATE만, api_service: 무권한) 직접 조회로 확인.

### 3-2. 전체 종목 백필 (최종 실행 기준)
```
active_stocks: 2760
corp_code_matched: 2646  (95.9%)
sector_updated: 2642     (95.7%)
financials_fetched: 2614 (94.7%)
skipped_no_corp_code: 114 (4.1%)
skipped_no_financials: 32 (1.2%)
errors: 0
```
대상 보고서: 2025년 사업보고서(연간, reprt_code=11011) — 4절 "재수집 주기" 참조.

### 3-3. 실데이터 정합성 확인 (삼성전자, corp_code=00126380)
- `induty_code`="264" → `data/reference/ksic_codes.csv` 대조 결과 "264: 통신 및 방송 장비 제조업"과 **정확히 일치** (코드표 대조로 검증, 추정 아님)
- 당기순이익(지배지분): 44,260,956,000,000원
- 자본총계(지배지분): 424,313,255,000,000원

### 3-4. 업종 분포 실측 (반영 후 실제 DB 집계, 상위 10)
의약품 제조업(94), 자동차 부품 제조업(91), 금융지주회사(75), 소프트웨어 개발 및 공급업(60), 특수 목적용 기계 제조업(54), 시스템 소프트웨어 개발 및 공급업(50), 그외 기타 금융지원 서비스업(47), 기초 의약물질 및 생물학적 제제 제조업(46), 응용소프트웨어 개발 및 공급업(45), 의학 및 약학 연구개발업(44) — 실제 한국 상장기업 산업 구성과 부합하는 분포.

### 3-5. 파이프라인 end-to-end 실행 (`--trade-date 2026-09-21`, 최근 확정 거래일)
```
$ python -m services.ingestion_batch.run_ingestion --trade-date 2026-09-21
[정보] PER/PBR 2614건 반영 (재무 원문 없어 건너뜀 253건)
[완료] status=SUCCESS trade_date=2026-09-21

$ python -m services.derivation_batch.run_derivation --trade-date 2026-09-21
[완료] status=SUCCESS trade_date=2026-09-21
```

### 3-6. 실 API(4001) 응답 검증
- `GET /api/v1/screen?market=ALL&per_max=15&sort_by=per&sort_dir=asc&page_size=5`
  → `total_count: 880`, 1위 한창(005110) PER 백분위 0.1%, 2위 효성화학(298000) 0.1% 등 — 실제 저PER 종목이 실제로 상위에 정렬됨
- `GET /api/v1/market-summary?market=ALL`
  → 업종별 거래대금 1위 "통신 및 방송 장비 제조업"(6.28조원, 삼성전자 분류), 2위 "다이오드·트랜지스터 등 반도체 제조업"(5.46조원, SK하이닉스 등 분류) — 실제 시장에서 거래대금 최상위인 두 종목의 실제 업종과 정확히 일치

### 3-7. 서버 상태
프론트엔드(4000)·백엔드(4001)·DB 전부 계속 실행 중인 상태로 검증(최종 확인: 홈 200 / 스크리닝 200 / 백엔드 API 200).

---

## 4. 개발 중 발견·수정한 결함 (전부 실데이터로 발견, 짐작 아님)

| # | 결함 | 발견 경위 | 조치 |
|---|---|---|---|
| 1 | **당기순이익 sj_div="IS" 누락 버그**: 손익계산서(IS)와 포괄손익계산서(CIS)를 하나로 합쳐 제출하는 회사(예: 하이트진로)는 당기순이익이 CIS에만 있어, IS만 찾으면 전부 None으로 빠짐 | `--limit 15` 실 데이터 검증 중 발견(하이트진로 등 다수 종목 net_income=None) | sj_div를 ("IS","CIS") 둘 다 찾도록 수정, 두 곳에 동시 존재해 충돌하는 사례 없음을 실측 확인 후 반영 |
| 2 | **DART 서버 측 IP 일시 차단**: 요청 간 간격 없이 3.6MB 매핑 파일 반복 다운로드 + 수백 건 연속 호출 시, 공식 문서에 없는 비공식 속도제한으로 추정되는 **연결 리셋**(opendart.fss.or.kr 홈페이지조차 응답 없음) 발생 | 전체 백필 1차 시도 중 재현, curl 직접 호출로 코드 문제 아님을 별도 확인 | `DartClient`에 요청 간 최소 0.5초 페이싱 추가. 약 50분 대기 후 자연 해제 확인 |
| 3 | **분기/반기 재무제표 필드 오독 위험**: `thstrm_amount`가 분기/반기보고서에서는 "당기 3개월 단독" 값이고, 연초 누적은 별도 필드 `thstrm_add_amount`에 있음(DART 개발가이드 원문 대조로 확인) | 분기 재수집 기능 구현 전 사전 검증(삼성전자 2026 반기보고서 실호출) | 사업보고서(연간)는 `thstrm_amount` 그대로, 분기/반기는 `thstrm_add_amount`(누적)을 12개월 기준으로 연환산해 저장하도록 구현 |

### 4-1. 운영 중 발생한 실수 (투명하게 기록)
전체 백필 1차 실행 중, 프로세스가 실제로는 정상 동작 중이었는데(네트워크 연결이 순간적으로 안 보인다는 불완전한 판단 근거로) **제가 프로세스를 임의로 강제 종료**했습니다. 당시 코드는 전체 루프가 끝난 뒤 한 번만 커밋하는 구조였어서, 그동안 처리한 데이터가 전부 유실됐습니다. 재발 방지로 **200건마다 중간 커밋**하도록 구조를 바꿨고, 이후로는 실행 중인 프로세스를 임의로 건드리지 않고 DB 행 수로만 진행 상황을 확인하는 방식으로 전환했습니다.

---

## 5. 알려진 제한사항 (지어내지 않고 있는 그대로 기록)

1. **매핑 실패 114건(4.1%)**: 우선주 등 DART에 별도 고유번호가 없는 종목 클래스로 추정(개별 원인은 종목별로 전수 조사하지 않음).
2. **재무데이터 없음 32건(1.2%)**: 신규 상장 등으로 아직 사업보고서가 없는 경우로 추정.
3. **연환산 근사치**: 분기/반기 데이터를 12개월로 연환산하는 로직은 구현·단위테스트 완료했으나, 이번 백필 자체는 연간(2025) 데이터를 사용했으므로 **연환산 실제 적용 사례는 아직 실거래 데이터로 검증하지 않았다** — 다음 분기 재수집(2026-11-20경, 3분기보고서) 때 최초로 실사용되며, 그때 다시 한번 실측 검증이 필요하다.
4. **오늘 사용한 데이터는 2025년 사업보고서(연간) 기준**이다. 사용자 승인에 따라 2026년 반기보고서(더 최신)로의 재백필은 보류했다 — 다음 재수집 체크포인트(11/20, 3분기보고서)에 자동으로 최신화된다.
5. **브라우저 인터랙티브 클릭 테스트는 이번에도 수행하지 못했다**(Chrome 확장 프로그램 미연결, 기존 제약과 동일). API 직접 호출 + DB 직접 조회로 대체 검증했다.

---

## 6. 재수집 주기 정책 (사용자 승인 완료, 2026-09-22)

자본시장법상 정기보고서 법정 제출기한(사업보고서 90일/분기·반기 45일)에 근거해 **연 4회** 재실행을 권장하며, `scripts/enrich_corp_financials.py`의 `resolve_target_report()`가 오늘 날짜 기준 최신 보고서를 자동 판단한다.

| 권장 재수집 시점 | 대상 보고서 | 법정 마감일 |
|---|---|---|
| 매년 4월 5일경 | 사업보고서(연간, 11011) | 3/31 |
| 매년 5월 20일경 | 1분기보고서(11013) | 5/15 |
| 매년 8월 20일경 | 반기보고서(11012) | 8/14 |
| 매년 11월 20일경 | 3분기보고서(11014) | 11/14 |

이 스케줄은 **일일 배치(`run_daily_batch.py`)에는 포함하지 않았다** — 재무제표가 분기 단위라 매일 돌릴 이유가 없고, DART 서버 부담(4절 결함#2)도 고려했다. 위 4개 시점에 `python scripts/enrich_corp_financials.py`를 수동(또는 향후 별도 스케줄러 등록 시 자동)으로 재실행하면 된다.

---

## 7. 결론

PER/PBR·업종분류 실데이터 연동을 실제 인증키·실제 2,760개 상장종목 데이터로 전 과정(수집 → DB 반영 → 파생 계산 → 실 API 응답) 검증 완료. 단위테스트 213건 전부 통과, 실측 중 발견한 결함 3건 전부 수정·재검증 완료. 프론트엔드·백엔드·DB 서버는 검증 작업 종료 시점까지 계속 정상 실행 상태로 유지했다.
