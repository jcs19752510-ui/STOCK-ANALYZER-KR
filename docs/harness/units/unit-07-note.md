# UNIT-07 구현 노트 — 조건 기반 스크리닝 기능

- 작성 에이전트: 05-unit-developer
- 작성일: 2026-09-17 (최초), 2026-09-17 재작업(v2 — DEF-U07-01 대응)
- 포함 REQ: REQ-003(조건 기반 스크리닝 — 다중 조건 조합 필터링, 결과는 조건 충족 여부·근거 가공 지표 값 위주 표시)
- 입력(최초): `docs/harness/02-planning.md`(v5) §4-3(데이터 가공 원칙), §9 UNIT-07 정의 / `docs/harness/03-system-design.md`(v4, PASS) §3-1-1(market 두 축)·§3-2(`derived_metrics_daily`)·§4-1(공통 원칙, 사용자 식별 파라미터 금지)·§4-2(`GET /screen` API 명세, `matched_metrics` 규칙·`sort_by` 기본값)·§4-3(응답 화이트리스트)·§5-1(인덱스) / `docs/harness/04-ux-design.md`(v3, PASS) §1-2(Flow B)·§2-2(스크리닝 화면 상세)·§2-6(금지표현 대조표)·§4(공통 컴포넌트: `MarketFilterControl`/`ConditionFilterPanel`/`ConditionField`/`SortControl`/`ResultsTable`/`ResultsList`/`Pagination`/`EmptyState`/`ErrorState`)·§5(접근성, 포커스 트랩)·§6(반응형) / `docs/harness/decisions.md` DEC-011~015 / `docs/harness/units/unit-06-note.md`(Derivation Batch/Public API 패턴)·`unit-05-note.md`(GlobalNav/Header 재사용, EmptyState 승격 금지 경고)·`unit-04-note.md`(면책 배너/금지표현 린트)
- 입력(v2 재작업): `docs/harness/units/unit-07-test.md`(6단계, FAIL 판정) — **DEF-U07-01(Critical, Open)** 대응. 04-ux-design.md §5-3(모바일 바텀시트 포커스 트랩, Must-have 접근성 요구사항)이 실제로 작동하지 않는 결함. 설계 결함이 아니라 구현 결함(구조적 버그 2건)이므로 3단계 재작업 없이 5단계가 직접 수정.
- 의존성: UNIT-02(Ingestion Batch), UNIT-03(종목마스터), UNIT-04(면책배너/기준시각뱃지/카피 인프라), UNIT-05(UI셸·GlobalNav·`/screener` 플레이스홀더). **UNIT-06(Derivation Batch/`derived_metrics_daily`)에도 스키마·코드 의존**(§0 참조 — 02-planning.md §9는 UNIT-07의 공식 의존성으로 UNIT-06을 나열하지 않았으나, REQ-003 API가 UNIT-06이 만든 `derived_metrics_daily`를 그대로 소비하고 스키마를 1개 컬럼 확장해야 해서 실질적으로 의존한다).

---

## 0-a. 재작업 이력 (v2 — DEF-U07-01 대응, 규칙 F 피드백 루프, 2026-09-17)

6단계(`unit-07-test.md`)가 헤드리스 Chromium(Puppeteer)으로 모바일 바텀시트(`ConditionFilterPanel`)의 실제 브라우저 동작을 검증하는 과정에서 **DEF-U07-01(Critical, Open)**을 발견해 FAIL 판정하고 5단계로 반려했다. 두 개의 독립적인 원인이 결합된 결함이었다: (a) 패널이 열려도 포커스가 패널 내부로 자동 이동하지 않는다, (b) 패널이 열린 상태에서 조건 필드에 입력하거나 정렬 `<select>`를 바꾸면(부모 컴포넌트 재렌더 발생) 포커스가 즉시 패널 밖으로 튕겨나가 입력값이 커밋되지 않는다. 재작업 대상은 코디네이터 지시대로 `frontend/src/lib/useFocusTrap.ts`/`frontend/src/components/ScreenerClient.tsx` 2개 파일로 한정했다(다른 파일은 건드리지 않음 — `git diff --stat`으로 확인).

### 원인(a) — 초기 포커스 이동 실패: 직접 재현으로 정확한 메커니즘 확정

6단계는 "CSS `visibility:hidden→visible` 전환과 effect 실행 시점의 경쟁 조건으로 추정"이라고만 기록하고 확정하지 않았다(`unit-07-test.md` §6). 이번 재작업은 이를 추측으로 남기지 않고 헤드리스 Chrome(Puppeteer-core, `.harness-tmp/`에 임시 설치, 시스템에 이미 설치된 Chrome을 `executablePath`로 직접 구동 — 신규 Chromium 다운로드 없음)으로 직접 재현했다.

- **1차 재현**: 375×812 뷰포트에서 실제 `/screener` 프로덕션 빌드를 띄우고 트리거 버튼 클릭 → `document.activeElement`가 패널 밖(트리거 버튼)에 남는 것을 확인(6단계 TC-033과 동일 재현).
- **원인 격리**: `HTMLElement.prototype.focus`를 계측(instrument)해 실제로 `.focus()`가 호출된 시점의 `getComputedStyle(this).visibility`를 기록한 결과, `useFocusTrap.ts`의 `(focusable[0] ?? container).focus()` 호출 시점에 패널의 `visibility`가 여전히 `"hidden"`으로 계산됨을 확인했다.
- **근본 메커니즘 확정**: React/CSS 결합 문제가 아니라 **브라우저의 CSS 전환(transition) 자체의 타이밍 특성**임을, 별도의 순수 HTML/CSS 최소 재현 페이지(`visibility: hidden→visible` 전환만 있는 `<div>`, React 완전히 배제)로 교차검증해 확정했다: 클래스 추가 직후는 물론, `requestAnimationFrame` 1회 뒤(`raf1`)에도 `getComputedStyle().visibility`가 여전히 `"hidden"`이고, **2회째 애니메이션 프레임(`raf2`)에서야 `"visible"`로 반영**됨을 확인했다. 즉 "hidden→visible 전환은 지연 없이 즉시 적용된다"는 CSS 스펙상의 기대와 달리, 실제 Chromium 엔진은 클래스 변경으로 예약된 전환이 최소 1개 프레임 이상 지난 뒤에야 `getComputedStyle`에 새 값을 반영한다(이 프로젝트의 실제 관찰 결과이며, 향후 유사 패턴(트랜지션 기반 표시/숨김 + 그 직후 포커스 이동)을 만들 때 참고할 것).
- **수정**: `useFocusTrap.ts`의 초기 포커스 이동을 단일 `requestAnimationFrame`이 아니라 **중첩된 더블 `requestAnimationFrame`** 이후로 지연시켰다(단일 rAF로 먼저 시도했으나 위 재현 결과와 동일하게 여전히 실패해, 더블 rAF로 교정 후 재검증까지 완료). `useEffect`의 cleanup에서 두 rAF 핸들 모두 `cancelAnimationFrame`으로 취소해 언마운트/재실행 시 누수·경합이 없도록 했다.

### 원인(b) — 재렌더 시 포커스 강제 이탈: 6단계 진단(TC-039)을 근본 해법으로 채택

6단계가 임시 패치(`onEscape`를 `useRef`로 변경, 검증 직후 원복)로 이미 원인을 확정해 뒀다(`unit-07-test.md` TC-039): `ScreenerClient.tsx`가 `onCloseMobile={() => setMobileFilterOpen(false)}`를 매 렌더마다 새 인라인 함수로 생성 → 이 불안정한 참조가 `useFocusTrap`의 `useEffect` 의존성 배열에 포함되어, 조건 필드 입력이나 `<select>` 변경으로 부모가 재렌더될 때마다 트랩 effect가 cleanup(무조건 `previouslyFocused.current?.focus()` 호출)+재초기화되어 포커스를 탈취했다.

- **채택한 해법(근본적 방향, 임시 패치를 그대로 쓰지 않음)**: `useFocusTrap.ts` 내부에서 `onEscape`를 `useRef`(`onEscapeRef`)로만 추적하도록 구조를 바꾸고, 이 ref는 별도의 얇은 `useEffect([onEscape])`로 매 렌더 최신값을 갱신하되, **정작 트랩을 여닫는 메인 `useEffect`의 의존성 배열에서는 `onEscape`를 완전히 제거**했다(`[isActive, containerRef]`만 남김). 이렇게 하면 부모가 `onEscape`를 몇 번이고 새로 만들어 넘겨도 트랩 effect 자체는 `isActive`가 실제로 바뀔 때만 재실행된다 — 6단계의 임시 패치보다 한 걸음 더 나아가, "매 렌더 재실행 자체를 막는" 형태로 재설계했다(코디네이터 지시의 "더 근본적인 해법" 옵션 채택).
- **이중 방어(코디네이터 재작업 요청 사항 2번 수용)**: `ScreenerClient.tsx`의 `onCloseMobile` 콜백도 `useCallback(() => setMobileFilterOpen(false), [])`로 안정화했다. `useFocusTrap.ts`의 구조적 수정만으로 이미 (b)가 해소되지만, 호출부 콜백을 불필요하게 매번 새로 만들 이유가 없어 함께 적용했다(6단계 재작업 요청 사항 2번과 동일한 방향).

### 직접 재현 검증 (수정 전/후 비교, 헤드리스 Chrome)

수정 전 빌드로 6단계의 TC-033/TC-035 재현을 먼저 재확인한 뒤(동일하게 재현됨을 확인, 우연한 통과가 아님을 담보), 수정 후 빌드로 6단계가 재작업 요청 사항 3번에서 명시한 TC-033~038 시나리오를 동등하게 재구성해 실행했다. 전부 통과를 확인했다:

| 시나리오(6단계 TC 대응) | 결과 |
|---|---|
| TC-033: 바텀시트 열림 직후 초기 포커스가 패널 내부로 이동 | **Fixed** — 포커스가 패널 내 첫 포커스 가능 요소("필터 닫기" 버튼)로 이동함 |
| TC-034: Tab 연속 입력 시 항상 패널 내부에 트랩 | **Fixed** — 20회 연속 Tab에도 매번 패널 내부 유지 |
| TC-035: 조건 필드 타이핑 중 포커스 유지 + 값 커밋 | **Fixed** — `#screen-market-cap-min`에 "1"→"0" 순차 입력 시 포커스 유지, 값이 "1"→"10"으로 정상 누적 |
| TC-036: 정렬 `<select>` 값 변경 시에도 동일하게 정상 | **Fixed** — 값 변경 후에도 포커스가 패널 내부에 유지되고 값이 정상 커밋 |
| TC-037: Escape 닫기 + 트리거로 포커스 복귀 | **회귀 없음** — 기존과 동일하게 정상 동작 |
| TC-038: 데스크톱(1280×900, `trapActive=false`) 타이핑 회귀 | **회귀 없음** — 기존과 동일하게 정상 동작(트랩 자체가 비활성인 경로는 이번 수정의 영향을 받지 않음, 코드상으로도 `trapActive=false`면 effect가 `isActive`가 false라 즉시 return) |

재현/검증에 쓴 스크립트와 Puppeteer-core는 전부 `.harness-tmp/unit07-rework/`에서 실행 후 세션 종료 전 `rm -rf`로 삭제했다(규칙 K, §7-b 참조). **6단계는 이 결과를 신뢰하지 말고 반드시 독립적으로 TC-033~038을 재실행해야 한다** — 이는 5단계 자체 검증이며 6단계의 독립 재검증을 대체하지 않는다.

### 조치 후 전체 게이트 재확인

- `python -m ruff check .` — All checks passed(백엔드 변경 없음, 회귀 없음 재확인).
- `python -m pytest tests/unit -q` — 127 passed(신규 실패 없음).
- `npx tsc --noEmit` — 오류 없음.
- `npm run lint`(ESLint) — 0 error / 0 warning.
- `npm run build`(`prebuild` 금지어 린트 포함) — 통과, 라우트 6개 정상 생성(회귀 없음).

### 참고사항 보완 — §5-1 인덱스 구성 편차의 정식 기재 누락 (6단계 권고 반영)

6단계(`unit-07-test.md` §8)가 "결함은 아니지만 문서화 보완 권고"로 지적한 사항: 03-system-design.md §5-1이 명시한 인덱스 컬럼 목록(`market, return_pct, market_cap_raw_krw, per_raw, pbr_raw, volume_anomaly_score` 복합)과 실제 구현(`(trade_date, market)` 2컬럼, 마이그레이션 0008)이 다른데도, 이 편차가 마이그레이션 docstring에는 있었지만 **아래 §2(설계서 대비 편차 목록)에는 정식 항목으로 등재되어 있지 않았다**. 이번 재작업 기회에 §2에 편차 항목 8번으로 정식 추가했다(아래 §2 참조). 결함으로 등록하지 않는 이유(YAGNI, 종목 수 규모 대비 타당성)는 기존 §1-2/마이그레이션 docstring 근거를 그대로 유지한다 — 재작업 범위(포커스 트랩 결함 수정)와 무관한 임의 설계 변경은 하지 않았다.

---

## 0. 이 유닛 착수 전 발견한 설계 공백과 처리 방침 (중요 — 반드시 먼저 읽을 것)

이 유닛을 시작하기 전, 03-system-design.md v4 §4-2가 요구하는 `GET /screen?volume_min=`(거래량 최소값, 주 단위) 필터를 실제로 구현할 방법이 설계서 안에서 자기모순적임을 발견했다. 이 절은 그 문제와 이 유닛이 내린 판단, 그리고 그 판단이 왜 "사용자에게 되물어야 할 질문"이 아니라 "아키텍트 수준의 설계 완성도 보완"으로 분류되는지를 기록한다(unit-03-note.md §0, unit-06-note.md §2와 동일한 성격의 선례를 따른 것이며, 새로운 판단 기준을 도입한 것이 아니다).

**문제**: `02-planning.md` §4-3 데이터 가공 원칙 1번은 "원본 시세 데이터(시가/고가/저가/종가/거래량 원문 수치, OHLCV)를 화면·API 응답 어디에서도 그대로 나열·재게시하지 않는다"고 명시한다. 그런데 `03-system-design.md` §4-2가 `GET /screen`의 Must-have 필터로 요구하는 `volume_min`(04-ux-design.md §2-2: "거래량(주), 최소값만 입력, 라벨 '10,000주 이상'")은 raw 거래량(원문 수치) 없이는 구현할 수 없다. 그러나 `derived_metrics_daily`(§3-2)에는 애초에 거래량 컬럼 자체가 없다 — §4-3 1차 방어(스키마 분리)가 이미 그렇게 만들어 놓았다.

**판단**: 이 문제는 03-system-design.md가 PER/PBR/시가총액에 대해 이미 확립해 둔 것과 정확히 동일한 클래스의 문제다 — "필터링은 원시 스케일이 필요한데, 원시값 노출은 금지된다." 그 문제에 대해 설계서는 이미 명시적으로 해법을 확정해 뒀다(§3-2, DEC-014): `*_raw`(DB 컬럼으로만 존재, API 응답 화이트리스트에서 항상 제외)/`*_percentile`(노출용 가공값)의 이원 컬럼 구조. 이 유닛은 그 동일한 패턴을 거래량에 그대로 적용했다: `derived_metrics_daily.volume_raw`(신규, BigInteger, nullable, 마이그레이션 0007)를 필터 전용 컬럼으로 추가하고, API 응답 어디에도 노출하지 않는다.

**PER/PBR/시가총액과의 유일한 차이**: PER/PBR/시가총액은 노출용 대응값(`*_percentile`)이 설계서에 이미 정의되어 있지만, 거래량에는 그런 노출용 대응값이 어디에도 정의되어 있지 않다(04-ux-design.md 어디에도 "거래량 백분위" 표시 문구가 없고, `sort_by` 허용값에도 거래량이 포함되지 않는다 — `sort_by`는 `return_pct|market_cap|per|pbr|volume_anomaly_score` 5개뿐). 즉 거래량은 "정렬 기준도 될 수 없고, 노출 대응값도 없는, 순수 필터 전용" 지표로 설계서가 이미 (의도했든 안 했든) 취급하고 있었다. 이 유닛은 이 사실을 그대로 존중해, **`volume_min`은 필터로는 정확히 동작하되 `matched_metrics`(API 응답)에는 어떤 형태로도 노출하지 않는다** — 새로운 "거래량 백분위" 개념을 창작하지 않았다(그렇게 하면 04-ux-design.md에 없는 신규 UI 카피/스펙을 이 유닛이 임의로 만들어내는 것이 되어 범위를 벗어난다).

**왜 사용자 질문(규칙 A)으로 격상하지 않았는가**: 두 갈래(㉮ 필터 전용 컬럼 추가 후 미노출 vs ㉯ 거래량 percentile을 새로 설계) 중, ㉯는 04-ux-design.md(이미 PASS된 문서)에 없는 신규 화면 카피/API 필드를 만들어야 해서 **이 5단계 개발 유닛의 권한 범위를 벗어난 설계 변경**이고, ㉮는 이미 확정된 03-system-design.md의 기존 패턴(DEC-014)을 문자 그대로 재사용하는 것이라 "새로운 판단"이 아니라 "기존 결정의 필연적 적용"에 가깝다. 두 선택지의 결과가 실질적으로 다르지 않다(어느 쪽이든 `volume_min` 필터는 동일하게 동작하고, 사용자가 화면에서 보는 것도 동일하다 — 차이는 오직 "화면에 거래량 관련 숫자를 하나 더 보여줄지"인데 그건 04-ux-design.md가 이미 "보여주지 않는다"고 암묵적으로 확정해 둔 것과 같다). 따라서 규칙 A의 "해석에 따라 결과가 실질적으로 달라지는 경우"에 해당하지 않는다고 판단했다.

**영향 범위**: `shared/db_models/public_serving.py`(컬럼 추가), `services/derivation_batch/`(repository.py/run_derivation.py — `volume_raw` 패스스루, 기존 필드는 전부 기본값을 부여해 기존 테스트 회귀 없음), 마이그레이션 0007(컬럼 추가, 기존 테이블 GRANT는 컬럼 단위가 아니라 테이블 단위라 재부여 불필요) + 0008(§5-1 인덱스, 아래 §1-2 참조).

---

## 1. 구현 범위

### 1-1. `derived_metrics_daily.volume_raw` 추가 (§0의 결론 반영)

- `db/alembic/versions/0007_add_volume_raw_to_derived_metrics_daily.py`(신규): 컬럼 추가만, 별도 GRANT 불필요(테이블 단위 권한이 새 컬럼에도 그대로 적용됨).
- `shared/db_models/public_serving.py`: `DerivedMetricsDaily.volume_raw`(BigInteger, nullable) 추가.
- `services/derivation_batch/repository.py`: `DerivedMetricsInput.volume_raw`(기본값 `None` — 기존 호출부 회귀 없음), `upsert_derived_metrics()`의 INSERT/UPDATE 양쪽에 반영.
- `services/derivation_batch/run_derivation.py`: `StockDayMetrics.volume_raw`(기본값 `None`), `compute_stock_day_metrics()`가 `window[0].volume`(당일 원본 거래량)을 그대로 대입, `build_derivation_inputs()`가 순위/백분위 계산 없이 그대로 통과(pass-through)시킴 — 거래량은 순위 대상이 아니므로 `rank_percentile()`을 거치지 않는다.
- `tests/unit/test_run_derivation.py`: 기존 테스트에 `volume_raw` 어서션 추가 + 신규 케이스 1건(`test_compute_stock_day_metrics_volume_raw_uses_todays_volume_not_baseline`). 기존 테스트는 전부 기본값(`None`)에 의존해 수정 없이 통과.

### 1-2. `db/alembic/versions/0008_index_derived_metrics_daily_trade_date_market.py` (신규, §5-1)

03-system-design.md §5-1이 REQ-003의 설계 매핑으로 명시한 인덱스 요구사항 중, 이 테이블의 기존 PK(`stock_code, trade_date, market` 순서, UNIT-06)로는 `GET /screen`이 항상 거치는 `WHERE trade_date = ? AND market = ?` 1차 필터에 인덱스가 활용되지 않는 문제를 발견해 `(trade_date, market)` 복합 인덱스를 추가했다. 종목 수 규모(코스피+코스닥 약 2,500개, §8-A3)를 감안해 이 인덱스 하나로 1차 필터를 좁히면 이후 range 필터/정렬은 최소 스캔이라 판단해, `*_raw`/`volume_anomaly_score` 등 컬럼별 인덱스는 이번에 추가하지 않았다(과설계 방지, YAGNI — §2-1/§5-2가 이미 채택한 "실측 후 병목 확인 시 추가" 원칙 재적용). 상세 근거는 마이그레이션 파일 docstring 참조.

### 1-3. Public API — `GET /api/v1/screen` (REQ-003)

- `services/public_api/schemas/screen.py`(신규): `ScreenResultItem`(`matched_metrics: dict[str, float | None]`), `ScreenData`. 원본/원시값 필드는 이 스키마 어디에도 없다(§4-3).
- `services/public_api/db/screen_repository.py`(신규): `ScreenFilters`/`ScreenRow`/`ScreenQueryResult` + `ScreenRepository`(Protocol)/`SqlScreenRepository`. `_apply_filters()`가 market/market_cap_min·max/volume_min/return_pct_min·max/per_max/pbr_max를 전부 SQL `WHERE`로 변환한다. `null` 지표를 조건으로 건 경우의 자동 제외(§3-2 결측치 처리 원칙)는 SQL의 표준 NULL 비교 동작(`NULL >= n`은 항상 unknown)을 그대로 활용해 별도 분기 없이 구현했다. 정렬은 원시값 컬럼 기준(§4-2 v3 신규 설명), 동률은 `stock_code` 오름차순 2차 정렬(결정론적 페이지네이션).
- `services/public_api/api/screen.py`(신규): 라우터 본체.
  - 파라미터 검증: `market`/`sort_by`/`sort_dir` 허용값 검사, `page_size` 상한(200) 검사, `market_cap_min > market_cap_max`·`return_pct_min > return_pct_max` 범위 역전 검사(시스템 경계 입력 검증 — 클라이언트 검증에만 의존하지 않음).
  - 신선도/에러 처리는 `GET /stocks/{code}/metrics`(UNIT-06)와 동일한 패턴을 그대로 재사용: `get_last_trading_day()` → 캘린더 미확인 시 424, `current_published_batch` 미존재 시 503 `DATA_PIPELINE_STALE`, 그 외 정상 조회 후 `meta.data_freshness` 구성(`services/public_api/data_freshness.py`의 `resolve_session_close_at`/`build_staleness_note` 재사용 — 3번째 재사용 시점, UNIT-06이 이미 "UNIT-07/08도 재사용 가능하게 분리해 둔다"고 명시한 대로).
  - `_resolve_matched_metric_keys()`/`_build_matched_metrics()`: `matched_metrics` = (필터 조건에 실제 값이 지정된 지표) ∪ (`sort_by` 지표)(DEC-013). `volume_min`은 §0의 판단에 따라 이 화이트리스트에 절대 포함하지 않는다.
- `services/public_api/main.py`: 라우터 등록.
- REQ-009(사용자 식별 파라미터 금지, §4-1): 이 엔드포인트에 `user_id`/`session_id`/보유종목/매수단가 등 개인화 파라미터를 추가하지 않았다(정적 검토로 확인). 블랙박스 헤더/쿠키 동일성 테스트(UNIT-04 TC-030/031, UNIT-06이 반복한 패턴)는 traceability.md REQ-009 비고가 "신규 API마다 6단계가 반복해야 한다"고 명시한 대로 6단계 소관으로 남긴다.

### 1-4. 프론트엔드 — `/screener` (04-ux-design.md §2-2)

UNIT-05가 만든 `GlobalNav`/`Header`/루트 레이아웃을 그대로 상속한다(새 헤더/내비게이션을 만들지 않음). UNIT-05의 플레이스홀더 텍스트를 그대로 승격시키지 않고 실제 화면으로 전면 교체했다(`unit-05-test.md` TC-028/§7 경고 준수).

- `frontend/src/app/screener/page.tsx`(교체): 메타데이터만 담당하는 서버 컴포넌트 셸. 실제 상호작용은 `ScreenerClient`(클라이언트 컴포넌트)에 위임했다 — **설계서 대비 편차**: `/stocks/[code]`(UNIT-06)는 서버 컴포넌트 fetch 패턴을 썼지만, 이 화면은 04-ux-design.md §2-2가 "로딩: 결과 영역만 스켈레톤, 조건 폼은 그대로 유지"를 요구해서 페이지 전체를 다시 내비게이션하는 서버 컴포넌트 fetch로는 이 요구를 만족할 수 없다(전체 라우트가 다시 로딩됨). 그래서 클라이언트 컴포넌트에서 직접 Public API를 호출하는 방식을 택했다(§2 편차 1 참조).
- `frontend/src/components/ScreenerClient.tsx`(신규): 폼 상태/검증/조회/페이지네이션/모바일 바텀시트 토글을 오케스트레이션하는 메인 컴포넌트.
- `frontend/src/components/ConditionFilterPanel.tsx`(신규): 조건 입력 폼 전체(데스크톱 ≥1024px 사이드 패널 상시 노출 / 모바일 바텀시트, §6 `lg`). **포커스 트랩/Esc 닫기/포커스 복귀(§5-3)를 이 컴포넌트가 구현한다** — `unit-05-note.md` §2 편차1이 "UNIT-07이 바텀시트를 구현할 때 반드시 이행해야 한다"고 명시적으로 위임한 요구사항이다.
- `frontend/src/lib/useFocusTrap.ts`(신규): 재사용 가능한 포커스 트랩 훅(Tab 순환, Escape 처리, 트리거로 포커스 복귀).
- `frontend/src/lib/useIsDesktopViewport.ts`(신규): `matchMedia` 기반 뷰포트 훅. 04-ux-design.md §6 "표 시맨틱이 필요 없는 뷰에서는 `<table>`을 아예 렌더링하지 않는다" 원칙을 실제로 구현하기 위해, `ResultsTable`/`ResultsList` 중 하나만 조건부 렌더링한다(768px 기준, §6 `md`).
- `frontend/src/components/MarketFilterControl.tsx`(신규): 04-ux-design.md §4 명세대로 종목검색(칩)·스크리닝(세그먼트 버튼) 공통 컴포넌트로 만들었다 — 이번 유닛은 세그먼트 버튼 용법만 쓰지만, 향후 REQ-001 프론트엔드 담당 유닛(UNIT-09)이 그대로 재사용해야 한다.
- `frontend/src/components/ConditionField.tsx`, `SortControl.tsx`, `ResultsList.tsx`, `ResultsTable.tsx`, `Pagination.tsx`(신규): §4 명세 그대로.
- `frontend/src/lib/screenApi.ts`(신규): 클라이언트 fetch(`fetchScreenResults`), 억원→KRW 변환(`eokToKrw`, §4-1 "프론트엔드가 API 호출 전 KRW로 변환할 책임을 진다").
- `frontend/src/lib/screenValidation.ts`(신규): 클라이언트 유효성 검증(`min ≤ max`), 순수 함수(DOM 불필요, node로 수동 검증 완료 — §7).
- `frontend/src/lib/screenMetricFormat.ts`(신규): `matched_metrics` 키 → 표시 문구 변환(§2-2/§2-6 "무엇의 몇 배/몇 %인지 항상 명시" 원칙).
- `frontend/src/lib/screenFieldIds.ts`(신규): 필드→DOM id 매핑, 검증 실패 시 첫 오류 필드 포커스 이동에 사용.
- `frontend/src/components/EmptyState.tsx`(수정): `no-screen-conditions`(초기 상태)/`no-screen-result`(0건) 변형 추가 — §2 편차 3 참조(설계서 명명 누락 보완).
- `frontend/src/components/ErrorState.tsx`(수정): `retryHref`(기존, 서버 컴포넌트용) 외에 `onRetry` 콜백(신규, 클라이언트 컴포넌트가 페이지 이동 없이 재조회할 때 사용)을 추가로 지원하도록 하위 호환 확장 — 기존 호출부(`/stocks/[code]`)는 변경 없이 그대로 동작.
- `frontend/src/content/copy.ko.json`(수정): `screener` 섹션 신설(필드 라벨/버튼/정렬 옵션 등), `emptyState`에 2개 키 추가.
- `frontend/src/app/globals.css`(수정): 조건 패널/바텀시트/오버레이/포커스 트랩 관련 스타일, 세그먼트 버튼, 정렬 토글, 결과 리스트/표, 페이지네이션, 인라인 안내(§4 `InlineNotice`) 스타일 추가.

---

## 2. 설계서 대비 편차 및 확인 필요 사항 (사유 포함)

1. **[아키텍처 패턴 결정] `volume_raw` 필터 전용 컬럼 신설** — §0 참조. PER/PBR/시가총액과 동일한 이원 컬럼 원칙(DEC-014)을 거래량에 확장 적용했다. `matched_metrics`에는 절대 노출하지 않는다.
2. **[구현 방식 결정] `/screener`를 클라이언트 컴포넌트로 구현** — 04-ux-design.md §2-2의 "결과 영역만 스켈레톤, 조건 폼 유지" 요구를 서버 컴포넌트 fetch(라우트 재내비게이션)로는 만족할 수 없어, `/stocks/[code]`(UNIT-06)와 다른 패턴을 택했다. `metadata`는 별도 서버 컴포넌트 셸(`page.tsx`)에서 export하고, 실제 로직은 `ScreenerClient`(`"use client"`)로 분리했다(Next.js 제약 — 클라이언트 컴포넌트는 `metadata`를 export할 수 없음).
3. **[설계서 명명 누락 보완] `EmptyState` 변형 `no-screen-conditions` 신설** — 04-ux-design.md §4의 `EmptyState` 변형 표는 스크리닝 화면의 빈 상태를 `no-screen-result`(조건 결과 0건) 하나만 명명했다. 그러나 §1-2 Flow B는 "초기(조건 미적용)" 상태의 텍스트("조건을 설정하고 [조건 적용]을 눌러주세요")를 별도로 명시하고 있어, 이미 확정된 문구에 이름만 붙여 구현했다 — 새 기능이 아니다.
4. **[구현 세부 결정] 결과 0건 상태에서 "조건 충족 종목 목록 (총 N건)" 헤딩을 표시하지 않음** — 04-ux-design.md는 이 경우 헤딩 표시 여부를 명시하지 않았다. `EmptyState` 문구만으로 충분하다고 판단해 헤딩은 결과가 1건 이상일 때만 표시한다(단순화, 과설계 방지).
5. **[구현 세부 결정] `percentileScopeNotice`(PER·PBR·시가총액 백분위 고지)는 결과 0건 상태에서는 표시하지 않음** — 표시할 백분위 값 자체가 없는 상태이므로 고지가 실질적 의미가 없다고 판단했다. `market !== "ALL"`이고 결과가 1건 이상일 때만 표시한다.
6. **[접근성 보강, 설계서 범위 내] 모바일 바텀시트에 `role="dialog"`/`aria-modal="true"` 추가** — 04-ux-design.md §5-3은 포커스 트랩/Esc/포커스 복귀만 명시했으나, 접근 가능한 다이얼로그 패턴의 표준 관행이라 함께 적용했다(트랩이 활성화된 경우에만 부여, 데스크톱 상시 노출 상태에서는 부여하지 않음 — 다이얼로그가 아니라 상시 패널이므로).
7. **[구현 세부 결정] `aria-live="polite"`를 결과 영역 전체(`.screener-page__results`)에 부여** — 04-ux-design.md §5-4는 "총 N건 검색됨" 등 동적 변화를 `aria-live` 영역으로 공지하라고 요구한다. 결과 개수만 별도로 감싸는 대신 결과 영역 전체를 감쌌다 — 구현이 단순해지는 대신, 스크린리더가 매 갱신마다 전체 목록을 다시 읽어줄 수 있어 결과 건수가 많을 때 장황할 수 있다는 트레이드오프가 있다(§3 수동 확인 항목 참조, 개선 여지 있음).
8. **[문서화 보완, v2 재작업에서 추가 — 결함 아님] §5-1 인덱스 컬럼 구성 편차** — 03-system-design.md §5-1이 명시한 인덱스 컬럼 목록(`market, return_pct, market_cap_raw_krw, per_raw, pbr_raw, volume_anomaly_score` 복합)과 실제 구현(마이그레이션 0008, `derived_metrics_daily(trade_date, market)` 2컬럼 복합 인덱스)이 다르다. §1-2에서 이미 서술한 대로, 종목 수 규모(코스피+코스닥 약 2,500개)에서는 `(trade_date, market)` 인덱스로 1차 필터를 좁히면 이후 range 필터/정렬 스캔 비용이 낮다고 판단해 컬럼별 인덱스를 추가하지 않았다(YAGNI, §5-1 목표는 특정 인덱스 구성이 아니라 "P95 800ms" 성능 목표). 마이그레이션 docstring에는 이 근거가 있었으나 **이 §2 편차 목록에는 최초 작성 시 등재를 누락**했다 — 6단계(`unit-07-test.md` §8)가 문서화 보완 권고로 지적한 사항을 이번 재작업 기회에 정식 반영했다. 실측 성능(§8-A3/§3 참조)은 여전히 미측정 상태로 남아 있다.

---

## 3. 수동으로 확인이 필요한 부분 (6단계 테스터 및 향후 운영자용)

- **[최우선] `screen_repository.py`의 실제 SQL 쿼리는 이번 세션에서 실 PostgreSQL로 검증하지 못했다** — 이번 세션에서 Docker Desktop이 기동되지 않아(`failed to connect to the docker API`) UNIT-01/02/03/06이 사용했던 로컬 `stock-screener-db` 컨테이너에 접근할 수 없었다. 백엔드 검증은 (1) `pytest`(FastAPI `TestClient` + Fake 리포지토리로 라우터 로직만 검증, 실제 SQL 미실행), (2) `ruff` 정적 분석까지만 수행했다. `_apply_filters()`의 각 WHERE 절, `sort_column.desc()/.asc()` 정렬, `join(StockMaster)` 조합, NULL 비교로 인한 자동 제외 동작은 **실제 DB로 반드시 재검증이 필요하다** — 이 항목이 이번 유닛에서 가장 중요한 미검증 리스크다.
- **마이그레이션 0007/0008의 실제 적용/롤백도 미검증** — 동일한 이유(Docker 미기동)로 `alembic upgrade head`/`downgrade`를 실행하지 못했다. SQL 구문은 UNIT-06의 0006 파일과 동일한 패턴을 따랐으나, 실제 PostgreSQL에서의 성공 여부는 확인되지 않았다.
- **프론트엔드 실제 브라우저 상호작용 미검증** — `npm run build`/`npm run start` + `curl`로 초기(조건 미적용) 상태의 정적 HTML만 확인했다(§7 참조). 다음은 실제 브라우저(또는 헤드리스 Chrome)로만 확인 가능하다: (1) 모바일 바텀시트 열기/닫기 애니메이션과 포커스 트랩의 실제 Tab 순환·Escape 동작·트리거로의 포커스 복귀, (2) "조건 적용" 클릭 후 실제 API 응답을 받아 결과 리스트/표가 렌더링되는 종단간 흐름(백엔드도 실 DB가 없어 실데이터로 확인 불가), (3) 768px/1024px 브레이크포인트에서 `ResultsList`↔`ResultsTable`, 바텀시트↔사이드패널 전환이 실제로 정확한 지점에서 일어나는지, (4) 클라이언트 유효성 검증 실패 시 포커스가 실제로 첫 오류 필드로 이동하는지.
- **REQ-002(UNIT-06)와의 상호작용 확인 필요**: `derived_metrics_daily`에 실제 데이터가 있어야(현재는 UNIT-02가 `raw_fundamentals`를 적재하지 않고 UNIT-06 검증 후 픽스처를 정리해 테이블이 비어 있음, `unit-06-note.md` §7 "정리" 참조) `GET /screen`이 의미 있는 결과를 반환한다. 6단계가 실 데이터(또는 UNIT-06과 동일한 방식의 명시적 테스트 픽스처)로 종단간 검증할 것을 권고한다.
- **REQ-009 블랙박스 회귀 테스트**: traceability.md REQ-009 비고가 "신규 API마다(UNIT-06/07/08) TC-028~031과 동일한 헤더/쿠키 동일성 테스트를 반복해야 한다"고 명시했다 — 이 유닛은 정적 검토(파라미터 목록에 식별자 없음)만 수행했고, 블랙박스 테스트 작성은 6단계 소관으로 남긴다.
- **인덱스(0008)의 실제 성능 효과 미측정** — §5-1 목표(P95 800ms)를 만족하는지는 실 데이터 규모(약 2,500종목)로 실측해야 하며, 이번 세션은 실행 계획(EXPLAIN) 확인조차 하지 못했다(DB 부재).

---

## 4. 인수 조건 (Acceptance Criteria) — 6단계 테스터용

**AC-1 (Derivation Batch `volume_raw` 패스스루, DB 불필요)** `pytest tests/unit/test_run_derivation.py -v`:
  - `test_compute_stock_day_metrics_with_fundamentals`: `result.volume_raw == 1000`(당일 원본 거래량 그대로)
  - `test_compute_stock_day_metrics_volume_raw_uses_todays_volume_not_baseline`(신규): 당일 거래량(5000)이 전일(900)이 아니라 당일 값 그대로 반영됨
  - `test_build_derivation_inputs_computes_cross_sectional_percentiles`: `volume_raw`가 순위/백분위 계산 없이 그대로 통과(A=12000, B=`None`)

**AC-2 (Public API `GET /api/v1/screen`, Fake 리포지토리)** `pytest tests/unit/test_public_api.py -v -k screen` 14건 전부 pass:
  - 기본 파라미터 성공(시장 ALL, `sort_by` 기본값 `return_pct`, `matched_metrics == {"return_pct": 3.2}`)
  - `market_cap_min` 필터 시 `matched_metrics`에 `market_cap`과 `return_pct`(sort_by 기본값) 둘 다 포함
  - `volume_min` 필터가 리포지토리에 전달되되 **`matched_metrics`에는 절대 포함되지 않음**(§0/§2 편차1 핵심 검증 포인트)
  - `pbr_max` + `sort_by=per` 조합 시 `matched_metrics == {"pbr": ..., "per": ...}`(둘 다, 알파벳순)
  - 결과 0건 → 200 + 빈 배열
  - `market`/`sort_by`/`sort_dir` 잘못된 값 → 400 `INVALID_PARAMETER`(리포지토리까지 도달하지 않음)
  - `page_size=201` → 400 `INVALID_PARAMETER`
  - `market_cap_min > market_cap_max`, `return_pct_min > return_pct_max` → 400 `INVALID_PARAMETER`
  - 캘린더 미확인 → 424 `CALENDAR_NOT_CONFIRMED`
  - 발행 데이터 없음 → 503 `DATA_PIPELINE_STALE`
  - `page`/`page_size` 파라미터가 리포지토리에 정확히 전달됨(페이지네이션)

**AC-3 (기존 회귀 없음)**
  - `pytest tests/unit -q` **127건** 전부 pass(기존 112건 + 이번 유닛 신규 15건: `test_run_derivation.py` 신규 1건(`volume_raw` 전용 케이스, 기존 2건은 어서션만 추가되어 건수 불변) + `test_public_api.py` screen 신규 14건)
  - `python -m ruff check .` 오류 0건

**AC-4 (프론트엔드 정적 분석)**
  - `cd frontend && npx tsc --noEmit`(오류 0건), `npm run lint`(0 error/0 warning), `npm run build`(prebuild 금지어 린트 포함, 검사 파일 39개, 위반 0건) 전부 통과
  - 빌드 결과 라우트 목록에 `/screener`가 정적(Static)으로 포함되어 있어야 한다(클라이언트 컴포넌트이지만 초기 셸은 정적 생성됨)

**AC-5 (프론트엔드 초기 상태 렌더링, 백엔드 불필요)**
  - `npm run build && npm run start` 후 `curl http://localhost:3000/screener` 응답 HTML에 다음이 모두 존재해야 한다: `<h1>조건 스크리닝</h1>`, 초기 안내 문구("조건을 설정하고 [조건 적용]을 눌러주세요"), `market-filter-control__button`(3개), `id="screen-market-cap-min"` 등 8개 조건 필드 id 전부, `disclaimer-banner`(REQ-007 회귀 없음), `aria-label="주요 메뉴"`(GlobalNav 회귀 없음)

**AC-6 (프론트엔드 순수 함수 수동 검증, DOM/네트워크 불필요)**
  - Node로 직접 실행 확인: `validateScreenForm`이 `min > max`일 때만 오류를 반환하고 빈 값/정상 범위는 오류 없음, `eokToKrw(1000) === 100_000_000_000`

**AC-7 (실 DB 검증 — 이번 세션 미수행, 6단계가 반드시 독립 수행해야 함)**
  - `alembic upgrade head`(0001~0008)가 성공하고 `derived_metrics_daily.volume_raw` 컬럼과 `ix_derived_metrics_daily_trade_date_market` 인덱스가 생성되어야 한다
  - 실 데이터(또는 UNIT-06과 동일한 방식의 명시적 테스트 픽스처)로 `market_cap_min`/`volume_min`/`return_pct_min·max`/`per_max`/`pbr_max` 각 필터가 실제로 결과를 좁히는지, `sort_by`/`sort_dir` 조합별 정렬 순서가 올바른지, 페이지네이션(`total_count`/`offset`/`limit`)이 정확한지 확인 필요
  - `api_service`로 `derived_metrics_daily`/`stock_master`에 대한 SELECT는 성공하고 INSERT/UPDATE/DELETE는 거부되는지(1차/2차 방어 회귀 없음) 재확인 필요

**AC-8 (v2 재작업 — DEF-U07-01 수정 확인, 6단계가 반드시 헤드리스 브라우저 또는 실제 브라우저로 독립 재현해야 함)**
  - `npm run build && npm run start`(모바일 뷰포트, 375×812 권장) 후 `.screener-page__mobile-filter-trigger` 클릭 → `[role="dialog"]` 렌더 직후(수 프레임 이내) `document.activeElement`가 패널 내부(첫 포커스 가능 요소, "필터 닫기" 버튼)여야 한다(트리거 버튼에 남아있으면 안 됨) — DEF-U07-01 원인(a) 회귀 확인
  - Tab을 여러 번(최소 10회 이상) 연속 입력해도 `document.activeElement`가 매번 다이얼로그 내부에 머물러야 한다(패널 밖 요소로 이탈하면 안 됨)
  - 임의의 조건 입력 필드(예: `#screen-market-cap-min`)에 포커스한 뒤 숫자를 2개 이상 연속 입력했을 때, 매 입력마다 포커스가 그 필드에 유지되고 값이 정상적으로 누적되어야 한다(예: "1" 입력 후 "0" 입력 시 값이 "10"이 되어야 함, 포커스가 패널 밖이나 다른 요소로 이탈하면 안 됨) — DEF-U07-01 원인(b) 회귀 확인
  - 정렬 기준 `<select id="screen-sort-by">` 값을 변경했을 때도 동일하게 포커스가 패널 내부에 유지되고 값이 정상 커밋되어야 한다(필드 종류와 무관하게 일반화되어야 함)
  - Escape 키 입력 시 패널이 닫히고 포커스가 트리거 버튼("조건 필터 열기")으로 복귀해야 한다(기존 정상 동작 회귀 없음)
  - 데스크톱 뷰포트(≥1024px)에서는 위 트랩 관련 항목이 애초에 적용되지 않는 경로(`trapActive=false`, 사이드 패널 상시 노출)이므로, 조건 필드 타이핑이 이번 수정 전과 동일하게 정상 동작해야 한다(회귀 없음 확인 목적)

---

## 5. 게이트 1 — 정적 분석/린트 결과

- **백엔드**: `pyproject.toml`의 `ruff` 설정(UNIT-01부터 기존) 그대로 적용. `python -m ruff check .` → **All checks passed!**
- **프론트엔드**: `eslint.config.mjs`(UNIT-04부터 기존) → `npm run lint` 0 error/0 warning. `npx tsc --noEmit` 통과. `npm run build`의 `prebuild`(금지어 린트) → 검사 파일 39개(이전 유닛 대비 신규 파일 다수 반영), 위반 0건.
- 설정이 없어서 건너뛴 검사는 없다.
- **(v2 재작업 재확인)** `useFocusTrap.ts`/`ScreenerClient.tsx` 수정 후 위 4개 명령(`ruff check .`, `pytest tests/unit -q`, `npx tsc --noEmit`, `npm run lint`, `npm run build`) 전부 재실행해 통과를 재확인했다(§0-a 참조).

## 6. 게이트 2 — 자체 코드 리뷰 체크리스트

- [x] **설계서/디자인서 명세와 실제 구현이 일치하는가** — 03-system-design.md §4-2(`GET /screen` 파라미터/응답/에러코드), §4-3(응답 화이트리스트), 04-ux-design.md §2-2(조건 폼 필드 1:1 대응, CTA 문구, 결과 표시 규칙, percentile 고지)·§5-3(포커스 트랩)·§6(반응형 전환)을 그대로 구현했다. 설계서가 명시하지 않은 부분(§0의 `volume_raw`, §2 편차 3~7)은 상상으로 채우지 않고 근거와 함께 직접 확정했다.
- [x] **에러 처리가 누락된 경로가 없는가(예외를 삼키고 무시하는 코드 없음)** — 백엔드: 캘린더 미확인/미발행 데이터/파라미터 검증 실패를 전부 명시적 `ApiError`로 처리(UNIT-06과 동일 패턴). 프론트엔드: `fetchScreenResults()`가 네트워크 실패/JSON 파싱 실패/서버 에러/응답 형식 이상을 전부 명시적으로 분기해 `ErrorState`/`EmptyState`로 연결한다(조용히 실패하거나 빈 화면을 보여주지 않음).
- [x] **입력값 검증이 시스템 경계(사용자 입력, 외부 API 응답)에서 이루어지는가** — API 경계: `market`/`sort_by`/`sort_dir` 허용값, `page_size` 상한, 범위 역전(`min > max`)을 서버가 재검증한다(클라이언트 검증에만 의존하지 않음 — 사용자가 클라이언트 검증을 우회해도 서버가 막는다). 프론트엔드 경계: `fetchScreenResults()`가 서버 응답의 `data`/`meta.data_freshness` 존재 여부를 검증한다(신뢰하고 그대로 사용하지 않음, UNIT-06과 동일 원칙).
- [x] **하드코딩된 시크릿/자격증명이 없는가** — 이번 유닛은 신규 환경변수나 자격증명을 도입하지 않았다(기존 `PUBLIC_API_DATABASE_URL`/`NEXT_PUBLIC_API_BASE_URL` 재사용). `grep -rn "devpass"` 등 로컬 비밀번호 문자열이 소스에 없음을 확인.
- [x] **새로 추가한 외부 의존성(패키지)이 있다면 실제 레지스트리 존재를 확인했는가** — 이번 유닛은 `pyproject.toml`/`package.json`에 신규 패키지를 추가하지 않았다(기존 FastAPI/SQLAlchemy/Next.js/React만 사용). 해당 없음.
- [x] **범위를 벗어난 변경(곁다리 리팩터링 등)이 섞여 있지 않은가** — `derived_metrics_daily` 스키마 확장(§0)은 REQ-003의 Must-have 파라미터(`volume_min`)를 구현하기 위한 필수 선행 작업이며, 기존 컬럼/로직은 전혀 건드리지 않았다(신규 컬럼 추가 + 기존 필드에 기본값만 부여). `ErrorState`의 `onRetry` 확장은 기존 호출부(`/stocks/[code]`)의 동작을 바꾸지 않는 하위 호환 확장이다. UNIT-06이 만든 `/stocks/[code]` 화면, UNIT-05가 만든 `GlobalNav`/`Header`/`/stocks` 플레이스홀더는 전혀 수정하지 않았다. `market_summary_daily`(REQ-004, UNIT-08 소관)는 만들지 않았다.

**(v2 재작업, DEF-U07-01 조치) 게이트 2 재점검**:
- [x] **설계서/디자인서 명세와 실제 구현이 일치하는가** — 04-ux-design.md §5-3(포커스 트랩/Esc/포커스 복귀, Must-have)이 실제로 동작하도록 수정했다(§0-a 재현 검증 표 참조). 설계서가 명시하지 않은 구현 세부(더블 rAF 지연 시점, `onEscape` ref화)는 설계 계약을 바꾸는 것이 아니라 이미 확정된 접근성 계약을 실제로 만족시키기 위한 구현 디테일이다.
- [x] **에러 처리가 누락된 경로가 없는가** — 해당 없음(이번 수정은 UI 상호작용/포커스 관리 로직이며 신규 에러 경로를 추가하지 않았다). rAF cleanup에서 `cancelAnimationFrame`을 빠짐없이 호출해 언마운트/재실행 시 콜백이 유령처럼 남아 실행되는 경로를 막았다.
- [x] **입력값 검증이 시스템 경계에서 이루어지는가** — 해당 없음(이번 수정은 서버/클라이언트 경계 입력 검증과 무관, 순수 프론트엔드 포커스 관리 로직).
- [x] **하드코딩된 시크릿/자격증명이 없는가** — 해당 없음(신규 환경변수/자격증명 도입 없음).
- [x] **새로 추가한 외부 의존성이 있다면 레지스트리 존재를 확인했는가** — `package.json`/`pyproject.toml`에 신규 의존성을 추가하지 않았다. 재현 검증에만 쓴 `puppeteer-core`(npm 공식 레지스트리 실존 확인, `npm install`로 정상 설치됨)는 `.harness-tmp/`에서만 설치·실행하고 검증 직후 완전히 삭제했다 — 프로젝트 의존성이 아니다.
- [x] **범위를 벗어난 변경이 섞여 있지 않은가** — 코디네이터 지시대로 `frontend/src/lib/useFocusTrap.ts`/`frontend/src/components/ScreenerClient.tsx` 2개 파일만 수정했다(`git diff --stat`으로 확인, §0-a 참조). `ConditionFilterPanel.tsx`/`globals.css` 등 다른 파일은 건드리지 않았다.

---

## 7. 로컬 동작 확인 요약 (실행 로그 근거)

- `python -m ruff check .` → **All checks passed!**
- `python -m pytest tests/unit -q` → **127 passed**(기존 112건 + 이번 유닛 신규 15건: `test_run_derivation.py` 신규 1건 + `test_public_api.py` screen 신규 14건)
- `cd frontend && npx tsc --noEmit` → 오류 없음
- `cd frontend && npm run lint` → 0 error, 0 warning
- `cd frontend && npm run build` → `금지표현 검사 통과 (검사 파일 39개)` 후 `next build` 성공, 라우트 6개 정상 생성(`/`, `/_not-found`, `/about`, `/screener`, `/stocks`, `/stocks/[code]`)
- `cd frontend && npm run start` 후 `curl http://localhost:3000/screener` → `<h1>조건 스크리닝</h1>`, 초기 안내 문구, 시장 세그먼트 버튼 3개, 조건 필드 id 8개(`screen-market-cap-min/max`, `screen-volume-min`, `screen-return-pct-min/max`, `screen-per-max`, `screen-pbr-max`, `screen-sort-by`), `disclaimer-banner`, `aria-label="주요 메뉴"`(GlobalNav) 전부 확인 — 확인 후 서버 프로세스 종료
- Node로 순수 함수 직접 실행 검증(`node --experimental-strip-types`): `validateScreenForm`이 시가총액/등락률 범위 역전만 오류로 잡고 정상 범위·빈 값은 통과함을 확인, `eokToKrw(1000) === 100000000000` 확인
- **Docker Desktop 미기동으로 실 PostgreSQL 검증은 이번 세션에서 수행하지 못했다**(`docker ps` 실행 결과 `failed to connect to the docker API` — `.harness-tmp/`나 다른 임시 아티팩트를 만들지 않았으므로 규칙 K 관련 정리 대상도 없음). §3에 상세 기록했으며, 6단계가 반드시 독립적으로 재현해야 한다(AC-7).

### 7-b. v2 재작업(DEF-U07-01) 로컬 동작 확인 요약

- `python -m ruff check .` → **All checks passed!**(백엔드 미변경, 회귀 없음)
- `python -m pytest tests/unit -q` → **127 passed**(신규 실패 없음)
- `cd frontend && npx tsc --noEmit` → 오류 없음
- `cd frontend && npm run lint` → 0 error, 0 warning
- `cd frontend && npm run build` → `금지표현 검사 통과 (검사 파일 39개)` 후 `next build` 성공, 라우트 6개 회귀 없이 정상 생성
- **헤드리스 Chrome(Puppeteer-core, 시스템 설치 Chrome 재사용, `.harness-tmp/unit07-rework/`)으로 실제 브라우저 재현**:
  - 수정 전 빌드: TC-033(초기 포커스 밖에 남음)·TC-035(타이핑 시 포커스 이탈, 값 미커밋) 재현 확인(6단계 결과와 동일, 우연이 아님을 담보)
  - 원인(a) 격리: `Element.prototype.focus` 계측 + 별도 순수 HTML/CSS 최소 재현 페이지로, `visibility:hidden→visible` 전환이 클래스 변경 후 최소 2개 애니메이션 프레임이 지나야 `getComputedStyle`에 반영됨을 확인
  - 수정 후 빌드: TC-033~038 동등 시나리오 전부 통과(§0-a 표 참조) — 초기 포커스 이동, Tab 20회 트랩 유지, 필드 타이핑 값 "1"→"10" 정상 누적, `<select>` 값 변경 시에도 포커스 유지+값 커밋, Escape 닫기+포커스 복귀 회귀 없음, 데스크톱 타이핑 회귀 없음
  - 재현에 사용한 `.harness-tmp/unit07-rework/`(puppeteer-core, 재현 스크립트, 임시 HTML) 전체를 검증 완료 후 `rm -rf`로 삭제 완료(규칙 K), 프론트엔드 서버 프로세스도 전부 종료 확인(포트 3100 재조회 결과 연결 없음)
- Docker Desktop은 이번 재작업에서도 기동하지 않아 실 PostgreSQL 기반 재검증(AC-7)은 이번에도 수행하지 못했다 — 이번 재작업은 프론트엔드 전용 결함(DEF-U07-01) 수정이라 백엔드/DB 영향이 없음을 `git diff --stat`으로 확인했으므로, AC-7의 미검증 상태는 최초 note와 동일하게 유지된다(6단계가 v1 검증에서 이미 실 DB로 확정 PASS했던 부분이며, 이번 재작업이 그 코드를 전혀 건드리지 않았다).

---

## 8. 다음 단계

- 이 노트 작성 및 `traceability.md` 갱신 완료 후, 6단계(단위테스트, `06-unit-tester`)를 UNIT-07 대상으로 호출해야 한다.
- 6단계는 특히 다음을 독립적으로 재검증할 것을 권고한다:
  1. §3/§7이 "미검증"으로 명시한 실 PostgreSQL 기반 검증 전체(마이그레이션 0007/0008 적용, `screen_repository.py`의 필터/정렬/페이지네이션 SQL 정확성, 권한 분리 회귀 없음) — 이번 유닛에서 가장 중요한 미완료 검증.
  2. `volume_min`이 필터로는 동작하되 `matched_metrics`에는 절대 노출되지 않는지(§0/§2 편차1) — 원본 데이터 미노출 원칙(§4-3)의 핵심 준수 지점이므로 실 데이터로 재확인 권고.
  3. 모바일 바텀시트 포커스 트랩(Tab 순환/Escape/포커스 복귀)의 실제 브라우저 동작(unit-05-note.md §2 편차1이 이 유닛에 위임한 요구사항의 이행 여부).
  4. REQ-009 블랙박스 헤더/쿠키 동일성 테스트(traceability.md REQ-009 비고가 UNIT-06/07/08에 반복 요구).
  5. `EmptyState` 신규 변형(`no-screen-conditions`/`no-screen-result`) 도입이 04-ux-design.md §1-2 Flow B의 정확한 문구와 일치하는지.

### 8-b. v2 재작업 완료 후 다음 단계 (2026-09-17)

- 이 노트(v2)와 `traceability.md` REQ-003 갱신 완료 후, **6단계(`06-unit-tester`)가 DEF-U07-01 조치를 독립적으로 재검증(v2)해야 한다** — 규칙 F 피드백 루프의 재검증 단계이며, 5단계 자체 검증(§0-a/§7-b)을 그대로 신뢰해서는 안 된다.
- 6단계 재검증 시 반드시 확인할 항목(AC-8, `unit-07-test.md` 재작업 요청 사항 3번과 동일 범위):
  1. TC-033~038(모바일 초기 포커스 이동/Tab 트랩/필드 타이핑 유지/`<select>` 변경/Escape/데스크톱 회귀)을 5단계 검증 결과를 신뢰하지 말고 **다시 독립적으로 재현**할 것 — 가능하면 5단계가 쓴 것과 다른 방식(예: 실제 브라우저 수동 조작, 또는 다른 헤드리스 툴)으로 교차검증하는 것을 권장한다.
  2. 원인(a) 수정(더블 rAF)이 네트워크/기기 성능이 느린 환경(예: CPU 스로틀링)에서도 여전히 충분한지 — 이번 재작업은 로컬 환경에서만 검증했다.
  3. 원인(b) 수정(`onEscapeRef` + 의존성 배열 축소, `useCallback`)이 다른 재렌더 트리거(예: `isSubmitting` 변화로 인한 재렌더)에서도 회귀 없이 동작하는지 — 이번 재작업은 필드 타이핑/`<select>` 변경 2가지 트리거만 재현했다.
  4. AC-1~AC-7(기존)은 이번 재작업이 건드리지 않은 코드이므로 전면 재검증은 불필요하고 회귀만 확인하면 된다(6단계 v1이 이미 실 PostgreSQL로 확정 PASS).
  5. 재검증 완료 후 `unit-07-test.md`를 v2로 개정하고 최종 판정(PASS/FAIL)을 내려야 한다 — DEF-U07-01이 Fixed로 확정되어야 07단계(통합테스트) 진행이 가능하다.
