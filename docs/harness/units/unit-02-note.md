# UNIT-02 구현 노트 — 데이터 수집/적재 파이프라인 (Ingestion Batch)

- 작성 에이전트: 05-unit-developer
- 작성일: 2026-09-15
- 포함 REQ: REQ-011 (데이터 소스 연동, +1영업일 지연 데이터 처리)
- 입력: `docs/harness/03-system-design.md`(v4, PASS) §1-2/§1-3(Ingestion Batch), §2-2(약관/호출한도), §3-2(`raw_internal.raw_ohlcv`/`raw_fundamentals`, `public_serving.batch_run`), §4-3(데이터 가공 원칙), §5-4(재시도/서킷브레이커), `docs/harness/04-ux-design.md`(v3, PASS), `docs/harness/02-planning.md`(v3) §9 UNIT-02
- 의존성: UNIT-01(거래일 판정, `shared/calendar_service/get_last_trading_day()`) — 재사용, 코드 변경 없음

---

## 0. 실제 API 키 없이 진행한 것에 대한 사실 확인 (필독)

이 프로젝트는 공공데이터포털 "금융위원회_주식시세정보"(`GetStockSecuritiesInfoService`,
오퍼레이션 `getStockPriceInfo`) API의 **실제 서비스키를 보유하지 않은 상태**로 진행됐다.
코디네이터 지시에 따라 다음 원칙을 지켰다:

1. **정상 응답(실제 시세 데이터) 파싱 로직은 data.go.kr 공개 문서에 기재된 요청
   파라미터/응답 필드명(`serviceKey`, `basDt`, `srtnCd`, `mkp`, `hipr`, `lopr`,
   `clpr`, `trqu`, `trPrc` 등)만 근거로 구현했다.** 상상으로 필드를 지어내지 않았다.
   다만 이 형태를 **실제 성공 응답으로 검증하지는 못했다** — 실 키 발급 후 반드시
   재검증이 필요하다(아래 §2 "확인 필요" 목록 참조).
2. **게이트웨이 레벨 오류 응답은 실제로 실측했다.** 서비스키 없이 실 엔드포인트
   (`https://apis.data.go.kr/1160100/service/GetStockSecuritiesInfoService/getStockPriceInfo`)를
   직접 호출해(2026-09-15) 다음을 확인했다:
   - `resultType` 생략/`xml` 지정 시: `HTTP 403` + XML 본문
     (`<OpenAPI_ServiceResponse><cmmMsgHeader><errMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR</errMsg>
     <returnAuthMsg>등록되지 않은 서비스키</returnAuthMsg><returnReasonCode>30</returnReasonCode>
     </cmmMsgHeader></OpenAPI_ServiceResponse>`).
   - `resultType=json` 지정 시에도 정상 응답 봉투(`response.header`)가 아니라
     `HTTP 403` + `{"OpenAPI_ServiceResponse": {"cmmMsgHeader": {...}}}` 형태의
     **JSON**으로 내려온다(같은 필드명, XML이 아님). 이는 "resultType=json이면
     오류도 JSON 정상 봉투로 온다"는 최초 가정이 틀렸음을 실측으로 발견해
     클라이언트 코드를 수정한 사례다(아래 §1 참조).
   - 이 실측 결과는 `services/ingestion_batch/gov_data_client.py` 모듈 docstring과
     `tests/unit/test_gov_data_client.py`의 관련 테스트 주석에 그대로 남겨뒀다.
3. **PER/PBR은 이 오퍼레이션이 제공하는지 확인하지 못했다. 시가총액(`mrktTotAmt`)은
   제공됨이 확인됐다.** *(2026-09-15 정정 — 6단계 DEF-005(Low) 지적 반영. 최초
   버전은 "PER/PBR/시가총액을 전부 확인하지 못했다"고 서술했으나 부정확했다:
   `mrktTotAmt`(시가총액)는 `getStockPriceInfo` 응답 필드로 문서상 제공이 확인되며,
   미확인/미제공인 것은 PER/PBR뿐이다. 코드 결함이 아니라 문서 서술 정확도
   문제였다.)*
   - PER/PBR은 이 오퍼레이션에 포함되는지, 별도 오퍼레이션/서비스가 필요한지
     실 키 없이 공식 스펙 원문을 전량 대조하지 못해 결론 내릴 수 없었다.
   - **시가총액이 제공됨을 확인했음에도, 이번 유닛은 `raw_fundamentals`(PER/PBR·
     시가총액 전부) 적재 로직 자체를 범위에서 제외했다.** 이유: (a) `raw_fundamentals`를
     `public_serving`으로 가공(파생 지표화)하는 로직은 애초에 UNIT-06/07/08
     (Derivation Batch) 소관이라, 이번 유닛에서 raw 원문만 앞서 적재해도 당장
     활용되지 않는다. (b) PER/PBR을 뺀 시가총액만 부분 구현하면 `raw_fundamentals`가
     "일부 컬럼만 채워지는 반쪽 원문 테이블"이 되어 오히려 혼란을 유발한다.
     (c) "시가총액만이라도 지금 적재할지"는 범위를 얼마나 넓힐지에 대한 별도
     판단이라 임의로 넓히지 않고, 후속 유닛(Derivation Batch 착수 시점)에서
     명시적으로 다루는 쪽을 택했다. `raw_internal.raw_fundamentals` 테이블
     스키마만 설계서(§3-2)대로 만들고 Ingestion Batch는 이 테이블에 실제로
     값을 적재하지 않는다(아래 §2, §3 참조 — 규칙 A 대상이지만, 원본 OHLCV
     파이프라인이라는 이번 유닛의 핵심 가치를 이 불확실성 때문에 전부 멈추지
     않기 위해 범위를 좁혀 진행했다. 코디네이터가 이미 이 상황을 예상하고
     "실제 키 없으면 목/픽스처 기반으로 진행하고 사실을 기록하라"고 명시했으므로
     별도 질문으로 격상하지 않았다).

**결론: 이 유닛은 "실제 공공데이터포털 서비스키로 정상 시세 데이터를 수신해
raw_ohlcv에 적재하는 전 과정"을 종단간 검증하지 못했다.** 실 키 발급 후 반드시
`services/ingestion_batch/run_ingestion.py`를 `--trade-date`로 지정해 실행하고,
`gov_data_client.py`의 파싱 결과가 실제 필드와 일치하는지 재검증해야 한다.

---

## 1. 구현 범위

### 1-1. Ingestion Batch 핵심 로직 (`services/ingestion_batch/`)

- `gov_data_client.py`: `GovDataPortalClient` — `getStockPriceInfo` 호출 클라이언트.
  - 요청: `serviceKey`, `resultType=json`, `basDt`(YYYYMMDD), `numOfRows`, `pageNo`.
  - 재시도(§5-4): 타임아웃(10초)/5xx/네트워크 오류에 한해 최대 3회, 지수 백오프
    1s/2s/4s. 서비스키 오류 등 재시도해도 결과가 같은 오류(`GovDataApiError(retryable=False)`)는
    즉시 전파.
  - 게이트웨이 오류 감지(`_parse_gateway_error_envelope`): XML/JSON 두 형태 모두
    처리(§0 실측 근거). HTTP 상태코드 분기보다 **먼저** 본문 형태로 감지한다 —
    실측 결과 게이트웨이 오류가 HTTP 200이 아니라 403으로 오기 때문에, 상태코드
    기준으로만 분기하면 이 오류를 "그냥 4xx 실패"로 뭉뚱그리게 된다.
  - 정상 응답: `resultCode != "00"`이면 `GovDataApiError(retryable=False)`.
    `items`가 빈 문자열이면 결과 0건으로 명시적으로 처리(REQ-011 "+1영업일 지연"
    감지에 사용, 아래 1-3 참조). 결과 1건일 때 `item`이 리스트가 아니라 단일
    dict로 내려올 가능성에 대비해 정규화.
  - `basDt` 응답값이 요청한 날짜와 다르면 `GovDataClientError`로 명시적 실패
    (다른 날짜 데이터를 조용히 받아들이지 않음).
  - `RawFundamentals` 관련 필드(PER/PBR — 시가총액 `mrktTotAmt`은 제공이 확인됐으나
    함께 범위에서 제외했다, §0-3)는 파싱하지 않는다.
- `models.py`: `raw_internal.raw_ohlcv`/`raw_fundamentals` SQLAlchemy 모델.
  **`shared/db_models/`가 아니라 이 서비스 전용 모듈에 둔다** — 03-system-design.md
  §1-3 "shared: raw 데이터 모델 코드 없음" 원칙을 코드 레벨에서 지키기 위해
  별도의 `DeclarativeBase`(`RawInternalBase`)를 사용한다. `raw_ohlcv.market`은
  `reference.market_session` ENUM(UNIT-01)을 그대로 재사용한다.
- `repository.py`: `upsert_ohlcv()` — `scripts/load_calendar.py`와 동일한
  `ON CONFLICT DO UPDATE` 패턴으로 재실행 시 중복 오류 없이 최신값 갱신.
- `batch_run_repository.py`: `public_serving.batch_run` 기록(`start_run`/`finish_run`)
  + 서킷브레이커용 조회(`recent_ingest_statuses`).
- `circuit_breaker.py`: §5-4 "3일 연속 실패 시 고위험 알림으로 격상"을 그대로
  구현. **요청을 차단하지 않는다** — 배치는 매일 정상적으로 재시도하되, 연속
  실패가 임계치(기본 3)에 도달하면 알림 심각도만 격상한다(설계서 원문 그대로).
- `calendar_lookup.py`: `CalendarLookup` 프로토콜의 SQL 구현. **의도적으로
  `services/public_api/db/calendar_repository.py`와 로직이 100% 동일한 소규모
  중복**이다(§2 "설계서 대비 편차" 3번 참조).
- `run_ingestion.py`: CLI 진입점(`python -m services.ingestion_batch.run_ingestion`).
  - `resolve_target_trade_date()`: `--trade-date` 수동 지정 우선, 없으면
    `get_last_trading_day(market="KRX", as_of=now, calendar)`로 자동 계산(UNIT-01
    함수 재사용, 코드 변경 없음).
  - MVP는 KRX 정규장 세션만 다룬다(`decisions.md` DEC-010 — NXT 커버리지 미확인).
  - **+1영업일 지연 처리**: 정확한 배포 시각(예: "영업일+1 13시 이후")을
    하드코딩해 추측하지 않는다. 대신 API가 실제로 반환한 결과가 0건이면
    "아직 배포되지 않음" 가능성으로 간주해 `batch_run.status='FAILED'`로
    명시적으로 기록한다(§0-b, 아래 §2 편차 2 참조 — 설계서에 정확한 절차가
    없어 직접 판단한 부분).
  - 모든 실행 경로(캘린더 미확인, API 오류, 0건 응답, 성공/부분성공)에서
    **정확히 1개**의 `batch_run` 행을 기록한다 — 서킷브레이커가 실패 이력을
    빠짐없이 봐야 하기 때문.
  - `--dry-run`: 설정(환경변수) 검증만 하고 네트워크/DB에 손대지 않는다.

### 1-2. 데이터 모델 / 마이그레이션

- `shared/db_models/public_serving.py`: `BatchRun` 모델. `public_serving`은
  원본이 아니므로(§1-3) `shared/`에 두는 것이 설계 원칙과 상충하지 않는다.
- `db/alembic/versions/0003_create_public_serving_batch_run.py`: `public_serving`
  스키마 + `batch_run` 테이블 + **GRANT를 같은 리비전에 포함**(UNIT-01 DEF-003
  교훈 적용 — 스키마 생성과 권한 부여를 분리했다가 후자를 빠뜨리는 실수를
  이번에는 처음부터 하지 않음). `batch_worker`=SELECT/INSERT/UPDATE,
  `api_service`=SELECT.
- `db/alembic/versions/0004_create_raw_internal_ohlcv_fundamentals.py`:
  `raw_internal` 스키마 + `raw_ohlcv`/`raw_fundamentals` 테이블 + GRANT.
  `batch_worker`만 SELECT/INSERT/UPDATE, **`api_service`는 어떤 권한도 갖지
  않는다**(명시적 `REVOKE ALL`로 의도를 코드에도 남김 — §1-1 2차 방어).
  `raw_ohlcv.market`은 `reference.market_session` ENUM을 `create_type=False`로
  재사용(새 ENUM을 만들지 않아 두 테이블의 값 집합이 갈라질 여지 없음).
  `source_batch_id`는 `public_serving.batch_run.batch_run_id` FK.

### 1-3. 범위에 포함하지 않은 것 (설계서/코디네이터 지시에 따른 의도적 제외)

- **Derivation Batch(원본→가공 지표 변환)는 UNIT-06/07/08 소관**이라 이번
  유닛에서 구현하지 않았다(코디네이터 지시 그대로). `raw_internal`에서
  `public_serving.derived_metrics_daily` 등으로 넘어가는 로직/스키마는 전혀
  만들지 않았다.
- `public_serving.stock_master`/`derived_metrics_daily`/`market_summary_daily`/
  `current_published_batch`는 UNIT-03/06~08 소관이라 만들지 않았다(범위 외
  확장 금지).
- `raw_fundamentals` 실제 적재 로직은 §0-3 사유로 구현하지 않았다(PER/PBR은
  제공 여부 자체가 미확인, 시가총액 `mrktTotAmt`은 제공이 확인됐지만 함께
  범위에서 제외 — 부분 구현으로 인한 혼란을 피하기 위함).

---

## 2. 설계서 대비 편차 및 확인 필요 사항 (사유 포함)

1. **[확인 필요] 정상 응답 파싱 형태 미검증**: `gov_data_client.py`가 가정하는
   성공 응답 봉투(`{"response": {"header": {...}, "body": {"items": {"item": [...]}}}}`)와
   필드명은 공개 문서 근거이지 실측이 아니다. 실 서비스키 발급 후
   `python -m services.ingestion_batch.run_ingestion --trade-date <실제 과거 거래일>`을
   실행해 실제 데이터가 정상 파싱되는지 반드시 재검증해야 한다.
2. **[확인 필요] "+1영업일 지연"의 정확한 배포 시각 미확정**: 01-trend-analysis.md는
   2차 출처 기반으로 "영업일+1 오후 1시 이후 갱신"이라고만 기록했고 "확인
   필요"로 병기했다. 03-system-design.md도 이 정확한 시각을 규정하지 않는다
   (§7-2는 다른 cron인 "배치 신선도 알림"의 스케줄링만 다룸). 이 유닛은 정확한
   시각을 하드코딩해 추측하는 대신, **API의 실제 응답(0건 여부)으로 판단**하는
   방식을 택했다(§1-1). 이는 설계서에 없는 내용을 직접 판단한 것이므로 편차로
   기록한다 — 근거: 정확한 시각을 몰라도 "0건이면 아직 미배포"라는 판단은 항상
   안전하며(거짓 성공을 만들지 않음), cron 스케줄링을 잘못 잡아도 조용한 데이터
   손상 대신 명시적 FAILED로 귀결되어 REQ-005/012 전반의 "명시적 실패" 원칙과
   일관된다. **운영 시 실제 cron은 정규장 마감(15:30) 이전, 그리고 전일 데이터
   배포 시각(추정 13:00) 이후의 시간대(예: 14:00 KST)에 실행하도록 권고**하며,
   이 스케줄링 창(window)의 정확한 경계는 실 서비스키로 여러 날 관찰한 뒤
   확정해야 한다.
3. **[의도적 중복] `SqlCalendarRepository` 코드 중복**: `services/public_api/db/calendar_repository.py`와
   로직이 100% 동일한 클래스를 `services/ingestion_batch/calendar_lookup.py`에
   별도로 뒀다. 03-system-design.md §1-3(서비스별 독립 배포 단위, 별도 컨테이너
   이미지)을 지키기 위해 서비스 간 코드 import를 만들지 않았다 — UNIT-01
   산출물(`services/public_api/`)을 이번 유닛에서 리팩터링/이동하는 것은
   범위 외 변경이라 판단해 하지 않았다. 이 로직이 세 번째로 필요해지면(UNIT-06~08
   Derivation Batch 등) `shared/calendar_service/`로 승격하는 것을 권고한다.
4. **[설계서에 없는 추가 방어] `batch_run` 행을 모든 실행 경로에서 기록**:
   설계서 §5-4는 "실패 시 `batch_run.status='FAILED'` 기록"이라고만 서술해
   구체적으로 "어떤 실패 유형까지 기록해야 하는가"를 규정하지 않는다. 이
   유닛은 캘린더 미확인/API 오류/0건 응답/성공/부분성공 **전부**를 기록하도록
   구현했다 — 서킷브레이커(§5-4 "3일 연속 실패")가 실패 이력을 근거로 판단하는데
   일부 실패 유형을 기록하지 않으면 서킷브레이커가 무력화되기 때문이다.
5. **[게이트웨이 오류 응답 형태 수정, 실측 기반]** 최초 구현 시 "게이트웨이
   오류는 XML로만 온다"고 가정했으나(2차 출처 기반 통념), 실제로 서비스키 없이
   실 엔드포인트를 호출해보니 `resultType=json` 요청 시 오류가 XML이 아니라
   `{"OpenAPI_ServiceResponse": {...}}` 형태의 JSON으로, 그것도 HTTP 403으로
   내려옴을 확인했다(§0-2). 클라이언트를 두 형태 모두 처리하도록, 그리고
   상태코드 분기보다 본문 형태 감지를 먼저 하도록 수정했다. **실제 네트워크
   검증으로 잘못된 가정을 발견해 고친 사례**이며, 상상이 아니라 실측으로
   구현을 교정했다는 근거로 남긴다.
6. **`raw_fundamentals`는 스키마만 존재, 적재 로직 없음** (§0-3, 반복 기록):
   `services/ingestion_batch/repository.py`에 `upsert_fundamentals()` 같은
   함수를 만들지 않았다. PER/PBR은 소스 제공 여부 자체가 미확인이라 추측
   매핑을 코드화하지 않는다는 원칙을 지킨 것이고, 시가총액(`mrktTotAmt`)은
   제공이 확인됐음에도 함께 미구현으로 남겼다 — PER/PBR 없이 시가총액만
   부분 구현하면 가공(Derivation Batch, UNIT-06~08 소관)에서 쓰이지 않을
   코드를 미리 만드는 셈이라 YAGNI 원칙에 따라 후속 유닛으로 미뤘다.

---

## 3. 수동으로 확인이 필요한 부분 (6단계 테스터 및 향후 운영자용)

- **실 서비스키 확보 후 재검증(최우선)**: §0/§2-1 참조. `GOV_DATA_PORTAL_SERVICE_KEY`를
  실제 값으로 설정하고 `--trade-date`를 최근 실제 거래일로 지정해 실행,
  `raw_internal.raw_ohlcv`에 실제 종목 수(코스피+코스닥 약 2,500개)만큼 행이
  들어오는지, 페이지네이션(`numOfRows`/`pageNo`, `totalCount` 기준)이 필요한
  규모인지 확인 필요. 이번 유닛은 페이지네이션 반복 호출 자체는 구현했지만
  (`fetch_ohlcv(page_no=...)`), `run_ingestion.py`가 여러 페이지를 자동으로
  순회하도록 배선하지는 않았다(1회 호출, `num_of_rows=1000` 고정) — 종목 수가
  1000을 넘으면 이 배선을 추가해야 한다. **이는 실 데이터 규모를 확인하지
  못해 남겨둔 명시적 미완성이다.**
- **실제 cron 스케줄링 시각 확정**: §2-2 참조. 여러 영업일 동안 관찰 후 안전한
  실행 시각(예: 14:00 KST)을 확정해야 한다.
- **NXT 데이터 커버리지**: `decisions.md` DEC-010 승계 — 이번 유닛도 KRX만
  다루며 재확인하지 않았다.
- **PER 소스 확인**: §0-3/§2-6 참조 — `getStockPriceInfo`가 PER/PBR을 제공하는지는
  여전히 미확인이다(시가총액 `mrktTotAmt`은 제공이 확인됨). PER/PBR 소스가
  확인되면(또는 시가총액만이라도 우선 적재하기로 범위를 정하면) `raw_fundamentals`
  적재 로직(파서 + upsert 함수)을 추가하는 후속 작업이 필요하다.
- **호출 한도(rate limit) 실측치**: 03-system-design.md §2-2가 이미 "5단계
  착수 시 확인 필요"로 남겨둔 항목이며, 이번에도 실 키가 없어 확인하지 못했다.
- **실제 컨테이너/cron 배포 미검증**: 이 유닛은 로컬 CLI 실행까지만 검증했고,
  실제 컨테이너 이미지 빌드나 cron 스케줄러 등록은 검증 범위 밖이다(10단계
  배포테스트 영역).

---

## 4. 인수 조건 (Acceptance Criteria) — 6단계 테스터용

**AC-1 (게이트웨이/오류 처리, 실측 기반)** `pytest tests/unit/test_gov_data_client.py`가
아래를 포함해 전부 pass:
  - 정상 응답(item 리스트/단일 dict 정규화 포함) 파싱 성공
  - `items=""` → 결과 0건(레코드 빈 리스트) 반환, 예외 아님
  - `resultCode != "00"` → `GovDataApiError(retryable=False)`, 재시도 없음(호출 1회)
  - 게이트웨이 XML 오류(HTTP 403, `<OpenAPI_ServiceResponse>`) → `GovDataApiError(retryable=False)`, 호출 1회
  - 게이트웨이 JSON 오류(HTTP 403, `{"OpenAPI_ServiceResponse": {...}}`) → 동일하게 처리, 호출 1회 (**실측 기반 회귀 테스트**)
  - 게이트웨이 오류 중 재시도 대상 코드(22) → 최초 시도+3회 재시도(호출 4회), 백오프 1s/2s/4s 순서로 `sleep` 호출
  - HTTP 5xx → 재시도 후 `GovDataClientError`, HTTP 4xx(게이트웨이 오류 아님) → 즉시 실패(재시도 없음)
  - 타임아웃/네트워크 오류 → 재시도 후 `GovDataClientError`
  - 일시적 실패 후 회복(2회차 성공) → 정상 반환
  - `basDt` 불일치, 필수 필드 누락 → `GovDataClientError`

**AC-2 (서킷브레이커)** `pytest tests/unit/test_circuit_breaker.py` 전부 pass:
  - 연속 실패가 임계치 미만이면 `is_open=False`
  - 연속 실패가 임계치 이상이면 `is_open=True`(초과해도 계속 True)
  - SUCCESS/PARTIAL이 스트릭을 끊음
  - 빈 이력은 `is_open=False`

**AC-3 (대상 거래일 계산)** `pytest tests/unit/test_run_ingestion.py` 전부 pass:
  - `--trade-date` 지정 시 캘린더 조회 없이 그 값을 그대로 사용
  - 미지정 시 `get_last_trading_day(market="KRX", ...)`로 계산(UNIT-01 로직 재사용 확인)
  - 캘린더 데이터 공백 → `IngestionRunError`
  - 캘린더 데이터 무결성 위반(거래일인데 마감시각 없음) → `CalendarDataError` 그대로 전파

**AC-4 (마이그레이션, 실 PostgreSQL로 검증 완료)**
  - `ALEMBIC_DATABASE_URL=<migrator> alembic upgrade head`(0001~0004) 성공 →
    `public_serving`/`raw_internal` 스키마, `batch_run`/`raw_ohlcv`/`raw_fundamentals`
    테이블 생성 확인
  - `\dp public_serving.batch_run` → `batch_worker=arw`, `api_service=r`
  - `\dp raw_internal.raw_ohlcv`, `\dp raw_internal.raw_fundamentals` → `batch_worker=arw`만 있고
    `api_service` 행 자체가 없음(권한 0)
  - `api_service` 계정으로 `SELECT * FROM raw_internal.raw_ohlcv` → `permission denied for schema raw_internal`
    (스키마 USAGE 자체가 없어 테이블 접근 이전에 거부됨 — 1차+2차 방어 동시 확인)
  - `alembic downgrade 0002` → 두 스키마 완전히 제거, `alembic upgrade head`로 재적용 시 오류 없이 복원

**AC-5 (Ingestion Batch 실행, 실 PostgreSQL + Fake 클라이언트로 검증 완료)**
  - `python -m services.ingestion_batch.run_ingestion --dry-run` →
    `BATCH_DATABASE_URL` 미설정 시 종료 코드 1 + 안내 메시지, 설정 시 종료 코드 0 +
    설정 요약 출력(서비스키 없어도 dry-run은 통과)
  - `GOV_DATA_PORTAL_SERVICE_KEY` 미설정 + `--dry-run` 아님 → 종료 코드 1 + 안내 메시지
  - (Fake 클라이언트로 실제 DB 대상 검증) 정상 응답 2건 → `raw_ohlcv`에 2행 삽입,
    `batch_run` 1행(`SUCCESS`, `validation_passed=true`)
  - 동일 종목 재수집(가격 변경) → 중복 오류 없이 `UPDATE`로 반영(idempotent upsert)
  - 응답 0건 → `raw_ohlcv` 삽입 없음, `batch_run` 1행(`FAILED`, error_summary에 "+1영업일 지연" 관련 안내 포함)
  - 3회 연속 API 오류 → `batch_run` 3행 모두 `FAILED`, `recent_ingest_statuses`+`circuit_breaker.evaluate`로
    `is_open=True` 확인(고위험 알림 로그 출력)

**AC-6 (정적 분석)**
  - `python -m ruff check .` 오류 0건
  - `python -m pytest tests/unit -q` **59건**(UNIT-01의 36건 + 이번 유닛 23건) 전부 pass

---

## 5. 게이트 1 — 정적 분석/린트 결과

- 이 프로젝트는 UNIT-01에서 `pyproject.toml`에 `ruff` 설정을 이미 도입했다(건너뛴 것이 아니라 기존 설정을 그대로 적용).
- `python -m ruff check .` 최초 실행 시 4건 발견(UP017 datetime.UTC 별칭 2건, import 정렬 1건, 라인 길이 초과 2건) → `--fix`로 자동 수정 가능한 것 적용 후 수동으로 나머지(E402 import 순서, 긴 함수 시그니처 줄바꿈) 수정. 최종 `All checks passed!` 확인.
- mypy 등 타입체커, black 등 포매터는 UNIT-01과 동일하게 아직 도입하지 않았다(범위 외).

## 6. 게이트 2 — 자체 코드 리뷰 체크리스트

- [x] **설계서/디자인서 명세와 실제 구현이 일치하는가** — §1-2(Ingestion Batch만 외부 API와 통신, 원본은 raw_internal에만 적재), §1-1(3중 방어 — 스키마 분리/DB 권한 분리/프로세스 분리 모두 구현), §3-2(raw_ohlcv/raw_fundamentals/batch_run 컬럼 정의 그대로), §5-4(재시도 3회 지수백오프 1/2/4초, 서킷브레이커 3일 연속 실패 시 알림 격상)를 그대로 구현했다. 남은 편차/확인 필요 사항은 §2에 전부 사유와 함께 명시했다(추측 없이 실측/명시적 미구현으로 처리).
- [x] **에러 처리가 누락된 경로가 없는가(예외를 삼키고 무시하는 코드 없음)** — `gov_data_client.py`(타임아웃/5xx/게이트웨이오류/JSON파싱실패/필드누락/날짜불일치 전부 명시적 예외), `run_ingestion.py`(모든 실행 경로에서 batch_run 기록, 예기치 못한 예외도 `except Exception`으로 잡아 FAILED로 명시적 기록 후 재전파 대신 종료코드 1로 알림 — 조용히 삼키지 않음), `repository.py`/`batch_run_repository.py`(DB 예외는 상위로 전파되어 CLI에서 처리).
- [x] **입력값 검증이 시스템 경계(사용자 입력, 외부 API 응답)에서 이루어지는가** — CLI `--trade-date` 파싱 실패 시 argparse가 명시적으로 실패. 외부 API 응답: 필수 필드 누락/날짜 불일치/숫자 파싱 실패/resultCode 비정상/게이트웨이 오류 봉투를 전부 명시적으로 검증·거부한다(`_parse_item`, `_parse_gateway_error_envelope`, `_parse_success_payload`). DB 쓰기 전 `basDt` 일치 검증으로 다른 날짜 데이터 혼입을 차단.
- [x] **하드코딩된 시크릿/자격증명이 없는가** — DB 접속 정보(`BATCH_DATABASE_URL`)와 API 서비스키(`GOV_DATA_PORTAL_SERVICE_KEY`) 모두 환경변수로만 주입. `.env.example`에는 `CHANGE_ME` 플레이스홀더만 존재. 로컬 검증에 사용한 `devpass`는 6단계가 미리 세팅한 로컬 1회성 Docker 컨테이너 값이며 코드/설정 파일에 커밋하지 않았다. 실 서비스키는 애초에 보유하지 않아 코드 어디에도 존재하지 않는다.
- [x] **범위를 벗어난 변경(곁다리 리팩터링 등)이 섞여 있지 않은가** — UNIT-01 산출물(`shared/calendar_service/`, `services/public_api/`, `scripts/load_calendar.py`, 기존 마이그레이션 0001/0002)은 전혀 수정하지 않았다(재사용만 함, calendar_lookup 중복은 §2-3에서 사유 명시). Derivation Batch(UNIT-06~08)나 `public_serving`의 다른 테이블은 만들지 않았다(§1-3). `requirements-dev.txt`에서 `httpx` 중복 제거는 이번 변경(런타임 의존성으로 승격)에 직접 연관된 최소 정리로, 별도 리팩터링이 아니다.

---

## 7. 로컬 동작 확인 요약 (실행 로그 근거)

- `python -m pytest tests/unit -q` → **59 passed**(UNIT-01 36건 + 이번 유닛 23건: `test_gov_data_client.py` 13건, `test_circuit_breaker.py` 6건, `test_run_ingestion.py` 4건)
- `python -m ruff check .` → **All checks passed!**
- 실제 gov 엔드포인트에 서비스키 없이 호출(`curl`) → HTTP 403 + XML/JSON 두 형태의 게이트웨이 오류 실측 확인(§0-2), 클라이언트/테스트에 반영.
- 로컬 Docker `stock-screener-db`(migrator/batch_worker/api_service 기존 계정 재사용):
  - `alembic upgrade head`(0001~0004) → `public_serving`/`raw_internal` 스키마 및 테이블 생성 확인.
  - `\dp public_serving.batch_run` → `batch_worker=arw`, `api_service=r` 확인.
  - `\dp raw_internal.raw_ohlcv`/`raw_fundamentals` → `batch_worker=arw`만 존재, `api_service` 권한 행 없음(0권한) 확인.
  - `api_service` 계정으로 `SELECT * FROM raw_internal.raw_ohlcv` → `permission denied for schema raw_internal` 확인(2차 방어 실동작 확인).
  - `alembic downgrade 0002` → 스키마/테이블/GRANT 전부 제거 확인 → `alembic upgrade head`로 재적용해 정상 복원.
  - Fake 클라이언트 + 실제 `run_once()` 호출: (1) 신규 2종목 삽입 → `raw_ohlcv` 2행, `batch_run` 1행(SUCCESS) 확인. (2) 동일 종목 갱신값으로 재실행 → `ON CONFLICT DO UPDATE`로 close/volume이 실제로 갱신됨을 쿼리로 확인(이 과정에서 `volume`/`trading_value` 컬럼이 `Mapped[int]`로만 선언되어 32비트 `INTEGER`로 생성되던 실제 결함을 발견 — `BigInteger`로 수정 후 재검증 완료, §2에 기록하지 않은 이유는 편차가 아니라 구현 버그였고 즉시 수정했기 때문). (3) 응답 0건 → `raw_ohlcv` 변화 없음, `batch_run` 1행(FAILED, "+1영업일 지연" 안내 포함) 확인. (4) 3회 연속 API 오류 → `batch_run` 3행 모두 FAILED, `evaluate_circuit_breaker` 결과 `is_open=True, consecutive_failures=3` 확인.
  - 검증 후 `raw_internal`/`public_serving.batch_run` 테스트 데이터는 `TRUNCATE`로 정리하고, `scripts/load_calendar.py`로 캘린더 데이터를 재적재해 다음 세션(UNIT-03)이 바로 이어서 쓸 수 있는 상태로 DB를 남겨뒀다.

---

## 8. 다음 단계

이 노트 작성 및 `traceability.md` 갱신 완료 후, 6단계(단위테스트, `06-unit-tester`)를
UNIT-02 대상으로 호출해야 한다. 6단계는 특히 다음을 독립적으로 재검증할 것을 권고한다:
(1) 실 PostgreSQL로 GRANT/스키마 분리가 실제로 동작하는지(이 노트의 검증을 신뢰하지
않고 직접 재현), (2) `gov_data_client.py`의 재시도/서킷브레이커 분기를 다른 시나리오
조합으로 추가 스윕, (3) §3 "수동 확인 필요" 목록(페이지네이션 미배선, cron 시각
미확정, PER/PBR 미확인)이 이번 유닛의 "완료" 판정에 영향을 주는 결함인지 아니면
후속 유닛/운영 과제로 남겨도 되는지 판단.
