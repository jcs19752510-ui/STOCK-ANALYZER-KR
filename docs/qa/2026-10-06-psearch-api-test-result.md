# 증권사 조건검색 API(백엔드) 시험 결과 — 2026-10-06 (DEC-088)

계약서: `docs/stock-detail/09-psearch-api-contract.md`. 범위는 백엔드와 BFF 허용 경로뿐이며 화면은 다른 담당이 한다.

## 1. 변경 요약
| 파일 | 내용 |
|---|---|
| `services/public_api/intraday/config.py` | `IntradaySettings.hts_id`(기본 None, `field(repr=False)`), `get_settings`가 `KIS_HTS_ID`를 읽음(공백 제거, 없으면 None) |
| `services/public_api/api/local_psearch.py` (신규) | `GET /local/psearch/conditions`(60초 캐시), `GET /local/psearch/results?seq=`. `require_owner` 재사용, `shared_intraday_service(settings).client`를 `asyncio.to_thread`로 호출 |
| `services/public_api/intraday/kis_client.py` | `psearch_titles`/`psearch_result`에 키워드 전용 `low_priority: bool = False` 추가(계약서 §4-5 허용 사항, 기존 호출은 그대로) |
| `services/public_api/db/stock_repository.py` | `lookup_stock_names(session, codes)` 추가 — `stock_master`에서 읽기 전용 SELECT 한 개 |
| `services/public_api/main.py` | import 한 줄 + 라우터 등록(주석 포함) |
| `frontend/src/lib/auth/bffPaths.ts` | `LOCAL_ALLOWED`·`LOCAL_ADMIN_ONLY`에 `/api/v1/local/psearch/(conditions\|results)` |
| `frontend/scripts/check-auth.mjs` | 시험 1건 추가(로컬 빌드에서만 열림·관리자 전용·비슷한 경로 거부) |
| `.env.example` | `KIS_PSEARCH_CACHE_SECONDS` 안내 두 줄 |
| `tests/unit/test_local_psearch_api.py` (신규) | 49건 |

구현 방식: 조건별 상태(`_Entry`: 비동기 잠금, 캐시, 편입 시각, 변화 기록)를 최근 사용 순으로 최대 20개 보관. 시계(`set_clock`), 캐시 시간(`set_cache_seconds`, 기본은 환경변수 2~60 보정), 종목 마스터 함수(`set_master_loader`)를 주입할 수 있다. 이름·시장은 코드 → (이름, 시장) 메모리 캐시(최대 5,000건·1시간)를 거치고, 마스터 읽기 실패 시 null로 계속하며 30초 동안 다시 읽지 않는다. 쿼리스트링은 BFF가 `pathname`만 검사하므로 `quotes?codes=`와 같은 방식이다(`route.ts`에서 확인).

## 2. 시험 결과
| 항목 | 결과 |
|---|---|
| `tests/unit/test_local_psearch_api.py` | **49 passed** (실제 uvicorn + 모의 증권사 REST, 약 40초) |
| `tests/unit` 전체 | **1024 passed, 1 skipped** (기준 975 passed, 1 skipped + 신규 49) |
| `ruff check services scripts tests/unit` | All checks passed |
| `frontend`: `npx tsc --noEmit` | 오류 없음 |
| `frontend`: `node scripts/check-auth.mjs` | 35 pass / 0 fail |

신규 49건의 구성(함수 33개, 매개변수 포함 49건):
- 설정 3개(+캐시 시간 보정 16건): `hts_id` 읽기·repr 숨김·기존 생성처 호환, 환경변수 보정(비어 있음·문자·NaN·음수·상·하한·inf), 로그 필터.
- 조건 목록 3개: 모양, 60초 캐시(여러 요청에도 증권사 1회, 59.9초 재사용·60.1초 재조회), 빈 목록·이상한 행·`output2` 없음, 거절(`PSEARCH_REJECTED`)·한도(429)·인증 실패·예상 밖 예외, 실패 직후 10초간 같은 오류.
- 결과 모양·보충·캐시: 키 전부, 이름(행 우선→마스터→null)·시장(마스터), 동시 25요청 → 모의 서버 `PSEARCH_CALLS == {"0": 1}`, 경계(4.99초 재사용·5.01초 재조회), 조건별 독립 캐시, 환경변수 30초·0.1→2초 보정.
- 편입·이탈: 만료 뒤 변화 기록(최신이 앞), 첫 조회는 변화 없음, 남은 종목의 `entered_at` 유지, 변화 최대 20건, 이탈 후 재진입은 새 `entered_at`.
- 0건: 200 + `empty:true`, 직전 종목 전부 이탈 기록, 다시 생기면 전부 편입, 0건도 캐시, 문구의 비밀값 가리기·120자 제한, 성공했지만 행이 없는 경우 `empty_message:null`.
- 100건: `capped:true`·순서·개수, 130건 입력은 100건으로 자름, 99건은 `capped:false`.
- 행 해석: 코드 키 순서, 알려진 키가 없으면 6자리 영숫자 값, 5·7자리·특수문자·중복·비딕셔너리 행 버림.
- 마스터: 캐시(새 코드만 조회), 실패 시 null·30초 재시도 억제·복구, 5,000건 한도·1시간 만료·시계 역행.
- 입력 검증: 잘못된 seq 17종(+파라미터 없음)이 400 `INVALID_SEQ`이고 증권사를 부르지 않음, 유효 seq 4종 통과, 조건 20개 초과 보관(최근 사용 유지, 100개 연속 요청 후에도 20개).
- 설정 누락: HTS ID 없음·공백 → 503 `PSEARCH_NOT_CONFIGURED`(두 경로), 앱키 또는 시크릿 없음 → 503 `LOCAL_INTRADAY_NOT_CONFIGURED`, 증권사 호출 없음.
- 호출 실패: 이전 결과 없음 → 429/502 코드, 이전 결과 있음 → `stale:true`(이전 항목·`fetched_at`·`entered_at` 그대로, `age_seconds` 증가, 변화 기록 없음), 실패 직후 재시도 억제, 회복 시 `stale:false`, 모의 서버를 실제로 내려 만든 연결 거절, 실패가 다른 조건에 번지지 않음.
- 접근 통제: 공개 Host·프록시 헤더 6종·꺼짐·허용 IP 밖 → 404(증권사 호출 0, 캐시 생성 0), 로그인을 켠 환경에서 관리자 아님·uuid 아님·헤더 없음 → 403 / 관리자 → 200, 두 경로 모두 `require_owner` 의존성·GET만, 쓰기 메서드 거부.
- 비밀값: 정상·오류·0건·stale·마스터 실패·연결 거절을 포함한 응답 본문·헤더 전체와 DEBUG 수준 전체 로그(httpx·httpcore 포함)에서 HTS ID·앱키·시크릿 문자열 검색 → 0건. 성공·오류 응답 모두 `Cache-Control: no-store`.

**시험이 실제로 잡는지(변이 확인)**: 잠금 제거 → 동시 요청 시험 실패, 비밀값 가리기 제거 → 가리기 시험 실패, httpx 로그 필터 제거 → 비밀값 로그 시험 실패. 확인 후 원복했다.

## 3. 발견·수정한 결함
1. **HTS ID가 httpx 요청 로그로 새는 경로**: `user_id`가 쿼리스트링이라 root 로그가 INFO 이하이면 `httpx`가 `...?user_id=<HTS ID>`를 그대로 기록한다(변이 확인으로 재현). `local_psearch` import 시 `httpx`·`httpcore` 로거에 `user_id=***` 치환 필터를 붙여 막았다. 단, 필터는 프로세스 전역 로거에 걸리므로 부수 효과가 없는지는 아래 위험에 적었다.
2. **마스터 캐시 한도 초과 시 이번 응답이 비어 나오는 결함**(시험 중 발견): 한 번에 5,000건을 넘게 읽으면 방금 읽은 값이 캐시에서 밀려나 반환값이 null이 됐다. 이번에 읽은 값을 따로 들고 있다 반환하도록 수정했다. API 경로에서는 항목이 최대 100건이라 실제로는 닿지 않는다.
3. 시험 작성 중 틀린 기대 3건(오류 봉투에 `meta`가 포함됨, 필드 이름 목록에 `price`가 있음, 중복 `seq` 파라미터는 마지막 값을 씀)을 고쳤다 — 구현 결함이 아니라 시험의 가정 오류다.

## 4. 계약서와 다르게 한 점 / 요청 변경 목록
계약서를 바꾸지는 않았다. 계약서가 정하지 않아 구현에서 선택한 부분은 다음과 같고, 화면 담당이 알아야 한다.
- **검사 순서**: seq 형식(400)을 먼저 확인하고 그 다음에 앱키(503)·HTS ID(503)를 확인한다(`local_market`이 입력 검증을 먼저 하는 것과 같음). 계약서 표 순서와 다르다. 필요하면 바꿀 수 있다.
- **실패 직후 재시도 억제**: 호출이 실패하면 캐시 시간(결과) 또는 10초(조건 목록) 동안 증권사를 다시 부르지 않고 같은 결과(stale 또는 같은 오류)를 돌려준다. 한도 초과 상황에서 요청이 몰려 상태를 악화시키지 않기 위한 것으로 계약서 §4-4와 모순되지 않는다. 다만 일시 오류가 최대 캐시 시간만큼 보인다.
- 증권사 오류 코드 `AUTH_FAILED`·`UPSTREAM_BAD_RESPONSE` 등 `RATE_LIMITED` 이외는 모두 502 `UPSTREAM_UNAVAILABLE`로 합쳤다(계약서 표의 "연결 불가·인증 실패 등").
- `age_seconds`·`fetched_at`·`entered_at`은 소수 3자리 epoch 초(float)다.
- 오류 응답 봉투에도 `meta`가 들어간다(기존 `ApiError` 처리 방식, 계약서의 `{"data":null,"error":{...}}`에 추가 키).
- 코드는 6자리 영숫자(대소문자)를 받아 대문자로 바꾼다. 같은 조건의 `entered_at`은 서버 메모리라 재기동하거나 20개 한도에서 밀려나면 다시 센다.
- 요청 변경(수정하지 않음): `scripts/mock_kis_server.py`는 수정하지 않았다. 기존 시험 파일도 수정하지 않았다.

## 5. 확인하지 못한 것
- **실제 증권사 응답**: 필드 이름(종목코드·이름 키), 0건을 어떤 코드·문구로 돌려주는지, 갱신 주기, 100건 한도의 실제 동작은 모의 서버와 공식 샘플 기준일 뿐 실제로 확인하지 못했다. `fields`와 `empty_message`는 이를 현장에서 확인하기 위한 진단 값이다.
- **0건과 다른 거절의 구분**: `KisClient`는 HTTP 비정상(500 등)·`rt_cd != 0`을 모두 `UPSTREAM_ERROR`로 던진다. 계약서 §4-3대로 이를 0건(`empty:true`)으로 처리하므로, 증권사의 일시 장애(비 200 응답)나 HTS ID 불일치도 "0건 + 이탈 기록"으로 보일 수 있다. `empty_message`로만 사람이 구분한다. 구분하려면 `KisClient` 오류 코드를 나누어야 하며 이는 이번 범위 밖이다.
- 실제 PostgreSQL에 대한 `lookup_stock_names` SQL 실행(시험은 주입한 함수로만 검증, DB 없음). SQLAlchemy 문장은 `list_active_stock_codes`와 같은 방식의 단순 SELECT이고 `api_service`의 `public_serving` 읽기 권한은 `deploy/render/neon-setup.sql` 주석(공개 API는 `public_serving` 읽기 전용)으로만 확인했다.
- 실제 웹 서버 대행(BFF)·로그인 포함 종단 시험(메인 담당 단계). `check-auth.mjs`는 경로 허용 규칙만 시험한다.
- 증권사가 같은 `user_id`를 짧은 시간에 여러 조건으로 조회하는 것을 제한하는지, 조건 20개를 동시에 계속 조회할 때의 호출 한도.
- 서버 종료 시 정리: 이 API는 백그라운드 작업을 만들지 않아 lifespan 변경이 없다.

## 6. 위험
- 위 5의 "0건과 다른 거절의 구분": 장애 때 이탈이 잘못 기록될 수 있다(화면은 `empty_message`를 그대로 보여 줘야 함).
- `httpx`·`httpcore` 로거에 필터를 붙여, 같은 프로세스의 다른 httpx 로그의 `user_id=` 값도 가려진다(해당 값은 이 앱에서 `psearch`뿐이라 부작용은 작다고 판단하나 다른 사용처는 전수 확인하지 못했다).
- 조건별 잠금은 한 조건의 증권사 호출이 오래 걸리면(타임아웃 10초) 같은 조건의 요청이 그동안 대기한다. 다른 조건은 영향받지 않는다.
- 편입 시각·변화 기록은 메모리에만 있다(재기동·20개 한도 초과 시 초기화).
- 이 PC 하나만 쓰는 가정이다(프로세스 여러 개로 띄우면 캐시·호출이 프로세스마다 따로 생긴다).
