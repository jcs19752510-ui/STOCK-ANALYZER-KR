# UNIT-09 구현 노트 — 종목 검색 결과 화면 (프론트엔드)

- 작성 에이전트: 05-unit-developer
- 작성일: 2026-09-17
- 대상 REQ: REQ-001 (프론트엔드 부분 — 백엔드는 UNIT-03이 이미 완료)
- 입력: `docs/harness/02-planning.md`(v5) §9 UNIT-09 정의(DEC-019 신설 경위), §4-3(데이터 가공 원칙) / `docs/harness/03-system-design.md`(v4) §3-1-1(market 두 축), §3-2(`stock_master`), §4-2(`GET /api/v1/stocks` 명세) / `docs/harness/04-ux-design.md`(v3) §1-3 Flow C, §2-3(종목 검색 화면), §4(컴포넌트 명세) / `docs/harness/traceability.md` REQ-001 행(DEF-006/007) / `unit-03-note.md`(백엔드 API 계약), `unit-05-note.md`(GlobalNav/플레이스홀더), `unit-06-note.md`/`unit-06-test.md`(REQ-001 시퀀싱 공백 인계), `unit-07-note.md`(v2, `MarketFilterControl` 범용화·DEF-U07-01 교훈), `unit-08-note.md`(가장 최근 프론트엔드 유닛, 접근성 사전 점검 관행)

---

## 0. 이 유닛의 배경과 범위

UNIT-03은 `GET /api/v1/stocks?query=&market=` 백엔드만 구현했고, 그 화면(`/stocks`)은 UNIT-05가 404 방지용 임시 플레이스홀더로만 채워둔 상태였다. UNIT-06 개발·테스트 과정에서 "사용자가 종목코드를 몰라도 상세 화면(`/stocks/[code]`)에 도달할 UI 경로가 없다"는 WBS 공백이 발견되어 DEC-019로 UNIT-09가 신설됐다(`02-planning.md` v4 변경 이력). 이 유닛은 그 화면을 구현한다.

**범위**: `/stocks` 검색 UI(검색어 입력 + 시장 필터 + 결과 리스트 + 빈 상태/에러 상태) 구현, 기존 `/stocks/[code]`(UNIT-06)로의 이동 경로 제공. **범위 밖**: 백엔드 API 수정(UNIT-03 산출물 무변경), `/screener`·`/`(UNIT-07/08) 무변경, DEF-006/007(백엔드 결함, Low/Open) 자체 수정 — 이 유닛은 그 결함의 영향을 인지만 하고 아래 §2에 기록한다.

---

## 1. 구현 범위

### 1-1. `frontend/src/lib/stockSearchApi.ts` (신규)

`GET /api/v1/stocks?query=&market=` 클라이언트 fetch. `screenApi.ts`(UNIT-07)와 동일한 이유로 클라이언트 컴포넌트에서 직접 호출하는 구조를 택했다 — 타이핑마다 디바운스 조회를 해야 해서 서버 컴포넌트 fetch(페이지 전체 재내비게이션)로는 04-ux-design.md §1-3 Flow C("검색어 입력 → 로딩")를 만족할 수 없다. `unit-03-note.md` §1-4가 이미 확정한 대로 이 엔드포인트 응답에는 `meta.data_freshness`가 없으므로, 이 결과 타입에는 `freshness` 필드가 없다(다른 화면과의 불일치가 아니라 API 계약 자체가 그렇다).

### 1-2. `frontend/src/lib/types.ts` (수정)

`StockSearchItem`(`stock_code`/`name`/`market`) 타입 추가. `unit-03-note.md`의 백엔드 Pydantic `StockSearchItem`과 필드가 1:1 대응한다.

### 1-3. `frontend/src/components/SearchInput.tsx` (신규)

04-ux-design.md §4 `SearchInput` 명세 구현. `<label htmlFor>` + `<input type="search">` 표준 패턴(`ConditionField.tsx`가 이미 확립한 "placeholder만으로 라벨을 대체하지 않는다" 원칙 재사용). 콤보박스/리스트박스 ARIA 패턴을 쓰지 않는다 — §2-3 원문이 "자동완성 아님"을 명시하기 때문이다.

### 1-4. `frontend/src/components/StockListItem.tsx` (신규)

04-ux-design.md §2-3/§4 `StockListItem` 명세 구현(종목명 + 코드 + 시장 뱃지, `/stocks/{code}`로 이동). 시장 뱃지는 `/stocks/[code]`(UNIT-06)가 이미 쓰는 `.market-badge` 클래스를 그대로 재사용해 새 뱃지 스타일을 만들지 않았다.

### 1-5. `frontend/src/components/MarketFilterControl.tsx` (변경 없음, 재사용)

UNIT-07이 이 컴포넌트를 만들면서 자신의 docstring에 "종목검색(`/stocks`)은 REQ-001 프론트엔드 담당 유닛(UNIT-09) 범위이며, 이 컴포넌트를 그대로 재사용해야 한다"고 명시적으로 남겨둔 지시를 그대로 이행했다. 새 필터 컴포넌트를 만들지 않았고, `copy.screener.marketOption*` 라벨("전체"/"코스피"/"코스닥")도 그대로 재사용했다(화면이 다르다고 "종목검색용" 라벨을 새로 만들지 않음 — 텍스트가 동일하므로 중복 카피 리소스를 만드는 것이 오히려 유지보수 부담).

### 1-6. `frontend/src/components/EmptyState.tsx` (수정)

04-ux-design.md §4가 `EmptyState` 컴포넌트 변형으로 이미 정식 명명해 둔 `no-query`(검색 전)와 `no-search-result`(검색 결과 없음)를 추가했다 — 새 이름을 짓지 않고 설계서에 이미 있는 이름을 그대로 썼다. `no-search-result`는 문구에 사용자가 입력한 검색어를 그대로 삽입해야 하는 유일한 변형이라("'{검색어}'에 대한 검색 결과가 없습니다...", §1-3), 다른 정적 변형과 달리 `query` prop을 받아 `copy.emptyState.noSearchResultTemplate`의 `{query}` 자리를 치환하도록 컴포넌트를 확장했다(기존 `ScreenerClient`/`StockDetailPage`의 기존 호출부는 `query`를 넘기지 않아도 되므로 옵셔널 prop으로 처리, 회귀 없음).

### 1-7. `frontend/src/content/copy.ko.json` (수정)

`emptyState.noQueryTitle`/`noSearchResultTemplate`, `stockSearch.pageTitle`/`inputLabel`/`inputPlaceholder` 추가. 04-ux-design.md §1-3 Flow C 원문 문구를 그대로 옮겼다("종목명 또는 코드를 입력해 검색하세요", "'{검색어}'에 대한 검색 결과가 없습니다. 종목명 또는 코드를 다시 확인해 주세요.").

### 1-8. `frontend/src/components/StockSearchClient.tsx` (신규, 핵심)

`/stocks` 화면의 상태 관리를 담당하는 클라이언트 컴포넌트. `ScreenerClient.tsx`와 유사한 구조이나, 스크리닝은 "제출 버튼 클릭"으로 조회가 시작되는 반면 이 화면은 "타이핑 디바운스"로 조회가 시작된다는 점이 다르다.

- **디바운스**: `query` state를 300ms 뒤 `debouncedQuery`로 반영하는 `useEffect` + `setTimeout`(04-ux-design.md §1-3 "디바운스 300ms" 그대로).
- **최소 길이(2자)**: `debouncedQuery.trim().length < 2`이면 API를 호출하지 않고 `no-query` 빈 상태만 보여준다. 이 판단은 `useEffect` 내부의 `setState`가 아니라 **렌더링 시점에 계산된 파생값**(`isQueryTooShort`)으로 처리했다 — 아래 §2 편차 1에 이유를 상세히 남긴다.
- **시장 필터 변경**: 디바운스 없이 즉시 재조회 대상이 된다(타이핑이 아니라 버튼 클릭이므로 디바운스가 필요 없음). `useEffect` 의존성 배열에 `market`을 포함해 구현했다.
- **에러 처리**: `errorMapping.ts`(UNIT-06)의 `mapApiErrorCodeToDisplay()`를 그대로 재사용했다. `/stocks`는 `DATA_PIPELINE_STALE`을 반환할 일이 없지만(기준시각 개념이 없는 엔드포인트), 방어적으로 `display.kind === "empty"`가 나오는 경우도 빈 상태가 아니라 `ErrorState(network)`로 안내하도록 처리했다(무시하거나 크래시하지 않음).
- **재시도**: `ErrorState`의 `onRetry`가 `retryToken`을 증가시켜 동일 `useEffect`를 다시 실행시킨다(URL 기반 재시도가 불가능한 클라이언트 상태 흐름이라 `ScreenerClient`의 `handleRetry`와 동일한 패턴 채택).

### 1-9. `frontend/src/app/stocks/page.tsx` (교체)

UNIT-05의 임시 플레이스홀더를 실제 화면으로 교체했다. `"use client"` 컴포넌트는 `metadata`를 export할 수 없어 `/screener`(UNIT-07)와 동일하게 메타데이터 전용 서버 컴포넌트 셸 + 클라이언트 컴포넌트로 분리했다.

### 1-10. `frontend/src/app/globals.css` (수정)

`.stock-search-page__controls`/`.search-input*`/`.stock-list*` 클래스 추가. 기존 `.results-list`(UNIT-07)·`.market-badge`(UNIT-06)·`.condition-field__input`(UNIT-07) 스타일 관례를 재사용해 새 디자인 토큰을 만들지 않았다(입력 높이 44px 최소 터치 타겟, 카드 테두리/라운드 8px 등 기존 값 그대로).

---

## 2. 설계서 대비 편차 및 확인 필요 사항 (사유 포함)

1. **[구현 세부 결정] "질의 2자 미만" 상태를 `useEffect` 내부 `setState`가 아니라 렌더링 시점 파생값으로 처리**: 처음에는 `useEffect` 안에서 `if (trimmed.length < 2) { setState({kind:"idle"}); return; }` 형태로 작성했으나, `npm run lint`(`react-hooks/set-state-in-effect`)가 "effect 본문에서 다른 상태를 그대로 파생시키는 동기 `setState` 호출"로 지적했다(React 공식 가이드가 권장하는 "effect는 진짜 외부 시스템과의 동기화에만 쓰고, 다른 state로부터 계산 가능한 값은 렌더링 중 직접 계산하라"는 원칙과 정확히 일치하는 지적이었다). 이를 받아들여 `isQueryTooShort`를 렌더링 시점에 계산하는 파생값으로 바꾸고, 렌더링 JSX가 `isQueryTooShort`를 `state` 값보다 우선해 분기하도록 구조를 변경했다(`unit-05-note.md`의 `useIsDesktopViewport.ts`가 이미 쓰던 "지역 함수로 감싸 effect 최상위 직접 호출을 피한다" 관례도 데이터 페칭 시작(`setState({kind:"loading"})`) 쪽에 동일하게 적용했다). 사용자 질문으로 격상하지 않은 이유: 이는 REQ-001의 기능적 동작이나 화면 문구를 전혀 바꾸지 않는 순수 구현 세부 사항(정적 분석 게이트를 통과하기 위한 리팩터링)이며, 이 저장소가 이미 여러 차례 채택한 "설계 완성도/구현 세부 사안은 개발자가 직접 확정하고 근거를 남긴다" 관행과 동일한 성격이다.
2. **[방어적 구현, API 계약 확장 아님] `/stocks`의 페이지네이션 부재를 그대로 승계**: `unit-03-note.md` §2 편차5가 이미 남긴 대로, 백엔드는 `MAX_SEARCH_RESULTS=100` 내부 상한만 두고 API 파라미터로 페이지네이션을 노출하지 않는다. 04-ux-design.md §2-3도 `Pagination` 컴포넌트를 이 화면에 요구하지 않는다. 이 유닛은 그대로 페이지네이션 UI 없이 구현했다(새 계약을 임의로 만들지 않음).
3. **[인지, 수정 대상 아님] DEF-006(LIKE 와일드카드 미이스케이프, Low/Open) 영향 인지**: 사용자가 검색창에 `%`나 `_`를 입력하면 백엔드가 이를 SQL LIKE 와일드카드로 그대로 해석해 예상보다 넓은 범위가 매칭될 수 있다(`traceability.md` REQ-001 행, `unit-03-test.md` §6). 이 유닛은 프론트엔드 화면 담당이며 백엔드 결함 자체를 고치는 것은 범위 밖이다 — 별도의 클라이언트 측 이스케이프나 입력 제한도 추가하지 않았다(백엔드가 이미 Low/Open으로 배포 차단 사유가 아니라고 판정된 결함에 대해, 프론트가 임의로 새로운 검증 규칙을 얹으면 오히려 API 계약과 클라이언트 동작이 이원화되는 위험이 있다고 판단했다). 6단계가 이 화면에서 이 결함의 실제 사용자 영향(예: `%` 입력 시 전체 종목이 나열되는지)을 재확인할 것을 권고한다.
4. **[구현 세부 결정] 시장 필터 변경 시 검색어가 2자 미만이면 조회하지 않음**: 04-ux-design.md는 시장 필터만 바꾸고 검색어가 없는 경우의 동작을 명시하지 않는다(`/screener`와 달리 `/stocks`는 "검색어 없이 시장만으로 전체 목록 조회"가 Flow C 어디에도 서술되어 있지 않다 — §1-2 Flow B는 "시장 구분만 선택하고 조건 없이 적용 가능"이라고 명시하지만 §1-3 Flow C에는 대응 문장이 없다). 검색어 입력이 화면의 1차 진입점이라는 §2-3 본문("종목명/코드로 빠르게 찾아 상세로 이동하는 허브 화면")에 따라, 검색어 없이 시장 필터만으로 조회를 트리거하지 않도록 구현했다(무의미하게 넓은 결과 방지, MAX_SEARCH_RESULTS 상한과도 무관하지 않음 — 짧은/빈 질의로 전체 종목을 나열하는 것을 방지하는 편이 더 안전하다고 판단). 이 판단이 설계 의도와 다르면(즉 "시장만 선택해도 전체 목록을 보여줘야 한다"는 의도였다면) 재검토가 필요하다 — 6단계/오케스트레이터 확인 필요 항목으로 남긴다.

---

## 3. 수동으로 확인이 필요한 부분 (6단계 테스터에게, 특히 중요)

**이번 세션은 이 저장소가 UNIT-01~08에서 수행해 온 것과 같은 수준의 실 PostgreSQL 기반 "인증된 종단간"(`api_service` 자격증명으로 실제 HTTP 호출) 검증을 완료하지 못했다.** 이번 세션의 자동 승인 정책이 자격증명 관련 Bash 작업(예: `ALTER ROLE ... PASSWORD`로 로컬 `api_service` 비밀번호 설정, `-U api_service`로 직접 접속, `pg_hba.conf`/환경변수 조회)을 전부 거부했기 때문이다(이전 유닛들이 남긴 note에서는 `localdevpass` 등으로 직접 접속해 검증했으나, 이번 세션에서는 동일한 시도가 "Secret-Store Writes"/"Credential Exploration" 사유로 차단됨을 직접 확인했다). 이는 임의로 우회하지 않고 다음 두 가지 대체 검증으로 한정했다:

1. **데이터 계층 검증(대체)**: 로컬 Docker `stock-screener-db`에 UNIT-03/UNIT-08이 남긴 실제 `stock_master` 픽스처(6행)가 있음을 `postgres` 슈퍼유저 권한(자격증명 조회가 아닌, 이미 통상적으로 허용되는 관리자 조회)으로 확인했고, `SqlStockSearchRepository.search()`가 실제로 실행하는 SQL(`ILIKE '%query%'` OR 조건 + `market` 필터 + `is_active=true` + `ORDER BY stock_code LIMIT 100`)을 동일하게 직접 실행해 (a) 이름 부분일치("삼성" → 삼성전자 1건), (b) 시장 필터 조합("UNIT08" + `market='KOSDAQ'` → 3건), (c) 매치 없음(존재하지 않는 검색어 → 0행) 세 시나리오가 프론트엔드가 기대하는 `{stock_code, name, market}` 모양과 정확히 일치함을 확인했다.
2. **프론트엔드 SSR/빌드 검증**: `npm run build && npx next start`로 실제 프로덕션 서버를 띄우고 `curl`로 `/stocks`의 초기 HTML을 확인했다 — 면책 배너(REQ-007), `GlobalNav`(`/stocks`에 `aria-current="page"`, REQ-013), `<h1>종목 검색</h1>`, `SearchInput`(라벨/placeholder), `MarketFilterControl`(전체/코스피/코스닥, "전체" 초기 활성), 결과 영역의 `no-query` 빈 상태 문구("종목명 또는 코드를 입력해 검색하세요")가 전부 기대대로 렌더링됨을 확인했다. `/`, `/screener`, `/about`, `/stocks/005930`도 함께 curl로 200 OK 및 정상 폴백(백엔드 미기동 상태에서 `/stocks/005930`이 크래시 없이 `ErrorState(network)`로 대체됨)을 확인해 회귀가 없음을 확인했다.

**아직 확인되지 않은 것(6단계가 반드시 재현해야 함)**:
- **타이핑 → 디바운스(300ms) → 실제 `fetch` 호출 → 로딩 스켈레톤 → 결과 리스트/빈 상태/에러 렌더링으로 이어지는 실제 상호작용 전체**. 이는 브라우저(또는 헤드리스 브라우저, UNIT-07이 DEF-U07-01 재현에 썼던 Puppeteer 등)로만 관찰 가능하며, curl로는 확인할 수 없다(SSR HTML은 항상 초기 `no-query` 상태만 보여준다). `api_service` 자격증명으로 실제 FastAPI 서버를 띄워 브라우저에서 "삼성" 입력 → 결과 1건 표시, "존재하지않는검색어" 입력 → `no-search-result` 문구(검색어 삽입 확인 포함), 코스닥 필터 선택 시 필터 반영 여부까지 실측이 필요하다.
- **2자 미만 입력 시 실제로 API 호출이 발생하지 않는지**(네트워크 탭/서버 로그로 확인 — 코드 리뷰상으로는 `isQueryTooShort` 가드가 있으나 실제 브라우저 타이핑 이벤트로 재현되지 않았다).
- **시장 필터만 바꾸고 검색어가 비어 있을 때 정말 조회가 트리거되지 않는지**(§2 편차 4의 판단이 맞는지 포함해 재검토 권고).
- **429(요청 과다)/네트워크 오류 시 `ErrorState(rate-limited/network)`가 실제로 뜨고 "다시 시도"가 동작하는지**(백엔드가 429를 발생시키는 경로가 현재 없어 강제로 네트워크를 끊거나 mock 서버로 재현 필요).
- **DEF-006 영향 실측**: 검색창에 `%`를 입력했을 때 실제로 전체 종목이 나열되는지 브라우저로 확인하고, 사용자 경험상 문제가 되는 수준인지 재판단.
- **200% 확대/모바일 실기기 확인**: `unit-05-note.md`/`unit-07-note.md`가 이미 남긴 "실 브라우저 반응형/확대 확인 필요" 항목과 동일한 성격으로, 이 화면도 실 브라우저 확인이 없었다.

---

## 4. 인수 조건 (Acceptance Criteria) — 6단계 테스터용

**AC-1 (초기 상태 — 04-ux-design.md §1-3 Flow C)**
- `/stocks` 최초 진입 시(검색어 없음) 결과 영역에 "종목명 또는 코드를 입력해 검색하세요" 문구만 보이고, API 호출이 발생하지 않아야 한다(네트워크 탭으로 확인).
- 1자만 입력(예: "삼")하면 300ms 뒤에도 API가 호출되지 않고 동일한 초기 문구가 유지돼야 한다.

**AC-2 (디바운스 + 검색 성공 — §1-3)**
- 2자 이상 입력(예: "삼성") 후 300ms 이내에는 로딩 스켈레톤이, 300ms 경과 시점부터 `GET /api/v1/stocks?query=삼성&market=ALL` 요청이 정확히 1회(연속 타이핑 중에는 발생하지 않다가 타이핑을 멈춘 뒤 1회) 발생해야 한다.
- 요청 성공 + 결과 1건 이상이면 각 항목에 종목명, 종목코드, 시장 뱃지(코스피/코스닥)가 표시되고, 항목 클릭 시 `/stocks/{code}`로 이동해야 한다.

**AC-3 (검색 결과 없음 — §1-3)**
- 결과 0건이면 `'{검색어}'에 대한 검색 결과가 없습니다. 종목명 또는 코드를 다시 확인해 주세요.` 문구가 표시되고, `{검색어}` 자리에 실제 입력한 검색어가 정확히 삽입돼야 한다(예: "존재하지않는종목" 검색 시 "'존재하지않는종목'에 대한 검색 결과가...").

**AC-4 (시장 필터 — §2-3)**
- 시장 필터를 "코스피"/"코스닥"으로 바꾸면 `market=KOSPI`/`market=KOSDAQ` 파라미터로 즉시(디바운스 없이) 재조회되어야 한다(이미 2자 이상 검색어가 입력되어 있는 상태 기준).
- 검색어가 비어 있는 상태에서 시장 필터만 바꿔도 API 호출이 발생하지 않아야 한다(§2 편차 4 — 이 판단이 설계 의도와 맞는지 재검토 권고).

**AC-5 (에러/재시도 — §1-3, §1-4 Flow D 재사용)**
- 네트워크 오류/503/기타 오류 시 `ErrorState(network)`가 표시되고 "다시 시도" 클릭 시 동일 조건으로 재요청이 발생해야 한다.
- 429 발생 시 `ErrorState(rate-limited)`가 표시돼야 한다(강제 재현 필요).

**AC-6 (`/stocks/[code]` 연결 — REQ-001 시퀀싱 공백 해소 확인, `unit-06-test.md` 인계 사항)**
- `/stocks/{존재하지않는코드}` 접속 시 나타나는 404 화면의 "종목 검색으로 돌아가기" 링크를 클릭하면 실제로 `/stocks`로 이동하고, 그 화면에서 정상적으로 검색이 가능해야 한다(사용자가 종목코드를 몰라도 상세 화면에 도달할 수 있는 경로가 실제로 완성됐는지 종단간 확인).

**AC-7 (회귀 없음 — REQ-006/007/009/013)**
- `/stocks` 응답 HTML에 면책 배너(`class="disclaimer-banner"`)와 `GlobalNav`(`aria-current="page"`)가 그대로 존재해야 한다.
- `/stocks` 요청에 임의의 쿠키/Authorization 헤더를 붙여도 응답이 동일해야 한다(REQ-009 블랙박스 검증, UNIT-04/08이 확립한 패턴 재사용 권장).
- 이 화면에는 `DataFreshnessBadge`가 없어야 한다(설계상 의도 — `/stocks` API가 `data_freshness`를 반환하지 않으므로).

**AC-8 (접근성 사전 점검 재확인)**
- `git grep useFocusTrap frontend/src/app/stocks frontend/src/components/StockSearchClient.tsx frontend/src/components/SearchInput.tsx frontend/src/components/StockListItem.tsx` → 매치 없음이어야 한다(포커스 트랩 미사용을 코드 레벨로 재확인).
- 검색 입력에 `<label htmlFor>` 연결이 실제로 존재해야 한다(placeholder만으로 라벨 대체 금지).

**AC-9 (정적 분석 게이트)**
- `cd frontend && npx tsc --noEmit`, `npm run lint`, `npm run build` 모두 오류/경고 없이 통과해야 한다(빌드는 `prebuild` 금지어 검사 포함).
- `python -m pytest tests/unit -q`가 기존 151건 그대로 pass해야 한다(이 유닛은 백엔드 파일을 전혀 수정하지 않았으므로 회귀가 없어야 정상).

---

## 5. 게이트 1 — 정적 분석/린트 결과

이 프로젝트는 정적 분석/린트 설정이 **있다**(건너뛰지 않음).

- 프론트엔드: `npx tsc --noEmit` → 오류 없음.
- 프론트엔드: `npm run lint`(ESLint 9, `eslint-config-next`, `react-hooks` 규칙 포함) → 0 error, 0 warning. 최초 구현 시 `react-hooks/set-state-in-effect` 오류 1건이 발견되어 직접 수정했다(§2 편차 1 참조 — 6단계로 넘기지 않고 이 단계에서 해결).
- 프론트엔드: `npm run build`(`prebuild` 금지어 린트 포함) → "금지표현 검사 통과 (검사 파일 47개)" 후 `next build` 성공, 라우트 6개 정상 생성(`/`, `/_not-found`, `/about`, `/screener`, `/stocks`, `/stocks/[code]`).
- 백엔드: 이번 유닛은 백엔드 코드를 전혀 수정하지 않았다. `python -m ruff check .`/`python -m pytest tests/unit -q`(151 passed)는 회귀 없음 확인용으로만 재실행했다.

---

## 6. 게이트 2 — 자체 코드 리뷰 체크리스트

- [x] **설계서/디자인서 명세와 실제 구현이 일치하는가** — 04-ux-design.md §1-3 Flow C(디바운스 300ms, 2자 이상, 초기/로딩/결과있음/결과없음 상태), §2-3(구성 요소: `SearchInput`/`MarketFilterControl`/`StockListItem`), §4(컴포넌트 명세, `EmptyState` 변형명 `no-query`/`no-search-result` 그대로 사용)를 1:1로 구현했다. 편차 4건은 §2에 사유와 함께 명시했다.
- [x] **에러 처리가 누락된 경로가 없는가(예외를 삼키고 무시하는 코드 없음)** — `stockSearchApi.ts`는 `fetch` 실패(네트워크), `response.json()` 파싱 실패, `!response.ok`, `body.data`가 없는 경우 4갈래 모두 명시적으로 `{kind:"error", code, message}`를 반환한다(`try/catch`로 조용히 삼키는 코드 없음, `stockMetrics.ts`/`screenApi.ts`와 동일한 검증된 패턴). `StockSearchClient`의 `useEffect`도 `cancelled` 플래그로 경쟁 조건(빠른 연속 입력 시 이전 요청의 응답이 최신 상태를 덮어쓰는 것)을 방지한다.
- [x] **입력값 검증이 시스템 경계(사용자 입력, 외부 API 응답)에서 이루어지는가** — 사용자 입력 경계: 검색어 2자 미만은 API를 호출하지 않고, 시장 필터는 `MarketFilterControl`이 이미 화이트리스트(`ALL`/`KOSPI`/`KOSDAQ`) 값만 방출하므로 잘못된 값이 만들어질 수 없다. 외부 API 응답 경계: `stockSearchApi.ts`가 `body.data`가 `null`/누락인 경우를 `INVALID_RESPONSE`로 명시적으로 거부한다(응답을 신뢰하지 않고 검증). 실제 SQL 인젝션/이스케이프는 백엔드 소관(§2 편차 3에 DEF-006 인지 기록).
- [x] **하드코딩된 시크릿/자격증명이 없는가** — 이번 유닛은 프론트엔드 파일만 변경했고 시크릿/자격증명을 다루지 않는다. 로컬 검증 중 DB 접속은 이미 구동 중인 `postgres` 슈퍼유저 세션(자격증명을 새로 만들거나 코드/설정에 남기지 않음)으로만 수행했고, `api_service` 비밀번호를 설정/조회하려는 시도는 세션 정책에 의해 거부되어 시도 자체를 중단했다(§3 참조 — 우회하지 않음).
- [x] **신규 외부 의존성이 있다면 실존 여부를 확인했는가** — 신규 패키지 의존성 추가 없음(기존 React/Next.js만 사용, 새 npm 패키지 설치 없음 — `package.json`/`package-lock.json` 변경 없음을 `git status`로 확인).
- [x] **범위를 벗어난 변경(곁다리 리팩터링 등)이 섞여 있지 않은가** — 변경/신규 파일은 `frontend/src/lib/stockSearchApi.ts`(신규), `frontend/src/lib/types.ts`(타입 1개 추가), `frontend/src/components/{SearchInput,StockListItem,StockSearchClient}.tsx`(신규), `frontend/src/components/EmptyState.tsx`(변형 2개 추가), `frontend/src/content/copy.ko.json`(카피 추가), `frontend/src/app/stocks/page.tsx`(플레이스홀더 교체), `frontend/src/app/globals.css`(클래스 추가), `docs/harness/traceability.md`/`docs/harness/units/unit-09-note.md`뿐이다. `MarketFilterControl.tsx`/`ScreenerClient.tsx`/`StockDetailPage`/백엔드 파일은 전혀 수정하지 않았다.

---

## 7. 로컬 동작 확인 요약 (실행 로그 근거)

Docker Desktop이 기동 중이었고 로컬 Postgres 컨테이너(`stock-screener-db`)에 UNIT-03/08이 남긴 `stock_master` 픽스처(6행: 005930/000660/005935/900001/900002/900003)가 이미 있어 이를 그대로 재사용했다(새로 시딩하지 않음 — 코디네이터 지시대로 기존 픽스처와 종목코드가 겹치지 않음을 먼저 확인했다).

1. **정적 분석**: `npx tsc --noEmit`(오류 없음), `npm run lint`(0 error/0 warning, 개발 중 `react-hooks/set-state-in-effect` 1건 발견 후 즉시 수정), `npm run build`(금지표현 검사 통과 47개 파일 + 빌드 성공, `/stocks`가 `○ Static`으로 분류됨 — 클라이언트 컴포넌트가 실제 fetch를 마운트 후에만 수행하므로 `/screener`와 동일하게 정적 셸로 빌드되는 것이 정상).
2. **데이터 계층(대체 검증, §3 참조)**: `docker exec stock-screener-db psql -U postgres ...`로 백엔드 리포지토리와 동일한 SQL을 직접 실행 — `name/stock_code ILIKE '%삼성%'` → 1건("삼성전자(테스트픽스처)", KOSPI), `ILIKE '%UNIT08%' AND market='KOSDAQ'` → 3건, `ILIKE '%존재하지않음%'` → 0건. 프론트엔드가 기대하는 `{stock_code, name, market}` 형태와 정확히 일치함을 확인했다.
3. **프론트엔드 SSR(대체 검증, §3 참조)**: `npm run build && npx next start -p 4100`으로 실제 프로덕션 서버 구동 후 `curl`로 `/stocks`, `/`, `/screener`, `/about`, `/stocks/005930` 전부 HTTP 200 확인. `/stocks` 응답 HTML에서 면책 배너, `GlobalNav`(`aria-current="page"` on `/stocks`), `<h1>종목 검색</h1>`, `SearchInput`(라벨 "종목명 또는 코드 검색", placeholder "예: 삼성전자 또는 005930"), `MarketFilterControl`(전체 active), 결과 영역의 `no-query` 문구를 전부 확인했다. `/stocks/005930`은 백엔드 미기동 상태에서도 크래시 없이 `ErrorState(network)`로 대체됨을 확인(회귀 없음).
4. **회귀**: `python -m pytest tests/unit -q`(151 passed, 이번 유닛의 신규 실패 없음), `python -m ruff check .`(All checks passed) 재확인.
5. **미수행(§3에 상세 사유 기록)**: `api_service` 자격증명 기반 실 HTTP 종단간 호출, 실제 타이핑→디바운스→렌더링 상호작용의 브라우저 기반 검증. 이번 세션의 자격증명 관련 Bash 작업 자동 거부 정책 때문이며, 우회를 시도하지 않고 §3에 6단계 인계 사항으로 명시했다.

**정리(Teardown)**: 이번 유닛은 DB에 새 데이터를 쓰지 않았다(읽기 전용 SQL만 실행). `next start` 임시 프로세스는 검증 후 종료했다. 새로 생성한 임시 파일(`src/__tmp_lint_test__/`, 린트 규칙 동작 확인용)은 검증 직후 삭제했다.

---

## 8. 다음 단계

- 6단계(단위테스트, `06-unit-tester`)를 이 노트에 대해 즉시 호출해야 한다.
- 6단계는 특히 **§3에 명시한 "실 자격증명 기반 종단간 HTTP 호출"과 "브라우저 기반 상호작용(디바운스/렌더링) 검증"을 독립적으로 수행**해야 한다 — 이번 세션은 도구 정책상 이 두 가지를 수행하지 못했으며, 이는 신뢰 부족이 아니라 이 세션에 국한된 도구 제약임을 명확히 인지시킨다.
- §2 편차 4("시장 필터만 바꾸고 검색어가 없을 때 조회하지 않음")가 설계 의도와 맞는지 오케스트레이터/6단계가 재검토할 것을 권고한다.
- REQ-001 프론트엔드 부분 및 백엔드 부분(UNIT-03, 이미 PASS)이 모두 완료됨에 따라 REQ-001 전체가 07단계(통합테스트) 진행 후보가 될 수 있는지는 6단계 PASS 판정 이후 오케스트레이터가 결정한다.
