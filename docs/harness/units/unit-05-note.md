# UNIT-05 구현 노트 — 반응형 UI 셸 / 공통 네비게이션

- 작성 에이전트: 05-unit-developer
- 작성일: 2026-09-16
- 포함 REQ: REQ-013(반응형 모바일 우선 웹 UI)
- 입력: `docs/harness/03-system-design.md`(v4, PASS) §2-1(Next.js+TypeScript 채택 근거) / `docs/harness/04-ux-design.md`(v3, PASS) §1-0(전역 구조/전역 내비게이션 항목 3개), §2-0(공통 레이아웃), §4(`GlobalNav` 컴포넌트 명세), §5(WCAG 2.1 AA 접근성 기준), §6(반응형/디바이스 대응 기준)
- 의존성: 02-planning.md §9 목록상 "없음(병행 가능)"이나, 코디네이터 지시에 따라 UNIT-04가 이미 만들어 둔 최소 `Header.tsx`(워드마크만)를 확장하는 형태로 순차 진행했다(UNIT-04 note §2 편차 3 "UNIT-05가 이 헤더를 확장해야 한다"를 그대로 이행)

---

## 0. 이 유닛의 성격

UNIT-04는 규제 대응 공통 컴포넌트(배너/푸터/기준시각 배지/카피 인프라)에 집중하며 헤더를 워드마크만 있는 최소 형태로 의도적으로 남겨뒀다. 이 유닛은 그 헤더를 확장해 04-ux-design.md §1-0/§4/§6이 요구하는 **전역 내비게이션(`GlobalNav`)과 반응형 브레이크포인트**를 완성한다. 화면 콘텐츠(홈/종목검색/스크리닝/전일동향의 실제 데이터·폼·리스트)는 만들지 않으며, 내비게이션이 가리키는 라우트가 아직 없는 경우에만 404 방지용 최소 플레이스홀더 페이지를 둔다.

---

## 1. 구현 범위

### 1-1. `GlobalNav` 컴포넌트 (`frontend/src/components/GlobalNav.tsx`, 신규)

- 04-ux-design.md §1-0이 확정한 **3항목** 내비게이션만 구현했다: 홈(`/`) · 조건 스크리닝(`/screener`) · 종목 검색(`/stocks`). §1-0은 "About/이용안내는 1차 내비게이션에 넣지 않고 배너/푸터 링크로만 노출한다(1차 내비게이션은 3개로 단순 유지)"를 명시적으로 규정하므로, `/about`은 이 컴포넌트에 추가하지 않았다(UNIT-04가 이미 배너/푸터에 링크를 뒀다).
- 클라이언트 컴포넌트(`"use client"`, `usePathname` 사용)로, 현재 경로와 일치하는 메뉴 항목에 `aria-current="page"`를 부여한다(04-ux-design.md §4 `GlobalNav` 명세 "현재 위치 표시" 그대로 구현). 홈은 정확히 `/`일 때만, 그 외 항목은 `pathname === href` 또는 `pathname.startsWith(href + "/")`(향후 `/stocks/[code]` 같은 하위 라우트가 생겨도 상위 탭이 활성 상태를 유지하도록 방어적으로 구현)일 때 활성 처리한다.
- **모바일/데스크톱을 위해 두 개의 별도 내비게이션 DOM을 만들지 않았다.** 동일한 `<nav><ul><li><Link>` 마크업 하나를 유지하고, CSS 미디어쿼리(`min-width: 768px`)로 `position: fixed(하단 탭바)` ↔ `position: static(상단 탭)`만 전환한다. 이렇게 한 이유: 두 세트의 링크를 만들고 `display:none`으로 한쪽만 숨기는 방식도 가능했지만(그 경우 `display:none` 요소는 포커스/스크린리더 트리에서 제외되어 이론상 문제는 없다), 링크가 완전히 동일한 3개뿐이라 굳이 DOM을 중복시킬 이유가 없었고, 단일 DOM 쪽이 "탭 순서가 뷰포트에 따라 두 배로 늘거나 줄지 않는다"를 코드 구조 자체로 보장한다(리뷰/유지보수 관점에서 더 안전).
- 메뉴 라벨 문구는 `src/content/copy.ko.json`의 `nav.home`/`nav.screener`/`nav.stocks`/`nav.ariaLabel` 키에 신규 추가했다(UNIT-04가 세운 "UI 문자열은 중앙 카피 리소스에서만 가져온다" 원칙 준수, `lint-forbidden-copy.mjs`의 스캔 대상에도 자동 포함됨).

### 1-2. `Header.tsx` 확장 (`frontend/src/components/Header.tsx`, 수정)

- 기존 워드마크만 있던 헤더에 `.site-header__bar`(flex, `justify-content: space-between`) 래퍼를 추가하고 그 안에 워드마크 링크 + `GlobalNav`를 배치했다(04-ux-design.md §1-0 ASCII 와이어프레임 "헤더: 서비스명 + 전역 내비게이션"과 1:1 대응).
- `Header` 자체는 여전히 서버 컴포넌트로 유지했다(워드마크는 상태가 필요 없음). `GlobalNav`만 클라이언트 경계로 분리해 클라이언트 번들 크기를 최소화했다(Next.js 공식 가이드 "Reducing JS bundle size" 패턴 그대로 적용).

### 1-3. 반응형 브레이크포인트 (`frontend/src/app/globals.css`, 수정)

04-ux-design.md §6 브레이크포인트 표를 이번 유닛 범위(셸/네비게이션)에 해당하는 부분만 CSS로 구현했다:

| 브레이크포인트 | 구현 내용 |
|---|---|
| Base(모바일, < 768px) | `GlobalNav`가 화면 하단에 `position: fixed`로 고정된 탭바(`justify-content: space-around`, 각 링크 `min-height: 44px` — §5-6 터치 타겟 최소 44×44px 반영), `<main>`에 `padding-bottom: calc(24px + 56px)`을 줘 고정 탭바에 콘텐츠가 가려지지 않게 함(§6 "디바이스별 세부 규칙" 요구사항) |
| `md`(≥768px) | `GlobalNav`가 `position: static`으로 전환되어 헤더 안에서 워드마크 옆 가로 탭으로 표시(§6 "상단 탭 내비게이션으로 전환"), `<main>` 하단 여백도 기본값(24px)으로 복귀 |
| `xl`(≥1280px) | `<main>`에 `max-width: 1200px; margin-inline: auto`를 적용해 "본문 최대 1200px 중앙 정렬"(§6) 구현. 헤더 내부 바(`.site-header__bar`)도 동일하게 1200px 중앙 정렬해 헤더와 본문의 좌우 여백이 일치하게 함 |

`sm`(≥640px, 카드 그리드 2열)과 `lg`(≥1024px, 조건 필터 사이드 패널)은 각각 화면 콘텐츠(홈 요약 카드, 스크리닝 조건 폼)에 종속된 규칙이라 이번 유닛에서 구현하지 않았다(§2 편차 참조).

### 1-4. 접근성 (04-ux-design.md §5)

- **키보드 내비게이션**: `GlobalNav`의 3개 링크는 표준 `<a>`(Next `Link`)라 Tab으로 도달 가능하고, DOM 순서(스킵링크 → 배너 링크 → 워드마크 → 홈/스크리닝/검색 탭 → 본문 → 푸터)가 시각 순서와 일치한다. 기존 전역 포커스 스타일(`a:focus-visible { outline: 2px solid var(--color-focus-ring) }`, `globals.css`)이 별도 추가 없이 `GlobalNav` 링크에도 그대로 적용된다(선택자가 `a` 전체를 대상으로 하므로).
- **스크린리더 라벨**: `<nav aria-label="주요 메뉴">`로 랜드마크를 명확히 구분했고, 현재 페이지는 `aria-current="page"`로 프로그래밍적으로 공지된다(색상만으로 표시하지 않음 — 활성 링크는 색상 변경 + `aria-current` 텍스트 시맨틱을 함께 사용).
- **포커스 트랩**: 04-ux-design.md §5-3이 요구하는 포커스 트랩은 "모바일 바텀시트(조건 필터 패널)"에 한정된 요구사항이며, 이 컴포넌트는 §2-2 `ConditionFilterPanel`(UNIT-07 범위)이다. 이번 유닛의 `GlobalNav`는 상시 노출되는 고정 탭바일 뿐 열고 닫는 오버레이/모달이 아니므로, 포커스를 가둘 대상 자체가 없다. 따라서 이번 유닛에는 적용 대상이 없음을 §2 편차에 명시한다(임의로 불필요한 트랩 유틸리티를 미리 만들지 않음 — 과설계 방지).
- **200% 확대**: `GlobalNav` 링크가 `flex: 1`(모바일)로 균등 분배되고 텍스트가 길지 않아(2~5자) 200% 확대 시에도 줄바꿈만 될 뿐 가로 스크롤을 유발하지 않는다(수동 확인 필요 항목 §3-1에 재확인 요청 남김).

### 1-5. 플레이스홀더 라우트 (`frontend/src/app/screener/page.tsx`, `frontend/src/app/stocks/page.tsx`, 신규)

- `GlobalNav`가 `/screener`, `/stocks`를 가리키지만 아직 해당 화면(UNIT-07/UNIT-06 범위)이 없어 404가 나므로, `frontend/src/app/page.tsx`(UNIT-04가 만든 홈 플레이스홀더)와 동일한 패턴으로 "어느 유닛이 실제 구현을 담당하는지"를 안내하는 최소 텍스트 페이지를 각각 추가했다.
- 각 페이지에 `metadata.title`을 지정해 페이지 이동 시 브라우저 탭 제목이 바뀌도록 했다(스크린리더 사용자가 `Link` 클릭 후 어느 페이지로 이동했는지 문서 제목으로도 인지할 수 있도록 — §5-4 "동적 변화는 공지되어야 한다" 원칙의 연장으로 판단해 추가. 필수 스펙은 아니었으나 접근성 관점에서 비용이 거의 없어 포함).
- 두 페이지 모두 실제 데이터/폼/리스트를 전혀 포함하지 않는다(임의 기능 추가 금지 원칙 준수).

---

## 2. 설계서 대비 편차 (사유 포함)

1. **포커스 트랩 미구현** — 위 §1-4에서 설명한 대로, 04-ux-design.md §5-3의 포커스 트랩 요구사항은 모바일 바텀시트(`ConditionFilterPanel`, UNIT-07 범위)에 한정되며 이 유닛이 만드는 `GlobalNav`(상시 노출 고정 탭바)에는 열고 닫는 오버레이가 없어 적용 대상이 없다. UNIT-07이 바텀시트를 구현할 때 이 요구사항을 이행해야 한다.
2. **`sm`/`lg` 브레이크포인트 미구현** — 04-ux-design.md §6 표의 `sm`(카드 그리드 2열)과 `lg`(조건 필터 사이드 패널 전환)는 각각 홈 요약 카드(UNIT-08)와 스크리닝 조건 폼(UNIT-07)이라는 특정 화면 콘텐츠에 종속된 규칙이다. 이번 유닛은 콘텐츠가 없는 셸만 만들므로 해당 CSS를 미리 만들지 않았다 — 각 콘텐츠 유닛이 자신의 컴포넌트에 해당 브레이크포인트 스타일을 추가해야 한다(추측성 선반영 금지, 과설계 방지).
3. **플레이스홀더 페이지의 시각적 스타일 없음** — `/screener`, `/stocks`는 UNIT-04의 홈 플레이스홀더와 동일하게 안내 문구만 있는 순수 텍스트다. 04-ux-design.md §2-2/§2-3이 정의한 실제 폼/리스트/빈 상태 UI는 전혀 반영하지 않았다(그 화면들의 소관 유닛에서 구현).
4. **하단 탭바 높이 여백(56px)은 근사치** — `<main>`의 `padding-bottom: calc(24px + 56px)`에서 56px는 실제 렌더링된 탭바 높이(최소 44px + 테두리 1px ≈ 45px)에 여유를 더한 근사값이다. 설계서가 정확한 px 수치를 못박지 않았으므로("본문 가시 영역을 과도하게 줄이지 않도록") 안전 마진을 더한 것이며, 실제 브라우저에서 과도한 공백이나 부족한 여백이 없는지는 §3 수동 확인 항목에 남긴다.

---

## 3. 수동으로 확인이 필요한 부분 (6단계 테스터에게)

1. **실제 브라우저/디바이스 반응형 확인**: 이번 검증은 `npm run build`/`npm run dev` + `curl`로 렌더링된 HTML/CSS 마크업만 확인했다. 실제 브라우저(또는 브라우저 개발자도구 반응형 모드)에서 (a) 768px 미만에서 하단 탭바가 실제로 화면 하단에 고정되는지, (b) 768px 이상에서 헤더 안 가로 탭으로 정확히 전환되는지, (c) 1280px 이상에서 헤더/본문이 1200px로 중앙 정렬되는지, (d) iPhone SE급(높이 667px 이하) 좁은 세로 화면에서 배너(2줄 확장 시)+헤더+하단 탭바로 인해 본문 가시 영역이 과도하게 줄어들지 않는지를 재검증해야 한다.
2. **200% 확대/줄바꿈**: 브라우저 200% 확대 시 `GlobalNav` 텍스트가 겹치거나 가로 스크롤을 유발하지 않는지 실제 확인이 필요하다(§1-4에 근거는 남겼으나 실측 아님).
3. **하단 탭바 여백(56px) 근사치 검증**: 실제 렌더링 결과에서 탭바와 본문 마지막 콘텐츠 사이 간격이 시각적으로 부자연스럽지 않은지 확인(§2 편차 4 참조). 필요 시 정확한 px로 조정.
4. **스크린리더 실기 테스트**: `aria-current="page"`가 VoiceOver/NVDA 등 실제 스크린리더에서 "현재 페이지"로 올바르게 공지되는지는 코드 리뷰만으로는 완전히 보장할 수 없다(HTML 시맨틱은 표준을 따름).
5. **Lighthouse/axe 자동 접근성 스캔**: 이번 유닛은 수동 코드 리뷰 + 로컬 렌더링 확인만 수행했고, 별도 접근성 자동화 도구(Lighthouse/axe-core)는 실행하지 않았다.

---

## 4. 로컬 동작 확인 로그

- `npx tsc --noEmit` → 오류 없음.
- `npm run lint`(ESLint 9, `eslint-config-next` flat config, `jsx-a11y` 규칙 포함) → 0 error, 0 warning.
- `npm run build`(`prebuild` 금지어 린트 포함) → `금지표현 검사 통과 (검사 파일 14개)` 후 `next build` 성공. 라우트 5개 정상 생성 확인: `/`, `/_not-found`, `/about`, `/screener`, `/stocks`(전부 Static).
- `npm run dev` 실행 후 `curl`로 직접 확인:
  - `GET /` 응답 HTML에서 `<nav class="global-nav" aria-label="주요 메뉴">` 존재, 홈 링크(`href="/"`)에만 `aria-current="page"` 부여됨을 확인.
  - `GET /screener` 응답에서는 조건 스크리닝 링크(`href="/screener"`)에만 `aria-current="page"`가 이동됨을 확인(경로별 활성 탭 전환 동작 검증).
  - `GET /stocks` → HTTP 200 (플레이스홀더 페이지 정상 서빙, 404 아님).
  - `/screener`, `/stocks` 응답 HTML 모두에 `class="disclaimer-banner"`와 `skip-link`가 그대로 존재함을 확인(REQ-007 회귀 없음 — 신규 라우트도 루트 레이아웃을 상속하므로 배너/스킵링크가 자동으로 포함됨).
- 위 `npm run dev` 프로세스는 확인 후 종료했다.

---

## 5. 게이트 1 — 정적 분석/린트 결과

- **프론트엔드**: `eslint.config.mjs`(ESLint 9, flat config, `eslint-config-next` — `jsx-a11y` 규칙 포함) 존재 → `npm run lint` 실행, 0 error/0 warning. TypeScript strict 모드(`tsconfig.json`) → `npx tsc --noEmit` 통과.
- UNIT-04가 신설한 금지어 검사(`npm run build`의 `prebuild`)도 이번 유닛이 추가한 신규 텍스트(`GlobalNav` 라벨, 플레이스홀더 페이지 문구)를 포함해 정상 통과했다(검사 파일 수가 이전 대비 3개 늘어난 14개로 확인됨 — 신규 파일이 스캔 대상에서 누락되지 않았음을 재확인).
- **백엔드**: 이번 유닛은 백엔드 코드를 전혀 수정하지 않았다(변경 파일 전부 `frontend/` 하위, `docs/harness/traceability.md` 제외). 별도 백엔드 정적 분석 재실행은 회귀 위험이 없어 생략했다.
- 설정이 없어서 건너뛴 검사는 없다.

---

## 6. 게이트 2 — 자체 코드 리뷰 체크리스트

- [x] **설계서/디자인서 명세와 실제 구현이 일치하는가** — 04-ux-design.md §1-0(내비게이션 3항목 구성)·§4(`GlobalNav` 상태/변형: 데스크톱 상단 탭/모바일 하단 탭바, `aria-current="page"`)·§6(브레이크포인트별 레이아웃 변화)을 1:1로 대응시켜 구현했다(§1 참조). 구현하지 않은 부분(포커스 트랩, `sm`/`lg` 브레이크포인트)은 범위 밖 사유를 §2에 명시했다.
- [x] **에러 처리가 누락된 경로가 없는가** — `GlobalNav`는 순수 표시/네비게이션 컴포넌트로 비동기 호출이나 사용자 입력 처리가 없어 별도 에러 경로가 필요 없다. `isActive()` 함수는 `pathname`이 `usePathname()`에서 항상 문자열로 반환되는 Next.js 계약에 의존하며, 예외를 삼키는 `try/catch`나 무시된 실패 경로가 없다.
- [x] **입력값 검증이 시스템 경계(사용자 입력, 외부 API 응답)에서 이루어지는가** — 이번 유닛은 사용자 입력 폼이나 외부 API 응답을 다루지 않는다(순수 네비게이션/레이아웃). 해당 없음.
- [x] **하드코딩된 시크릿/자격증명이 없는가** — API 키/토큰/자격증명을 다루는 코드가 없다. 확인 결과 없음.
- [x] **범위를 벗어난 변경(곁다리 리팩터링 등)이 섞여 있지 않은가** — `DisclaimerBanner`/`Footer`/`SkipLink`/`DataFreshnessBadge`/기존 `/about`·`/` 페이지는 전혀 수정하지 않았다. 실제 화면 콘텐츠(검색 폼, 조건 필터, 결과 리스트, 시장 요약 카드)는 만들지 않았다(각각 UNIT-06/07/08 범위). 변경된 파일은 `Header.tsx`(확장), `globals.css`(네비게이션/브레이크포인트 CSS 추가), `copy.ko.json`(nav 키 추가), `GlobalNav.tsx`(신규), `screener/page.tsx`·`stocks/page.tsx`(신규 플레이스홀더), `traceability.md`(REQ-013 갱신)뿐이다.

---

## 7. 6단계 테스터를 위한 인수 조건 (Acceptance Criteria)

**AC-1 (전역 내비게이션 구성 — 04-ux-design.md §1-0/§4)**
- `frontend/`에서 `npm run dev` 실행 후 `/` 페이지 HTML에 `<nav aria-label="주요 메뉴">`가 존재하고, 그 안에 정확히 3개의 링크(`href="/"`, `href="/screener"`, `href="/stocks"`, 라벨 각각 "홈"/"조건 스크리닝"/"종목 검색")만 있어야 한다(4번째 이상의 메뉴 항목이나 `/about` 링크가 이 `<nav>` 안에 없어야 함 — `/about`은 배너/푸터에만 존재).
- 각 라우트(`/`, `/screener`, `/stocks`)에 접속했을 때, 해당 라우트와 일치하는 링크에만 `aria-current="page"`가 부여되고 나머지 2개 링크에는 없어야 한다.

**AC-2 (라우트 존재/404 방지)**
- `/screener`, `/stocks` 각각 `curl -o /dev/null -w "%{http_code}"`로 확인 시 HTTP 200이어야 한다(404 아님).
- 두 페이지 모두 실제 검색/조건 폼 기능은 없어야 한다(플레이스홀더 안내 문구만 존재 — UNIT-06/07이 나중에 이 파일을 실제 화면으로 교체).

**AC-3 (반응형 브레이크포인트 — 04-ux-design.md §6)**
- 브라우저 뷰포트 너비를 768px 미만으로 설정하면 `GlobalNav`가 화면 최하단에 고정되어야 한다(스크롤해도 위치가 바뀌지 않음). 768px 이상으로 설정하면 `GlobalNav`가 헤더 내부(워드마크 오른쪽)에 가로로 배치되어야 하며 더 이상 화면 하단에 고정되지 않아야 한다.
- 코드 리뷰로 확인: `frontend/src/app/globals.css`의 `.global-nav`가 기본(모바일) `position: fixed; bottom: 0`이고 `@media (min-width: 768px)` 블록에서 `position: static`으로 재정의되는지.
- 1280px 이상 뷰포트에서 `<main>`이 `max-width: 1200px`로 중앙 정렬되는지 코드 리뷰(`@media (min-width: 1280px)` 블록) 및 실제 브라우저 렌더링으로 확인.

**AC-4 (접근성 — 04-ux-design.md §5)**
- 키보드만으로 Tab 키를 눌러 스킵 링크 → 배너 링크 → 워드마크 → 홈/조건 스크리닝/종목 검색 순서로 포커스가 이동해야 하며, 각 포커스 지점에서 시각적 포커스 링(`outline`)이 보여야 한다(`outline: none`으로 제거된 요소가 없어야 함).
- `GlobalNav` 각 링크는 모바일 뷰포트(768px 미만)에서 `min-height: 44px` 이상이어야 한다(코드 리뷰: `.global-nav__link`의 `min-height` 값 확인).
- `aria-current="page"`가 색상 변경과 함께 프로그래밍적으로도 존재해야 한다(색상에만 의존하지 않음).

**AC-5 (기존 REQ-007/006 회귀 없음)**
- `/screener`, `/stocks` 응답 HTML에도 `class="disclaimer-banner"`(면책 배너)와 `skip-link`(스킵 링크)가 그대로 존재해야 한다(신규 라우트 추가로 인한 공통 레이아웃 회귀가 없어야 함).

**AC-6 (금지표현 가이드라인 회귀 없음 — REQ-008)**
- `cd frontend && npm run lint:copy`(또는 `npm run build`)가 이번 유닛이 추가한 신규 파일(`GlobalNav.tsx`, `screener/page.tsx`, `stocks/page.tsx`, `copy.ko.json` 갱신분)을 포함해 종료 코드 0으로 통과해야 한다.

**AC-7 (정적 분석 게이트)**
- `cd frontend && npx tsc --noEmit`, `npm run lint` 모두 오류/경고 없이 통과해야 한다.

---

## 8. 다음 단계

- 6단계(단위테스트)를 이 노트에 대해 즉시 호출해야 한다.
- UNIT-06(종목 검색/상세)·UNIT-07(스크리닝)·UNIT-08(시장 동향)은 이번 유닛이 만든 `/screener`·`/stocks` 플레이스홀더 페이지를 실제 화면으로 교체해야 하며, `Header`/`GlobalNav`는 그대로 재사용하고 임의로 새 헤더/내비게이션을 만들지 않아야 한다(traceability.md REQ-013 비고에 명시).
- UNIT-07이 `ConditionFilterPanel`(모바일 바텀시트)을 구현할 때, 이번 유닛에서 미룬 포커스 트랩(§5-3)을 반드시 이행해야 한다(§2 편차 1 참조).
