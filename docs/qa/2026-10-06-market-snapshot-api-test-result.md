# 전 종목 준실시간 시세 API 연결 시험 결과서 (2026-10-06)

- 범위: 백엔드만. `MarketSnapshotPoller`를 앱에 연결하고 소유자 전용 API 2개를 추가했다. 화면은 이 작업 범위가 아니다.
- 실제 증권사·실제 DB 접속은 하지 않았다(모의 증권사 REST + 가짜 종목 유니버스 함수).

## 1. 변경 요약
| 파일 | 내용 |
|---|---|
| `services/public_api/api/local_market.py`(신규) | `GET /api/v1/local/market/quotes?codes=` , `GET /api/v1/local/market/status`. 접근 통제는 `local_realtime.require_owner` 재사용. `MarketRuntime`(폴러·종목 유니버스·유휴 정지·정리) |
| `services/public_api/db/stock_repository.py` | `list_active_stock_codes(session)` 추가(읽기 전용) |
| `services/public_api/intraday/service.py` | `IntradayService.client` 읽기 전용 접근자 |
| `services/public_api/intraday/kis_client.py` | 낮은 우선순위 호출(`multi_price`)이 상세 화면 호출에 양보하는 장치(§5) |
| `services/public_api/main.py` | import 1줄, 라우터 등록 1줄(+주석 1줄), lifespan 종료에 `shutdown_market()` 1줄 |
| `frontend/src/lib/auth/bffPaths.ts` | `LOCAL_ALLOWED`·`LOCAL_ADMIN_ONLY`에 `/api/v1/local/market/(quotes\|status)` |
| `frontend/scripts/check-auth.mjs` | 허용·관리자 전용·거부 경로 시험 1건 추가 |
| `tests/unit/test_local_market_api.py`(신규) | 22건 |

동작 결정 사항
- 종목 유니버스: 실제 종목 마스터는 `reference`가 아니라 **`public_serving.stock_master`**(`is_active=true`)이며 마이그레이션 0005에 `GRANT SELECT ... TO api_service`가 있다. 새 테이블·권한 요청 없음. 시작 때와 이후 1시간마다 다시 읽고, 읽기 실패 또는 0건이면 이전 목록 유지(실패 시 30초 뒤 재시도). 형식이 틀린 코드·중복은 걸러낸다.
- 폴러 시작: `quotes` 첫 요청. 마지막 `quotes` 요청 뒤 `KIS_MARKET_IDLE_SECONDS`(기본 300초, 하한 0.1초, 잘못된 값은 기본)가 지나면 정지. `status`는 폴러를 시작하지도 유휴 시간을 갱신하지도 않는다(상태 화면이 폴링해도 증권사 호출을 유지시키지 않도록 한 판단).
- 첫 `quotes` 응답은 값이 비어 있다(`missing` 전부, `stale: true`). 소비 측이 다시 조회해야 한다.
- 응답: `{"data": {"quotes": [...요청 순서, 중복 제거...], "missing": [...], "meta": {cycle_seconds, last_cycle_at, covered, total, stale, running}}, "error": null}`, `Cache-Control: no-store`. 값이 없는 종목(유니버스에 없음·빈 값 행으로 버려짐·아직 못 받음)은 `missing`.
- `stale`: `last_cycle_at`(모든 묶음이 성공한 마지막 한 바퀴의 끝)이 없거나, 주기의 3배보다 오래됨. 주기 = 장중은 max(마지막 한 바퀴 측정 시간, 묶음 수 × min_interval) + cycle_pause, 장외는 max(off_hours_cycle_interval, 측정 시간). 일부 묶음이 계속 실패하면 완주가 갱신되지 않아 stale로 보인다(보수적). 낡은 값도 지우지 않고 `fetched_at`과 함께 돌려준다.
- 입력: 최대 100개, 6자리 영숫자 대문자, 쉼표 앞뒤 공백·빈 항목·누락은 모두 400 `INVALID_PARAMETER`. 검증은 접근 통제 뒤·폴러 시작 앞에서 하므로 거절된 요청은 폴러·DB를 건드리지 않는다.

## 2. 시험 결과 숫자
| 항목 | 결과 |
|---|---|
| 신규 `tests/unit/test_local_market_api.py` | **22건 통과**, 같은 파일 3회 반복 모두 22건 통과(약 42초/회) |
| `tests/unit` 전체 | **952 passed, 1 skipped**(작업 전 기준선 930 passed, 1 skipped → 정확히 +22) |
| `ruff check services scripts tests/unit` | All checks passed |
| `npx tsc --noEmit` | 오류 0 |
| `node scripts/check-auth.mjs` | 34건 중 34 통과, 0 실패 |

신규 22건 구성: 종단(실제 uvicorn + 모의 REST) 첫 요청·값 채움(장중/장외/실제시각 3 변형), 요청 순서·중복, stale(값 유지), 400 입력 검증(12종 + 100개 경계 + 파라미터 없음), 접근 통제(공개 Host·프록시 헤더 4종·꺼짐·앱키 없음 503), 로그인 켠 환경 관리자 403/200, 두 경로의 `require_owner` 의존성 확인, 유휴 정지·재시작(요청이 계속되면 유지, status는 갱신 안 함, 정지 뒤 호출 수 불변), 유휴 환경변수 파싱, 종료 시 정리, 종목 목록 갱신·읽기 실패 유지(예외 메시지 비노출)·0건 유지·상장폐지 제거, 첫 읽기 실패 후 복구, 같은 `KisClient` 공유(생성 1개), 단위(코드 파싱, stale 경계, 보기/missing, 우선순위 양보 3건).

## 3. 발견·수정한 결함
1. **정상 상태가 항상 stale로 보임(내 구현, 시험 중 발견·수정)**: 첫 바퀴는 호출 간격 대기가 없어 측정 시간이 0.013초였고 그 3배(0.04초)로 판정해 매 응답이 stale이었다. 호출 수 × `min_interval`을 하한으로 보정하고 회귀 시험(`test_장중_첫_바퀴의_짧은_측정_시간...`)을 추가했다. 시험이 장중 시각(KST 16시대)에 돌아 우연히 드러났으므로, 이후 장중/장외를 주입으로 고정해 시각과 무관하게 검증한다.
2. 시험 쪽: 같은 파일의 여러 시험이 로컬 경로 호출 한도(600/분)를 공유해 간헐적으로 429가 날 수 있어 서버 기동마다 `reset_rate_limit_state()`를 호출한다.

## 4. 호출 한도 공유 방식과 판단
- `get_runtime`이 `shared_intraday_service(settings)`를 받아 그 `.client`(신규 읽기 전용 접근자)로 `make_kis_fetcher`를 만든다. 상세 화면 REST(`get_intraday_service`)와 실시간 시작 값(`make_seed_fetcher(shared_intraday_service(...))`)이 쓰는 인스턴스와 동일하다(시험: 프로세스 내 `KisClient` 생성 1개, 폴러 호출이 같은 인스턴스의 토큰·`_last_call`을 갱신). 앱키가 바뀌어 서비스가 새로 만들어지면 런타임도 새로 만들고 옛것은 정리한다.
- 합산 호출률은 `KisClient._throttle`(0.12초 간격 ≈ 초당 8건)로 상한이 정해지고, 폴러의 `min_interval` 0.2초(초당 5건)가 그 안의 몫을 차지한다.
- **상세 화면 우선 장치는 구현했다(작게)**: `multi_price`만 `low_priority=True`. 일반 호출이 진행 중(대기 포함)이면 20ms씩 최대 100회(2초)까지 양보한 뒤 진행(굶음 방지). 일반 호출은 양보 대상이 아니다. 효과: 상세 화면 시작 때의 분봉 연속 호출(최대 14쪽)이 순환 호출에 끼어들려 느려지는 것을 줄인다. 한계: 호출 사이의 짧은 틈에는 순환 호출 1건이 들어올 수 있고, 양보는 호출률 총량을 줄이지는 않는다(총량은 throttle이 담당).
- **위험(미해결)**: (a) 실시간 접속키 발급(`/oauth2/Approval`)은 `KisClient`를 거치지 않고 별도 httpx로 나가 호출 간격 공유 대상이 아니다. (b) 증권사의 실제 초당 한도가 초당 8건보다 낮으면(미확인) 순환 때문에 상세 화면도 `RATE_LIMITED`를 받을 수 있다. 토큰 버킷 같은 합산 예산 장치는 아니다. (c) 같은 앱키를 다른 프로세스·PC에서 쓰면 공유되지 않는다.

## 5. 확인하지 못한 것
- 실제 증권사 응답 필드·값 형태, 30종목 동시 조회 동작, 실제 호출 한도(앱키 없음). 설계서 §6 항목은 모두 그대로 미확인.
- 실제 PostgreSQL에서 `list_active_stock_codes`와 `api_service` 권한으로 읽기(DB 없이 가짜 함수 주입으로만 시험). SQL은 기존 검색 저장소와 같은 모델·조건이며 GRANT는 마이그레이션 0005 문구로만 확인했다.
- 2,800종목 규모의 실제 한 바퀴 시간과 `stale` 임계(3배)의 적절성, 유휴 5분 기본값 동작(시험은 0.8초로 축소).
- 공휴일(달력 미연동): 휴장일 장중 시간대에도 연속 순환한다.
- 웹 서버 대행(Next) 경로의 실제 동작은 허용 목록 시험(`check-auth`)까지만 확인했고 브라우저·대행 종단 시험은 하지 않았다.
- 다중 워커 환경(폴러가 프로세스마다 생김)은 시험하지 않았다. 설계상 워커 1개만 허용.
- `status`가 폴러를 시작하지 않는 결정은 요청 문구("첫 요청 때 시작")의 해석이다. 다르게 원하면 알려 달라.

## 6. 위험
- 로컬 경로 호출 한도(`LOCAL_INTRADAY_RATE_LIMIT_PER_MINUTE`, 기본 600/분 = 초당 10건)가 `quotes` 폴링에도 적용된다. 화면은 1초 이상 간격으로 조회해야 한다.
- 서버 재시작 직후 첫 바퀴(전 종목 약 19초 가정) 동안 값이 비어 있고 `stale: true`.
- 종목 목록을 읽을 수 없는 상태로 시작하면 유니버스가 비어 모든 요청이 `missing`(요청은 200). 복구되면 30초 안에 반영.
- `stop()`은 진행 중인 증권사 호출을 기다리므로(최대 5초) 유휴 정지·종료가 그만큼 지연될 수 있다.
