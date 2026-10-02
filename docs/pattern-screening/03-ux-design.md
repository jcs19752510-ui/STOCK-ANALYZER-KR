# 03. 디자인서(UX/UI) — 패턴 스크리닝 "급등 전 압축주"

- 작성일: 2026-10-02 (KST) · 버전: v1 → 검증 후 v2(최종)
- 입력: [01 기획서](01-planning.md), [02 설계서](02-system-design.md), 기존 `docs/harness/04-ux-design.md`(토큰·컴포넌트·접근성 기준 승계), 실제 `frontend/src` 코드
- 원칙: **기존 디자인 시스템·카피 규칙(REQ-007/008/013)을 그대로 따른다.** 새 토큰을 만들지 않는다.

## 0. 디자인 목표 (사용자·규제 관점)

1. 사용자가 증권사 앱에서 눈으로 하던 대조를 **조건별 체크표**로 한눈에 본다.
2. 화면은 종목을 "판단"하지 않는다. **충족/미충족/산정 불가**를 사실로 보여 주고, 각 판정의 **근거 수치와 기준값**을 항상 함께 보여 준다(블랙박스 금지).
3. 데이터가 부족하면 감추지 않고 **이유와 함께** 말한다(REQ-035).
4. 사용자 결정(명칭 "급등 전 압축주" 유지)을 따르되, **예측·권유가 아님을 화면이 스스로 고지**한다(REQ-034). 점수·순위·"유력" 같은 서열 표현은 쓰지 않는다.

## 1. 정보 구조와 내비게이션

```
/screener            (기존: 직접 조건 설정)   ←→   /screener/pattern  (신규: "급등 전 압축주")
```

- 두 화면 상단에 **스크리닝 방식 전환 링크 2개**를 둔다. ARIA `tablist`가 아니라 **페이지 이동 링크**(`<nav aria-label="스크리닝 방식">` + 현재 항목 `aria-current="page"`)다 — 실제로 라우트가 바뀌기 때문.
- `GlobalNav`의 "조건 스크리닝" 활성 판정은 접두 일치(`/screener`)라 `/screener/pattern`에서도 활성 유지(기존 `isActive` 동작, UNIT-05가 `/screenerxyz` 충돌까지 검증함 — 회귀 TC 포함).
- 기능 스위치 off(`NEXT_PUBLIC_PATTERN_SCREEN_ENABLED="false"`)면 **전환 링크를 렌더하지 않고** `/screener/pattern`은 `notFound()`.

## 2. 화면 구성 — `/screener/pattern`

### 2-1. 데스크톱 (≥ 1024px) 와이어프레임

```
┌ DisclaimerBanner(고정, 기존) ──────────────────────────────────────────────┐
├ GlobalNav ────────────────────────────────────────────────────────────────┤
│ [직접 조건 설정]  [급등 전 압축주]◀현재        DataFreshnessBadge          │
│ ┌ InlineNotice(info) ──────────────────────────────────────────────────┐ │
│ │ ⓘ 이 목록은 가격·거래량 흐름이 아래 수치 조건에 해당하는 종목을 기계적으로 │ │
│ │   표시한 것입니다. 이후의 주가 움직임을 예측하거나 매수·매도를 권유하는   │ │
│ │   정보가 아닙니다.                                                      │ │
│ └────────────────────────────────────────────────────────────────────────┘ │
│ ┌ 좌: PatternFilterPanel ──┐  ┌ 우: 결과 ────────────────────────────────┐ │
│ │ 시장  (전체|코스피|코스닥)│  │ 조건 충족 종목 목록 (총 12건)  평가 2,650/2,760 │ │
│ │ 최소 시가총액(억원) [500] │  │ ┌──────┬────┬────┬────┬────┬────┬────┐ │ │
│ │ 최소 거래량(주) [100000]  │  │ │종목  │긴  │이평│60일│60일│거래│급등│ │ │
│ │ 필수 적용 조건            │  │ │      │횡보│수렴│접근│돌파│량  │이력│ │ │
│ │ ☑ 긴 횡보  ☑ 이평선 수렴  │  │ ├──────┼────┼────┼────┼────┼────┼────┤ │ │
│ │ ☑ 60일선 접근 ☑ 돌파 단계 │  │ │OO전자│✓충족│✓충족│✓충족│✓직전│✓충족│✓없음│ │ │
│ │ ☑ 거래량 ☑ 급등 이력      │  │ │005930│18.2%│1.9%│-1.4%│    │1.3배│    │ │ │
│ │ [조건 적용]               │  │ └──────┴────┴────┴────┴────┴────┴────┘ │ │
│ └───────────────────────────┘  │ Pagination                              │ │
│ ▸ 조건 정의와 기준값 (펼치기)    └──────────────────────────────────────────┘ │
├ Footer(기존) ─────────────────────────────────────────────────────────────┤
```

### 2-2. 모바일 (< 1024px, 기준 폭 320~767)

- 전환 링크 → 고지(InlineNotice) → **`조건 설정` 버튼**(바텀시트 열기, 기존 `ConditionFilterPanel` 모바일 패턴·포커스 트랩 재사용) → 결과 **카드 리스트** → Pagination → "조건 정의와 기준값".
- 카드 1개 = 종목명·코드·시장 뱃지 + **조건 6행 체크리스트**(`<dl>`): 각 행 `조건명 | 상태 배지 | 근거 문장`.
- 표 대신 카드를 쓰는 분기점은 **1024px**(기존 결과 목록의 768px과 다름): 조건 열이 6개라 768px에서 가로 스크롤 없이 읽히지 않기 때문. 가로 페이지 스크롤은 어떤 폭에서도 만들지 않는다(기존 규칙).

## 3. 조건 표시 규칙

### 3-1. 상태 배지 (`ConditionStatusBadge`) — 색에만 의존하지 않는다

| 상태 | 글리프 | 텍스트 | 스타일(기존 토큰) | 스크린리더 |
|---|---|---|---|---|
| `met=true` | ✓ | 충족 | `color.brand.primary` 글자·1px 테두리, `surface.subtle` 배경 | "충족" |
| `met=false` | ✕ | 미충족 | `color.text.secondary` 글자·`border.default` | "미충족" |
| `met=null` | – | 산정 불가 | `color.semantic.warning` 글자, 사유 줄 병기 | "산정 불가, 사유: {reason}" |

- 글리프는 `aria-hidden`, **텍스트는 항상 보인다**(툴팁에만 의존 금지). 사유(`reason`)는 배지 아래 보조 줄로 **항상 표시**: `INSUFFICIENT_HISTORY`→"시세 기간 부족", `SUSPECT_PRICE_JUMP`→"시세 단절 의심(액면분할 등)", `METRIC_UNAVAILABLE`→"지표 산출 불가".
- 상승/하락 색(`semantic.up/down`)은 **쓰지 않는다**(등락 표시가 아니므로 오독 방지).

### 3-2. 조건별 이름·근거 문장 (원문 번호 대신 이름을 쓴다 — ⑤→⑨ 건너뜀 혼동 방지)

| 조건 | 열 제목 | 근거 문장(값은 API `metrics`, 기준은 `definition`에서 주입) |
|---|---|---|
| c1 | 긴 횡보 | "횡보 폭 {range}% · {lookback}거래일 변화 {net}%" |
| c2 | 이평선 수렴 | "이평선 간격 {conv}% · 변동성 수축비 {ratio}" |
| c3 | 60일선 접근 | "60일선 대비 {gap}% · 20일선과 60일선 간격 {x}%" |
| c4 | 60일선 돌파 단계 | 단계 문구(서버 `ma60_stage`): `BELOW_NEAR`→"돌파 직전", `CROSS_EARLY`→"돌파 초입({n}일 전 상향 돌파)", `EXTENDED`→"이미 60일선을 크게 상회", `BELOW_FAR`→"60일선 한참 아래", `ABOVE_SETTLED`→"60일선 위에 안착" |
| c5 | 거래량 | "최근 5일 거래량이 60일 평균의 {vr}배" |
| c9 | 급등 이력 | "최근 {surge_days}거래일 내 급등·거래량 급증 이력 {없음/있음}" |

- 숫자 서식: 부호 필수(`+1.4%`/`-1.4%`, 기존 규칙), 소수 1자리(%)·2자리(배/비), 기존 `formatPercent.ts` 재사용. 값이 `null`이면 "—".
- **문장은 단정·권유 금지**: "~임/~입니다"는 정의 설명에만, 상태 표시는 사실형.

### 3-3. 조건 정의 패널 (`PatternDefinitionPanel`, `<details>`/`<summary>` 기본 접힘)

- 제목: "조건 정의와 기준값". 내용은 **API `definition`을 그대로 렌더**한다(하드코딩 금지 → 설정 변경 시 화면이 자동으로 정확).
- 각 조건: 이름 + 규칙 문장(예: "최근 80거래일 종가의 최고·최저 폭이 평균의 40% 이하이고, 기간 시작 대비 변화가 ±15% 이내") + 계산 기준("종가·거래량 일봉 기준").
- 하단 고정 안내 2줄:
  1. "거래량·급등 이력은 '바닥권 거래량'과 '뉴스 반영 여부'를 직접 확인하는 것이 아니라, 가격·거래량 기록으로 대신 점검하는 **대리 지표**입니다."
  2. "외국인·기관 수급과 실적 조건은 아직 반영되지 않았습니다."

## 4. 신규 컴포넌트 명세

| 컴포넌트 | 목적 | 상태/변형 | 재사용 |
|---|---|---|---|
| `ScreeningModeNav` | 두 스크리닝 방식 전환 링크 | 현재/비현재(`aria-current`), 스위치 off 시 미렌더 | `GlobalNav` 스타일 |
| `PatternNotice` | 비예측 고지(상시) | 단일 | `InlineNotice`(`info` 변형), **닫기 버튼 없음** |
| `PatternFilterPanel` | 시장·최소 시총·최소 거래량·필수 조건 체크 | 기본/오류/비활성(로딩) | `MarketFilterControl`·`ConditionField`·바텀시트 패턴 |
| `ConditionStatusBadge` | §3-1 | 충족/미충족/산정 불가 | 신규 |
| `PatternResultsTable` | ≥1024 결과 표 | 정상/로딩 | `ResultsTable` 구조 |
| `PatternResultsList` | <1024 카드 리스트 | 정상/로딩 | `ResultsList` 구조 |
| `PatternDefinitionPanel` | §3-3 | 접힘/펼침 | 신규 |
| `ReadinessNote` | "평가 {evaluated}/{total}종목, 나머지는 산정 불가" 보조 줄 | `ready_ratio<1`일 때만 | `InlineNotice`(`info`) |

`EmptyState`에 변형 `pattern-data-not-ready` 추가, `errorMapping.ts`에 `PATTERN_DATA_NOT_READY → {kind:"empty", variant:"pattern-data-not-ready"}`. `mapApiErrorCodeToDisplay`의 기존 분기는 불변.

## 5. 상태 설계

| 상태 | 표시 | 비고 |
|---|---|---|
| 초기 | **페이지 진입 즉시 기본값으로 1회 자동 조회**(프리셋 화면이라 "조건 적용" 클릭 없이 결과를 본다) | 기본값: 시장 전체, 최소 시총 500억, 최소 거래량 100,000주(기존 `DEFAULT_SCREEN_FORM_VALUES`와 동일 상수 재사용), 필수 조건 6개 전부 |
| 로딩 | 결과 영역만 스켈레톤(행 5개, 실제 높이 고정 — CLS 방지), 필터는 조작 가능, [조건 적용] 비활성+스피너 | 기존 §2-2와 동일 |
| 정상 | 총 건수·평가 종목 수·표/카드 | 결과 영역 `aria-live="polite"`로 "총 N건" 안내 |
| 결과 0건 | "조건을 모두 충족하는 종목이 없습니다. 필수 조건을 줄이거나 시장·기준 범위를 바꿔 다시 확인해 보세요." | **"추천 조건" 같은 대안 제시 금지**(기존 규칙). 위 문구는 사용자가 직접 바꿀 수 있는 항목을 안내할 뿐 특정 값을 제안하지 않는다 |
| 데이터 준비 중(`PATTERN_DATA_NOT_READY`) | EmptyState `pattern-data-not-ready`: "패턴 지표 산출에 필요한 시세 기간이 아직 부족합니다. 데이터가 준비되면 이용할 수 있습니다." | 에러(빨강) 아님 — 정상적 준비 단계 |
| 일부 종목만 산정 | `ReadinessNote` + 해당 행은 "산정 불가(사유)" | 조용한 제외 금지 |
| 오류 | `ErrorState` 변형 재사용: network(503)·calendar-not-confirmed(424)·rate-limited(429) | 기존 Flow D |
| 검증 오류 | 필수 조건을 모두 해제 → 인라인 오류 "필수로 적용할 조건을 하나 이상 선택해 주세요." + 포커스 이동 | 클라이언트 검증(서버도 400) |
| 스위치 off | 링크 미노출·라우트 404 | §1 |

## 6. 라우트·파일 구조 (UNIT-17에서 구현)

```
frontend/src/app/screener/pattern/page.tsx          서버 컴포넌트 셸 + metadata + (스위치 off → notFound())
frontend/src/components/PatternScreenerClient.tsx   "use client" — 상태·fetch(ScreenerClient 패턴 동일)
frontend/src/components/{ScreeningModeNav,PatternFilterPanel,ConditionStatusBadge,
                         PatternResultsTable,PatternResultsList,PatternDefinitionPanel,ReadinessNote}.tsx
frontend/src/lib/patternApi.ts                      fetchPatternResults(), 응답 타입
frontend/src/lib/patternValidation.ts               required 검증(순수 함수)
```
- `app/screener/page.tsx`에는 `ScreeningModeNav` 1줄만 추가(기존 동작 불변).
- 새 `types.ts` 타입은 서버 응답 화이트리스트와 동일 필드만 선언한다.

## 7. 카피(문구) — `copy.ko.json`의 `pattern` 키 (명칭 단일 출처)

| 키 | 값 | 비고 |
|---|---|---|
| `pattern.label` | **급등 전 압축주** | 사용자 결정(DEC-032). **이 키 한 곳만 바꾸면 전 화면 반영** — 법률 검토 결과 대응용 |
| `pattern.pageTitle` | `{label} | 국내주식 조건 스크리닝 정보 서비스` | `metadata.title`도 이 키 조합 |
| `pattern.modeNavAriaLabel` | 스크리닝 방식 | |
| `pattern.modeManualLabel` | 직접 조건 설정 | |
| `pattern.notice` | 이 목록은 가격·거래량 흐름이 아래 수치 조건에 해당하는 종목을 기계적으로 표시한 것입니다. 이후의 주가 움직임을 예측하거나 매수·매도를 권유하는 정보가 아닙니다. | 상시·닫기 불가 |
| `pattern.resultsHeading` | 조건 충족 종목 목록 (총 {total_count}건) | 기존 제목 규칙 |
| `pattern.readinessNote` | 시세 기간이 충분한 {evaluated}/{total}종목을 평가했습니다. 나머지는 '산정 불가'로 표시됩니다. | |
| `pattern.status.met` / `unmet` / `unavailable` | 충족 / 미충족 / 산정 불가 | |
| `pattern.reason.*` | 시세 기간 부족 / 시세 단절 의심(액면분할 등) / 지표 산출 불가 | |
| `pattern.requiredHeading` | 필수로 적용할 조건 | |
| `pattern.requiredError` | 필수로 적용할 조건을 하나 이상 선택해 주세요. | |
| `pattern.emptyResult` | 조건을 모두 충족하는 종목이 없습니다. 필수 조건을 줄이거나 시장·기준 범위를 바꿔 다시 확인해 보세요. | |
| `pattern.notReady` | 패턴 지표 산출에 필요한 시세 기간이 아직 부족합니다. 데이터가 준비되면 이용할 수 있습니다. | |
| `pattern.definitionHeading` | 조건 정의와 기준값 | |
| `pattern.proxyFootnote` | 거래량·급등 이력은 '바닥권 거래량'과 '뉴스 반영 여부'를 직접 확인하는 것이 아니라, 가격·거래량 기록으로 대신 점검하는 대리 지표입니다. | |
| `pattern.scopeFootnote` | 외국인·기관 수급과 실적 조건은 아직 반영되지 않았습니다. | |

- **금지어 자체 점검(작성 시점)**: `FORBIDDEN_TERMS`(추천·매수신호·매도신호·수익보장·손실보전·원금보장·지금 사세요·매수 타이밍·베스트 종목·확실한·안전한 조건)와 정규식 패턴을 **공백 제거 후** 대조 — 위 문구 전부 비해당. 실제 린트 실행은 UNIT-17 완료 조건이며, 검증 로그에 코드로 재현한 결과를 남긴다.
- "급등"은 린트 목록에 없으나 취지상 위험 표현이다 → 사용처를 `pattern.label` 1곳과 이를 보간하는 제목/링크로 **한정**한다. 다른 문구(`notice`·정의·푸트노트)에는 "급등"을 쓰지 않는다(예외: `recent_surge_flag` 근거 문장의 "급등·거래량 급증 이력" — 과거 사실 표기).

## 8. 접근성 (WCAG 2.1 AA, 기존 §5 승계 + 이 화면 추가)

| 항목 | 기준 |
|---|---|
| 키보드 | 전 컨트롤 Tab 도달, `ScreeningModeNav`→필터→결과→페이지네이션 순서, 바텀시트는 기존 `useFocusTrap` 사용·ESC 닫기·닫힌 뒤 트리거로 포커스 복귀 |
| 표 의미 | `<table>`+`<caption>`(sr-only: "패턴 조건 충족 여부"), 열 `scope="col"`, 종목명 셀 `scope="row"` |
| 색 | 상태는 글리프+텍스트로 구분, 대비 본문 4.5:1·UI 3:1(기존 토큰 값 그대로) |
| 라이브 영역 | 결과 총 건수 `aria-live="polite"`, 로딩 `aria-busy` |
| 타깃 크기 | 터치 컨트롤 최소 44×44px |
| 리플로우 | 320px·200% 확대에서 가로 페이지 스크롤 없음(카드 레이아웃) |
| 모션 | `prefers-reduced-motion` 시 스켈레톤 펄스 제거(기존) |
| 오류 연결 | `aria-invalid`/`aria-describedby`, 첫 오류 필드 포커스(기존 `SCREEN_FIELD_IDS` 패턴 확장) |
| 정의 패널 | `<details>` 네이티브(키보드·스크린리더 기본 지원) |

## 9. 요구사항 ↔ 화면 매핑

| REQ | 화면 요소 |
|---|---|
| REQ-033 | §2~§6 전체 |
| REQ-034 | `PatternNotice`, `pattern.label` 단일 출처, 서열 표현 없음(§0-4, §7) |
| REQ-035 | `ConditionStatusBadge` 산정 불가+사유, `ReadinessNote`, EmptyState `pattern-data-not-ready` |
| REQ-007/013 | 기존 `DisclaimerBanner`(layout 고정)·반응형 규칙 승계 |
