# 내부 테스트 결과서 — 장중 재계산 백엔드 (DEC-089·090·091)

- 작성일: 2026-10-06 / 대상: 로컬 모드 관리자 전용 `GET /api/v1/local/screen`, `GET /api/v1/local/screen/pattern`, 일봉 보충, 우선 순환 시세
- 근거 문서: `docs/stock-detail/10-intraday-rescreen-contract.md`(§0~§7), `docs/harness/decisions.md` DEC-089·090·091
- 환경: Python 3.12 가상환경, PostgreSQL 16 임시 클러스터(포트 5544, 시험마다 임시 DB 생성·삭제, 개발 DB 미접속), 읽기 전용 `api_service` 계정으로 실제 SQL·권한 검증, 모의 증권사 서버(`scripts/mock_kis_server.py`, HTTP). **실제 증권사에는 접속하지 않았다.**
- 판정 방식: 기존 `/screen`·`/screen/pattern` 엔드포인트 함수를 **그대로 호출**하고 저장소만 SQL 가상 테이블(`jsonb_to_recordset`)로 바꿔 끼운다. 필터·정렬·패턴 조건식을 복제하지 않았다.

## 1. 변경 내용
| # | 내용 | 파일 |
|---|---|---|
| 1 | 증권사 일봉 조회(`inquire-daily-price`, `FHKST01010400`)·정규화(`normalize_daily_price`)·모의 서버 엔드포인트 | `intraday/kis_client.py`, `intraday/normalize.py`, `scripts/mock_kis_server.py` |
| 2 | 시세 폴러 **우선 순환**(`set_priority`·`priority_codes`·`priority_cycle_seconds`), 시세 갱신 시 더 오래된 값이 새 값을 덮지 않음, `/local/market/quotes?priority=1` | `realtime/market.py`, `api/local_market.py` |
| 3 | 재계산 행 만들기(순수 함수, 배치와 같은 계산 함수 재사용) | `live_screen/rows.py` |
| 4 | **일봉 보충**(교차검증·재시도·진행률) | `live_screen/fill.py` |
| 5 | 이력 캐시·스냅샷 저장소(최근 5개)·서비스(최소 계산 간격 재사용, 단일 비행) | `live_screen/{history,snapshot,service}.py` |
| 6 | SQL 가상 테이블(값은 바인드 파라미터 1개로만 전달) | `live_screen/virtual.py` |
| 7 | 저장소에 선택 인자 `source`와 `matching_codes` 추가(기본 동작 불변) | `db/screen_repository.py`, `db/pattern_repository.py` |
| 8 | API 2개(`basis`·`meta.live`·편입 이탈·우선 순환 등록), 오류 `details`(선택) | `api/local_screen.py`, `schemas/live_screen.py`, `errors.py`, `main.py` |
| 9 | 사용자 PC 확인 도구 | `scripts/kis_daily_price_smoke_test.py` |

## 2. 시험 결과 요약
| 구분 | 파일 | 개수 | 결과 |
|---|---|---|---|
| 단위: 우선 순환 | `tests/unit/test_market_priority.py` | 11 | 통과 |
| 단위: 증권사 일봉 클라이언트·정규화·모의 서버(HTTP) | `tests/unit/test_kis_daily_price.py` | 21 | 통과 |
| 단위: 확인 도구 | `tests/unit/test_kis_daily_price_smoke_test.py` | 6 | 통과 |
| 단위: 재계산 순수 함수 | `tests/unit/test_live_rows.py` | 23 | 통과 |
| 단위: 보충·스냅샷·서비스 | `tests/unit/test_live_fill_snapshot_service.py` | 18 | 통과 |
| 통합(임시 DB·실제 SQL·실제 앱) | `tests/integration/test_live_screen_db.py` | 19 | 통과 |
| 종단(실제 uvicorn + 모의 증권사 HTTP + 실제 폴러·보충) | `tests/integration/test_live_screen_stack_db.py` | 3 | 통과 |
| **새 시험 합계** | | **101** | **전부 통과** |
| 기존 회귀 포함 전체 | `pytest tests` | {FULL} | {FULLRESULT} |
| 정적 검사 | `ruff check services scripts tests` | — | 통과(오류 0) |
| 기준선(작업 전) | `pytest tests` | 1282 passed, 63 skipped | — |

## 3. 시험 케이스 상세
### 3-1. 동치 — 가상 테이블 = 기존 테이블 (통합, 실제 PostgreSQL)
| 케이스 | 기대 | 결과 |
|---|---|---|
| 조건 스크리닝: 필터 11종 조합 × 정렬 7종 × 방향 2 = 154가지 + 페이지 경계 | 기존 저장소와 `search` 결과(항목·순서·총건수) 완전 동일, `matching_codes` 동일 | 통과 |
| 패턴 스크리닝: 필수 조건 9조합 × 정렬 4종 × 방향 2 × 시장 3 = 216가지 | `search`(조건 충족 여부·`ma60_stage`·지표 포함) 완전 동일 | 통과 |
| 패턴 `readiness`(ALL·KOSPI)·단일 종목 조회 | 동일 | 통과 |
| NULL·소수 정밀도(Decimal)·빈 목록 | NULL 보존, Decimal 값 동일, 빈 목록이면 0건 | 통과 |
| 값에 SQL 조각이 든 경우 | 바인드 파라미터라 구조 불변: 길이 제한에서 거부될 뿐 테이블 영향 없음 | 통과 |
| 기존 `/screen` 골든 응답(`golden_screen_before_pattern.json`)·동결 해시 시험(A35) | 기존 응답 불변(해시는 DEC-091 ①로 1회 갱신) | 통과 |

### 3-2. 재계산 정확성 — 골든
확정일(2026-09-30)의 일봉을 "오늘 진행 봉(시세)"으로 넣고 9/29까지를 이력으로 주면, **재계산 열 전부(`return_pct`, 이동평균 이격도 2종, 거래량 이상치, `volume_raw`, 패턴 지표 10개 + 상태)와 등락률 순위가 배치가 만든 9/30 행과 허용오차 0으로 일치**한다. 발행 행의 재계산 열을 일부러 엉뚱한 값으로 바꿔 둔 뒤 비교해 "실제로 덮어썼음"을 증명했다. 일봉 고정 열(PER·PBR·시총·백분위)은 그대로임을 확인(이력이 짧은 픽스처 종목 T00008의 `INSUFFICIENT_HISTORY`도 일치). 통과.

### 3-3. 재계산 규칙 (단위, DB 없음)
| 케이스 | 결과 |
|---|---|
| 시세 사용 가능 판정: 없음·가격 0·음수·거래량 음수·신선도 경계(300초 / 300.1초) | 통과 |
| 뒤처지지 않음 + 시세 없음 → 발행 행 그대로(입력 불변, 복사본) | 통과 |
| 시세 있음 → 등락률·거래량 재계산, 일봉 고정 열 유지, `basis=live` | 통과 |
| 배치 계산 함수와 정확히 동일(종가·거래량 조합) | 통과 |
| 이력 부족(30행) → `INSUFFICIENT_HISTORY`, 단절(+100%) → `SUSPECT_PRICE_JUMP`(예외 없음) | 통과 |
| 오래된 시세 무시, 오늘이 비거래일·마감 뒤(E=오늘) 시세 무시 | 통과 |
| 등락률 순위 정책: 커버율 100%·90%(live)·80%(daily, 발행 값 유지) | 통과 |
| 뒤처짐(P<E): E까지 이력으로 재계산(발행 P 값이 아님), E 일봉이 없는 종목은 제외 목록으로 보고, 시세가 있으면 E 위에 오늘 행 | 통과 |
| 뒤처짐 시 순위는 E 기준 등락률로 다시 계산 | 통과 |
| 중복 날짜·미래 날짜 이력은 영향 없음, 빈 입력, meta 필드(재계산/일봉 고정 열 목록, 거래량 부분값 표시) | 통과 |

### 3-4. 일봉 보충(DEC-090)
| 케이스 | 결과 |
|---|---|
| 교차검증: OK / P 행 없음 / 종가 불일치 / 필요한 날짜 누락 / 여러 날짜 중 하나 누락 | 통과 |
| 보충기: 25종목 전부 성공, 혼합(성공·불일치·누락·일시 실패 후 성공·재시도 3회 소진 실패) 집계 정확, 같은 (P,E)는 다시 조회하지 않음, 새 (P,E)는 새로 시작, 빈 입력은 즉시 ready, 종료 시 작업 취소(거짓 ready 없음) | 통과 |
| 서비스: 보충 진행 90% 미만이면 503 `LIVE_BASE_FILLING`(`details` 진행률), 완료 후 응답(`filled`·`mismatched`·`excluded`·`pending` 정확), 5거래일 초과 409 `LIVE_BASE_STALE`(이력·보충 호출 없음), 정확히 5거래일은 보충 진행 | 통과 |
| API(통합): 처음 503 → 게이트를 열면 보충 완료 → 200. 종가 불일치·날짜 누락·조회 오류 종목은 결과에서 빠지고 meta에 수로 표시, 나머지는 `basis` 정확 | 통과 |
| API(통합): 보충 뒤 시세 없는 종목의 값 = E 기준(+1.0%), 발행 P 값 아님 | 통과 |

### 3-5. API 동작
| 케이스 | 결과 |
|---|---|
| 마감 뒤: `/local/screen` = `/screen`과 항목·순서·`matched_metrics`·총건수 동일(파라미터 4조합), 모든 항목 `basis=daily`, `meta.live.base_fill.state=none`, `Cache-Control: no-store` | 통과 |
| 마감 뒤: `/local/screen/pattern` = `/screen/pattern`(4조합, `basis` 제거 시 완전 동일) | 통과 |
| 장중 시세 8/10종목: 8개 `live`·2개 `daily`, 커버율 80% → 순위 daily, 재계산 등락률 정확(+3.0%) | 통과 |
| 응답에 원본 시세 필드(`fetched_at` 등)·증권사 응답 필드 없음 | 통과 |
| 보이는 종목이 우선 순환에 등록되고 `meta.live.priority_codes`와 일치 | 통과 |
| 시세 없음 → 503 `LIVE_QUOTES_NOT_READY`(장 마감 뒤에는 요구하지 않음) | 통과 |
| 5분보다 오래된 시세는 없는 것으로 처리 | 통과 |
| 스냅샷: 최소 간격 안 재사용(계산 1번), 동시 요청 3개도 계산 1번, 간격 뒤 새 계산, 시세가 크게 바뀌어도 고정 스냅샷은 같은 결과(페이지 이동), 모르는 id 410 `SNAPSHOT_EXPIRED`, 형식 오류 400/422, 보관 5개(오래된 id는 410), 발행일이 같으면 이력 재적재 없음 | 통과 |
| 편입·이탈: 첫 계산 `null`, 2·3번째 계산에서 `entered`·`left` 정확, 다른 조건은 `null` | 통과 |
| 접근 통제: 로컬 모드 꺼짐 → 404(모든 경로), 앱키 없음 → 503 `LOCAL_INTRADAY_NOT_CONFIGURED` | 통과 |
| `snapshot_id` 입력 검증(32자리 16진수만) | 통과 |

### 3-6. 우선 순환 시세
| 케이스 | 결과 |
|---|---|
| 상한 200·중복·미지 코드 제거·순서 유지·빈 목록 해제 | 통과 |
| TTL 30초 만료 자동 해제, 비양수 TTL은 즉시 만료, 종목 목록 교체 시 빠진 종목 제외 | 통과 |
| 30종목 묶음 호출(65종목 → 30·30·5), 우선 종목의 시세만 갱신 | 통과 |
| 호출 간격 ≥ `min_interval/priority_share`(0.4초) — 합산 한도의 50% 이내 | 통과 |
| 실패 시 공유 백오프(1초)를 지키고 다음 묶음은 계속 | 통과 |
| 시작·정지·재시작, 정지 뒤 호출 없음, 우선 종목이 없으면 증권사 호출 0건 | 통과 |
| 기존 폴러 시험 91건(`test_market_snapshot`·`test_local_market_api`) 불변 | 통과 |

### 3-7. 종단(실제 서버·모의 증권사 HTTP)
- 장중(금 10:00, P=9/30, E=10/1): 실제 서버가 모의 증권사에서 일봉을 채우고(`filled=10`, `gap_days=1`) 전 종목 시세를 모아 `basis=live` 10건, `return_rank_policy=live`, 우선 순환 호출 증가(`priority_calls_total>0`, `priority_codes=10`), 패턴 화면·`/quotes?priority=1` 동작, **서버 종료 시 보충 작업 정리**(`_service is None`). 통과.
- 마감 뒤: 보충·시세 없이 `daily`로 응답. 통과.
- 증권사 일봉 종가 불일치 종목: 결과에서 제외되고 `mismatched=1`·`excluded=1`·`filled=9`. 통과.

### 3-8. 성능(2,800종목 × 100거래일 합성 데이터, 임시 PostgreSQL, 이 컨테이너 1회 측정)
| 항목 | 측정값 | 비고 |
|---|---|---|
| 발행 행·달력 읽기 | 109 ms | 계산마다 |
| 이력 적재(250종목씩 12번) | 2,162 ms | **발행일이 바뀔 때 1회**(캐시) |
| 재계산(2,800종목, 파이썬) | 2,010 ms | 계산마다. 최소 계산 간격 5초 안에서는 재사용 |
| 가상 테이블 JSON 만들기 / 크기 | 48 ms / 2,279 KB | 스냅샷마다 1회 |
| 조건 스크리닝 쿼리(200건 페이지) | 134 ms | 요청마다 |
| 편입·이탈용 코드 목록 쿼리 | 58 ms | 요청마다 |
| 패턴 스크리닝 쿼리 / readiness | 121 ms / 62 ms | 요청마다 |
- 요청 타임아웃: 로컬 경로(`/api/v1/local/`)는 30초 허용이라 첫 계산(약 4~5초)도 통과한다. 쿼리 문장 제한(기본 3초)은 이력을 250종목씩 나눠 읽어 넘지 않게 했다.
- CPU: 자동 갱신 10초 간격이면 재계산 약 2초 = 한 코어의 약 20%(내 PC 한 명 사용 기준).

## 4. 발견·수정한 사항
| # | 발견 | 조치 |
|---|---|---|
| 1 | 시세 폴러에 우선 순환 작업을 추가하자 기존 시험 `test_off_hours_runs_slowly_after_first_cycle`가 실패(우선 작업의 대기가 시험용 가짜 시계를 진행시킴) | 우선 작업의 유휴 대기를 주입 sleep이 아니라 이벤트로 바꿈. 기존 91건 통과 |
| 2 | 기존 동결 해시 시험(A35)이 `screen_repository.py` 변경을 거부 | 추가형 변경임을 골든 응답 비교로 보증하고 해시를 1회 갱신(DEC-091 ①, 선례 DEC-046) |
| 3 | 발행 일봉이 뒤처졌고 시세도 없을 때 `LIVE_QUOTES_NOT_READY`가 `LIVE_BASE_FILLING`보다 먼저 나와 보충이 시작되지 않을 수 있었음(종단 시험에서 발견) | 보충을 먼저 시작·보고하고 그다음 시세 준비를 확인하도록 순서 변경 |
| 4 | 실제 DB는 이력 100행이 아닐 수 있음: 픽스처에서 이력이 짧은 종목(50행)이 있어 "항상 100행" 가정이 틀림 | 시험 기대를 종목별 실제 길이로 수정, 재계산은 `INSUFFICIENT_HISTORY`로 정상 처리 |
| 5 | 네트워크 DB에서 이력 한 문장(28만 행)이 문장 제한(3초)을 넘을 위험 | 250종목씩 나눠 읽기 |

## 5. 확인하지 못한 것·남은 위험
| # | 내용 | 대응 |
|---|---|---|
| 1 | **실제 증권사 일봉 응답**(필드 이름·수정주가 기준·호출 한도·지연)은 앱키가 없어 확인하지 못했다. 필드 이름은 공식 샘플 기준이다 | 사용자가 장중에 `scripts/kis_daily_price_smoke_test.py` 실행(종가 일치 비교 포함). 일치하지 않으면 해당 종목은 안전하게 결과에서 제외된다 |
| 2 | 실제 증권사 호출 한도에서 전 종목 보충에 걸리는 시간(모의 서버로는 호출 간격만 검증) | 호출 간격 공유·4개 작업자·재시도 구현. 실제 시간은 PC에서 관찰 |
| 3 | 거래량은 장중 누적 부분값(시간대 보정 없음), PER·PBR·시총 일봉 고정 | 화면 경고 상시 표시(프런트 결과서) |
| 4 | 정규장 전(08:00~09:00) 시간외 시세로 `live` 계산 가능 — 값이 부분적 | 가이드에 명시. 2단계에서 장 시간 제한 검토 |
| 5 | 보충 결과는 메모리 전용이라 서버 재시작 시 다시 수집(몇 분) | 의도된 설계(DB 불변). 디스크 캐시는 후보로 기록 |
| 6 | 달력은 평일 단순 모델로 시험(휴장일 규칙은 기존 달력 서비스 시험이 보증) | — |
| 7 | 브라우저 화면 연동은 프런트 결과서(`2026-10-06-intraday-rescreen-screen-test-result.md`)와 합친 종단에서 확인 | 합친 뒤 종단 시험 결과를 이 문서 §6에 추가 |

## 6. 합친 뒤 종단(프런트 + 백엔드)
(합치는 단계에서 추가)
