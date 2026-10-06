# 증권사 조건검색 화면 — API 계약서 (DEC-088)

- 작성일: 2026-10-06 / 상태: **확정(백엔드·화면이 이 문서만 보고 병렬 개발)** / 관련: `docs/ops/local-psearch-guide.md`, `scripts/kis_psearch_smoke_test.py`, `services/public_api/intraday/kis_client.py`(`psearch_titles`·`psearch_result`)
- 한 줄 요약: 내 HTS에 "서버저장"한 조건검색식의 결과 종목을 **내 PC(로컬 모드)에서 관리자만** 사이트 화면에서 본다. 판정은 증권사가 하고 사이트는 결과 종목을 보여 줄 뿐이다. 가격은 기존 준실시간 시세(`useQuotes`)로 채운다.

## 1. 범위와 접근 통제
- 로컬 모드 전용. 기존 `local_realtime.require_owner`(로컬 모드 4중 통제 + 로그인을 켠 환경은 관리자만)를 그대로 쓴다. 운영(Render) 빌드·일반 회원·로그인 안 한 사용자에게는 화면 요소도 요청도 없다.
- 설정: `.env`의 `KIS_HTS_ID`(내 HTS 로그인 ID, 비밀번호 아님)를 `IntradaySettings.hts_id`로 읽는다. 없으면 두 API 모두 `PSEARCH_NOT_CONFIGURED`.
- **HTS ID·앱키는 응답·로그·오류 메시지 어디에도 나오지 않는다.**
- 웹 서버 대행(BFF) 허용 경로: `/api/v1/local/psearch/conditions`, `/api/v1/local/psearch/results` (조회 GET만, `LOCAL_ALLOWED`와 `LOCAL_ADMIN_ONLY` 모두).

## 2. 응답 봉투·오류
기존 API와 같은 봉투: 성공 `{"data": {...}, "error": null}`, 실패 HTTP 상태 + `{"data": null, "error": {"code": "...", "message": "..."}}`(기존 `ApiError` 사용). 응답 헤더 `Cache-Control: no-store`.

| 상황 | HTTP | error.code |
|---|---|---|
| 로컬 모드 꺼짐·허용 밖 접속 | 404 | (기존 `require_local_mode` 그대로) |
| 관리자 아님 | 403 | (기존 `require_owner` 그대로) |
| 앱키 없음 | 503 | `LOCAL_INTRADAY_NOT_CONFIGURED` (기존 `local_market._not_configured`와 같은 문구) |
| HTS ID 없음 | 503 | `PSEARCH_NOT_CONFIGURED` — "HTS ID가 설정되지 않았습니다. .env의 KIS_HTS_ID를 확인하세요." |
| `seq`가 영숫자 1~10자가 아님 | 400 | `INVALID_SEQ` |
| 증권사 호출 한도 | 429 | `RATE_LIMITED` |
| 증권사 연결 불가·인증 실패 등 | 502 | `UPSTREAM_UNAVAILABLE` (증권사 문구는 비밀값을 가린 뒤에만 `message`에 포함) |
| 조건 목록 조회 거절(HTS ID 불일치·서버저장 없음 등) | 502 | `PSEARCH_REJECTED` — message에 가린 증권사 문구 |

## 3. `GET /api/v1/local/psearch/conditions`
내 조건 목록. 서버가 **60초 캐시**한다(여러 화면이 열려도 증권사 호출은 늘지 않는다).
```ts
interface PsearchConditions {
  conditions: { seq: string; group: string; name: string }[]; // 빈 배열 가능(서버저장한 조건이 없음)
  fetched_at: number; // epoch 초
}
```

## 4. `GET /api/v1/local/psearch/results?seq=0`
조건 하나의 현재 결과. **응답 필드 이름이 확정되지 않았으므로 종목코드만 필수**로 한다(증권사 행에서 종목코드 필드를 `code`·`stck_shrn_iscd`·`mksc_shrn_iscd`·`jong_code`·`stock_code` 순으로 찾고, 없으면 6자리 영숫자 값을 가진 첫 필드를 쓴다 — `scripts/kis_psearch_smoke_test.py`의 `row_code`와 같은 규칙).
```ts
interface PsearchResults {
  seq: string;
  items: {
    code: string;            // 6자리 종목코드
    name: string | null;     // 증권사 행의 이름(name/hts_kor_isnm/stock_name) → 없으면 종목 마스터 → 없으면 null
    market: string | null;   // 종목 마스터(KOSPI/KOSDAQ 등) → 없으면 null
    entered_at: number;      // 이 서버가 이 종목을 처음 본(편입한) 시각 epoch 초. 서버를 재기동하면 처음 본 시각부터 다시 센다
  }[];                       // 증권사 순서 유지, 최대 100건
  count: number;             // items 길이
  capped: boolean;           // 100건 한도에 닿음(조건을 더 좁혀야 전체를 볼 수 있음)
  empty: boolean;            // 증권사가 0건(오류 응답)을 돌려줌 → items는 빈 배열
  empty_message: string | null; // empty일 때 증권사 문구(비밀값 제거·120자 이내), 아니면 null
  changes: { at: number; added: string[]; removed: string[] }[]; // 이 서버가 본 최근 변화(편입·이탈) 최대 20건, 최신이 앞
  fields: string[];          // 증권사 행 필드 이름 목록(진단용, 첫 비어 있지 않은 응답 기준)
  fetched_at: number;        // 증권사에서 이 결과를 받은 시각 epoch 초
  age_seconds: number;       // 지금 - fetched_at
  cache_ttl_seconds: number; // 서버가 결과를 재사용하는 시간(= 화면이 이보다 자주 물을 필요 없음)
  stale: boolean;            // 최근 증권사 호출이 실패해 이전 결과를 돌려주는 중
}
```
서버 동작 규칙(백엔드):
1. **캐시**: 조건(seq)별로 `KIS_PSEARCH_CACHE_SECONDS`(기본 5, 최소 2, 최대 60)초 동안 마지막 결과를 재사용한다. 동시에 여러 요청이 와도 증권사 호출은 한 번(조건별 잠금). seq 종류는 최대 20개까지만 보관.
2. **편입·이탈 추적**: 새 결과와 직전 결과의 종목 집합을 비교해 `entered_at`과 `changes`를 갱신한다. 첫 조회는 `changes`에 넣지 않는다.
3. **증권사가 0건(오류 응답, `KisError("UPSTREAM_ERROR")`)이면** HTTP 200 + `empty: true`로 돌려주고(오류로 취급하지 않음) 직전 종목이 있었다면 `changes`에 전부 이탈로 기록한다. (조건 키 오류와 0건이 같은 코드일 수 있으므로 `empty_message`를 화면에 그대로 보여 준다.)
4. **호출 실패(`RATE_LIMITED`·`UPSTREAM_UNAVAILABLE` 등)**: 이전 결과가 있으면 그것을 `stale: true`로 돌려주고, 없으면 위 표의 오류를 돌려준다.
5. 증권사 호출은 기존 `KisClient`(토큰·호출 간격 공유, `shared_intraday_service(settings).client`)를 쓰며 블로킹이라 `asyncio.to_thread`로 실행한다. 상세 화면 호출에 양보하는 낮은 우선순위(`low_priority`)로 부르는 것이 바람직하다(`KisClient._get`의 `low_priority`; 필요하면 `psearch_*`에 선택 인자 추가).
6. 가격은 이 API에 넣지 않는다(화면이 기존 `useQuotes(codes)`로 준실시간 값을 채운다).

## 5. 화면(프런트) 규칙
- 새 화면 `/screener/broker`("증권사 조건검색"). 스크리닝 방식 전환(`ScreeningModeNav`)에 세 번째 항목을 **로컬 모드 관리자에게만** 보인다: 서버 렌더에서는 보이지 않고, 브라우저에서 `localIntradayAvailable()`이 참이고 `/api/v1/local/psearch/conditions`가 200일 때만 나타난다(403·404·503이면 항목도 화면 내용도 없음).
- 조건 선택(목록의 `group · name`), 결과 표(종목명(코드), 시장, **현재가=`useQuotes`의 준실시간 값(`QuoteText` 재사용)**, 편입 시각), 새로 들어온 종목 강조(색에만 의존하지 않음: "신규" 글자), 이탈 종목 변화 목록(`changes`).
- 자동 갱신: `max(5초, cache_ttl_seconds)` 간격, 탭이 가려지면 중지, 403·404·503은 다시 묻지 않음, 실패 시 간격 증가(상한 30초). 화면에 **"마지막 조회 시각"**과 `stale`·`capped`·`empty` 안내를 보여 준다. "실시간 보장" 문구는 쓰지 않는다.
- 안내문(한 줄): "증권사 HTS 조건검색 결과입니다(본인 전용). 조건 판정은 증권사가 하며 이 사이트는 결과를 표시만 합니다. 투자 권유가 아닙니다." — `npm run lint:copy`(금지표현 검사)를 통과해야 한다.
- 운영 빌드(로컬 플래그 꺼짐)에서는 탭·화면·요청이 전혀 없어야 한다.

## 6. 시험 기대(공통)
- 백엔드: 실제 uvicorn + 모의 증권사(`scripts/mock_kis_server.py`의 psearch: seq 0=호출 3번마다 한 종목 편입·이탈, seq 1=0건 오류, seq 2=100건)로 위 규칙 전부.
- 화면: 순수 로직 시험 + 실제 브라우저(가짜 JSON 서버 또는 하네스)로 폭 320~1280·접근성(axe)·폴링 간격·운영 빌드 비노출.
- 최종 종단(실제 스택: 로그인 + 웹 서버 대행 + API + 모의 증권사)은 합치는 단계에서 메인이 수행한다.
