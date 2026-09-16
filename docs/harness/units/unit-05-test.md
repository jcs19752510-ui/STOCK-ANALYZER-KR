# 테스트 결과서 (Test Result Report) — UNIT-05

## 1. 개요
- 테스트 대상: 작업단위 UNIT-05(반응형 UI 셸 / 공통 네비게이션, REQ-013) — `frontend/src/components/GlobalNav.tsx`(신규), `frontend/src/components/Header.tsx`(확장), `frontend/src/app/globals.css`(반응형 CSS 추가), `frontend/src/app/screener/page.tsx`·`frontend/src/app/stocks/page.tsx`(신규 플레이스홀더), `frontend/src/content/copy.ko.json`(`nav.*` 키 추가)
- 테스트 유형: 단위(Unit) — 6단계
- 테스트 목적: 5단계(`unit-05-note.md`) 산출물이 인수 조건(AC-1~AC-7)을 실제로 만족하는지 **독립 재현**으로 증명하고, 5단계 자체 보고(특히 "실제 브라우저 확인은 수동 확인 필요"로 남긴 항목·포커스 트랩 범위 판단·플레이스홀더 UX 적절성)를 신뢰하지 않고 재검증한다.
- 관련 산출물: `docs/harness/units/unit-05-note.md`(입력 계약, §7 AC-1~AC-7), `docs/harness/04-ux-design.md`(v3, PASS, §1-0/§4/§5/§6), `docs/harness/03-system-design.md`(v4, §2-1), `docs/harness/traceability.md`(REQ-013)
- 테스트 수행자(에이전트): 06-unit-tester
- 테스트 일시: 2026-09-16

## 2. 테스트 범위 및 제외 범위
- 범위(In-Scope): AC-1~AC-7 전 항목 독립 재현, 코디네이터가 명시적으로 지시한 6개 중점 확인 사항(반응형 브레이크포인트 실동작, 접근성/키보드/터치타겟, 포커스 트랩 범위 판단의 원문 대조, 플레이스홀더 라우트의 404 방지/UX 명확성, UNIT-04 회귀(면책 배너·금지표현 린트), 전체 빌드/린트/타입체크), AC에 없는 위험 기반 경계 케이스(빈 라우트/미존재 라우트/prefix 충돌 라우트에서의 `isActive()` 오탐 가능성, 실제 Chrome 렌더링을 통한 반응형 검증)
- 제외 범위 및 사유:
  - 실제 물리 모바일 기기(iOS/Android)·실제 스크린리더(VoiceOver/NVDA) 실기 테스트 — 이 테스트 환경에 물리 기기/스크린리더가 없음. 대신 헤드리스 Chrome(DevTools Protocol)으로 9개 뷰포트 폭에서 실제 컴퓨티드 레이아웃(`getBoundingClientRect`, `getComputedStyle`, `scrollWidth`)을 측정해 대체 검증했다(§4 TC-009/TC-010). 스크린리더 실기 테스트는 `unit-05-note.md` §3-4가 이미 "6단계 테스터에게" 수동 확인이 필요하다고 남긴 항목으로, 이번에도 도구 제약상 완전히 닫지 못했음을 §7에 리스크로 승계한다(신규로 발견한 결함이 아니라 5단계가 이미 투명하게 남긴 항목의 재확인 실패).
  - Lighthouse/axe-core 등 자동 접근성 스캔 도구 실행 — 이 환경에 설치되어 있지 않고 네트워크 설치 여부가 불확실해 생략했다(`unit-05-note.md` §3-5와 동일 사유). 수동 코드 리뷰 + CDP 실측으로 핵심 접근성 요구사항(시맨틱 랜드마크, `aria-current`, 포커스 인디케이터, 색 대비)은 별도로 확인했다(§4 TC-013~015, TC-031).
  - 백엔드 재테스트 — 이번 유닛은 `frontend/` 하위 파일만 변경했음을 `git diff --stat`으로 직접 확인했다(§4 TC-030). 백엔드 회귀 위험이 없어 `pytest`/`ruff` 재실행은 범위에서 제외한다.
  - `sm`(≥640px 카드 그리드)·`lg`(≥1024px 조건 필터 사이드 패널) 브레이크포인트의 실제 콘텐츠 검증 — 이번 유닛은 콘텐츠가 없는 셸만 구현했으므로 해당 CSS 자체가 존재하지 않는다(§4 TC-027에서 이 판단이 04-ux-design.md 원문과 일치하는지만 대조 확인했다).

## 3. 테스트 환경
- 실행 환경: Windows 10 Pro, Node.js v24.18.0, Next.js 16.3.5(Turbopack), React 19.3.0, TypeScript 6.0.3, ESLint 9.39.5(`eslint-config-next`, `jsx-a11y` 포함)
- 브라우저(실제 렌더링 검증용): Google Chrome 152.0.7977.83 — `--headless=new` + Chrome DevTools Protocol(CDP)로 `Emulation.setDeviceMetricsOverride`를 이용해 320/375/428/640/767/768/1024/1280/1500px 9개 뷰포트 폭에서 실제 레이아웃을 측정하고 스크린샷을 캡처했다.
- 테스트 데이터: 별도 DB/시드 데이터 불필요(이 유닛은 정적 셸/네비게이션만 다룸, API 호출 없음)
- 전제 조건: `cd frontend && npm run dev`(또는 `npm run build && npm run start`)로 로컬 서버가 `http://localhost:3000`에 기동되어 있어야 함. 테스트 종료 후 기동한 `next dev`/`next start`/헤드리스 Chrome 프로세스는 모두 종료했고, 테스트 과정에서 일시적으로 수정했던 `copy.ko.json`/`screener/page.tsx`(금지어 주입 재현용)는 원상복구해 `git status`가 테스트 시작 전과 동일함을 최종 확인했다(§4 TC-018/019 비고).

## 4. 테스트 케이스 및 결과

| ID | 시나리오 | 사전조건 | 실행 절차 | 예상 결과 | 실제 결과 | Pass/Fail | 비고 |
|----|----------|----------|-----------|-----------|-----------|-----------|------|
| TC-001 | AC-1: `/` 페이지 `GlobalNav` 구조/라벨 | `npm run dev` 기동 | `curl http://localhost:3000/` 후 `<nav aria-label="주요 메뉴">` 내부 마크업 확인 | `<nav aria-label="주요 메뉴">` 안에 `href="/"`(홈)·`href="/screener"`(조건 스크리닝)·`href="/stocks"`(종목 검색) 정확히 3개 링크만 존재, `/about` 링크 없음 | 정확히 일치. `<nav class="global-nav" aria-label="주요 메뉴"><ul>...</ul></nav>` 안에 3개 `<a class="global-nav__link">`만 존재, 라벨 "홈"/"조건 스크리닝"/"종목 검색" 정확, `/about` 링크 없음 | PASS | AC-1 불릿1 |
| TC-002 | AC-1: `/`에서 `aria-current` | 동일 | `/` HTML에서 `aria-current="page"` 개수·위치 확인 | 홈 링크(`href="/"`)에만 부여, 나머지 2개는 없음 | `aria-current="page"` 정확히 1개, `href="/"` 링크에만 부여 확인 | PASS | AC-1 불릿2 |
| TC-003 | AC-1: `/screener`에서 `aria-current` 이동 | 동일 | `curl http://localhost:3000/screener` | 조건 스크리닝 링크에만 `aria-current="page"` | 정확히 이동됨(홈/검색에는 없음) | PASS | AC-1 불릿2 |
| TC-004 | AC-1: `/stocks`에서 `aria-current` 이동 | 동일 | `curl http://localhost:3000/stocks` | 종목 검색 링크에만 `aria-current="page"` | 정확히 이동됨 | PASS | AC-1 불릿2 |
| TC-005 | AC-2: 플레이스홀더 라우트 HTTP 상태 | 동일 | `curl -o /dev/null -w "%{http_code}" /screener`, `/stocks` | 둘 다 200 | 둘 다 200(404 아님) | PASS | AC-2 불릿1 |
| TC-006 | AC-2: 플레이스홀더에 실제 기능 없음 | 동일 | `/screener`,`/stocks` HTML을 `<form`,`<input`,`<select`로 grep | 매칭 0건(안내 문구만) | 매칭 0건. `<h1>`+`<p>` 안내 문구만 존재 확인 | PASS | AC-2 불릿2 |
| TC-007 | AC-3: 브레이크포인트 CSS 정의(코드 리뷰) | 소스 열람 | `globals.css`에서 `.global-nav`/`@media` 블록 확인 | 기본 `position:fixed;bottom:0`, `@media(min-width:768px)`에서 `position:static`, `@media(min-width:1280px)`에서 `main{max-width:1200px;margin-inline:auto}` | 정확히 일치(라인 104-190) | PASS | AC-3 불릿2/3 코드 리뷰 요구사항 |
| TC-008 | AC-3: 소스↔프로덕션 빌드 CSS 바이트 대조 | `npm run build` 완료 | `.next/static/chunks/*.css`에서 `.global-nav`/`main`/`@media` 규칙 추출, 소스와 대조 | 축약(minify)만 있고 값(임계치/속성) 변경 없음 | 완전히 일치(예: `@media (min-width:768px){.global-nav{...position:static}}`, `@media (min-width:1280px){main{max-width:1200px;margin-inline:auto}}` 그대로 존재) | PASS | 빌드 파이프라인이 미디어쿼리 값을 왜곡하지 않음을 확인(코드 리뷰만으로는 놓칠 수 있는 "빌드 후 실제 반영" 검증) |
| TC-009 | **AC-3: 실제 Chrome 9개 뷰포트 폭 실측(320/375/428/640/767/768/1024/1280/1500px)** | 헤드리스 Chrome + CDP 연결, `npm run start`(프로덕션 빌드) 기동 | CDP `Emulation.setDeviceMetricsOverride`로 각 폭 설정 → `Runtime.evaluate`로 `.global-nav`의 `getBoundingClientRect()`/`getComputedStyle().position`/`document.documentElement.scrollWidth` 측정 | 767px 이하: `position:"fixed"`, `nav`가 화면 최하단(`bottom≈viewport height`); 768px 이상: `position:"static"`, 헤더 내부(워드마크 오른쪽)로 이동; 전 구간 `scrollWidth <= innerWidth`(가로 스크롤 없음) | 정확히 일치. 767px: `navPosition:"fixed"`, `navRect.top=855,bottom=900`(뷰포트 900 하단에 고정). **768px에서 정확히 전환**: `navPosition:"static"`, `navRect.x=486.28`(헤더 안, 워드마크 우측). 320~1500px **전 구간에서 `hasHorizontalOverflow:false`**(가로 스크롤 없음, 200% 확대와 유사한 좁은 실효 뷰포트에서도 오버플로 없음을 뒷받침) | PASS | **코디네이터 지시 1항목 핵심 검증.** 5단계 note는 "실제 브라우저 확인 필요"로 남겼던 항목(§3-1)을 6단계가 실제 Chrome 컴퓨티드 레이아웃으로 닫았다. 상세 원시 데이터는 검증 로그 참조 |
| TC-010 | AC-3: 1280px/1500px 본문 1200px 중앙 정렬 실측 | 동일 | 각 폭에서 `.site-header__bar`의 `getBoundingClientRect().width`와 `x` 좌표 확인 | `width===1200`, `x===(뷰포트폭-1200)/2` | 1280px: `width:1200, x:40`((1280-1200)/2=40, 정확히 일치). 1500px: `width:1200, x:150`((1500-1200)/2=150, 정확히 일치). 1024px(아직 xl 미만): `width:992`(고정폭 아님, 콘텐츠에 맞춰 유동) | PASS | AC-3 불릿3 |
| TC-011 | (테스트 방법론 검증) CLI 스크린샷 방식의 신뢰성 재확인 | 동일 | `chrome --headless=new --screenshot=... --window-size=375,900`로 촬영한 이미지에서 배너 텍스트/3번째 탭이 프레임 우측에서 잘려 보이는 현상 발견 → CDP `Page.captureScreenshot`(완전한 레이아웃 이후 캡처)로 동일 폭 재촬영해 교차검증 | 실제 오버플로 결함이면 두 방식 모두 잘림이 재현되어야 하고, 캡처 타이밍 아티팩트라면 CDP 방식에서는 정상 표시되어야 함 | TC-009에서 `scrollWidth<=innerWidth`(오버플로 없음)로 이미 확인했고, CDP `captureScreenshot`(레이아웃 완료 후 캡처)에서는 배너 텍스트가 정확히 2줄로 줄바꿈되고 3개 탭 전부 프레임 안에 정상 표시됨(잘림 없음) — CLI `--screenshot` 플래그가 리사이즈/레이아웃 완료 전에 캡처하는 도구 자체의 타이밍 아티팩트였음을 확정, **제품 결함 아님** | PASS(결함 아님으로 확정) | 이 발견 과정 자체를 투명하게 기록한다(규칙 B: "테스트 자체가 잘못 설계되어 결함을 놓치거나 오탐할 가능성을 의심"에 따른 자기 검증 사례). 최초 CLI 스크린샷만 보고 "AC-3 실패"로 오판할 뻔했으나 2차 교차검증(CDP 실측값 + CDP 스크린샷)으로 오탐임을 확정했다 |
| TC-012 | AC-4: DOM/탭 순서 | `/` HTML 획득 | body 내 `a`/`nav`/`main`/`footer` 태그 등장 순서를 파싱, 소스 전체에서 `tabIndex`/`tabindex` 사용 여부 grep | 스킵링크 → 배너 링크 → 워드마크 → (홈/조건 스크리닝/종목 검색) → 본문 → 푸터 순, `tabindex` 미사용(=DOM 순서가 곧 탭 순서) | 정확히 일치하는 순서 확인(`skip-link`→`disclaimer-banner__link`→`site-header__wordmark`→`global-nav__link`×3→`main#main-content`→`site-footer` 링크), 소스 전체에서 `tabIndex`/`tabindex` 매칭 0건 | PASS | AC-4 불릿1 |
| TC-013 | AC-4: 포커스 인디케이터 미제거 | 동일 | `globals.css` 전체에서 `outline:\s*none` 패턴 grep, `a:focus-visible` 규칙이 실제로 앵커 전체를 대상으로 하는지 확인 | 매칭 0건, `a:focus-visible{outline:2px solid ...}`가 `.global-nav__link`에도 적용(선택자 특정 제외 없음) | 매칭 0건 확인, `.global-nav__link`를 대상으로 한 `:focus`/`:focus-visible` 재정의(오버라이드)가 별도로 없어 전역 규칙이 그대로 적용됨을 확인 | PASS | AC-4 불릿1 |
| TC-014 | AC-4: 모바일 터치 타겟 44px 실측 | CDP 연결(폭 320/375/767px) | `getComputedStyle('.global-nav__link').minHeight` 및 실제 `getBoundingClientRect().height` 확인 | `min-height:44px`, 실제 렌더 높이 ≥44px | 320/375/767px 전부 `minHeight:"44px"`, 실제 렌더 `height:44`(정확히 44px). 폭(width)도 최소 106px(320px 폭 기준)로 44px를 크게 상회(AC 문면 범위 밖이나 위험 기반으로 추가 확인) | PASS | AC-4 불릿2. 768px 이상에서는 `minHeight:"0px"`(auto)로 전환되고 실제 높이 37px로 줄어드는데, 이는 AC-4가 "모바일 뷰포트(768px 미만)"로 범위를 명시했으므로 위반 아님(마우스 포인터 환경) |
| TC-015 | AC-4: `aria-current` + 색상 병행 | 소스 리뷰 + TC-002~004 결과 | `.global-nav__link[aria-current="page"]` 규칙과 실제 HTML의 `aria-current="page"` 속성 병존 확인 | 색상 변경(`color:var(--color-brand-primary)`)과 `aria-current="page"` 텍스트 시맨틱이 함께 존재 | 둘 다 확인됨(CSS 규칙 존재 + HTML 속성 실제 부여, TC-002~004) — 색상에만 의존하지 않음 | PASS | AC-4 불릿3 |
| TC-016 | AC-5: 신규 라우트 REQ-007/006 회귀 없음 | 동일 | `/screener`,`/stocks` HTML(개발 서버) + 프로덕션 빌드(`npm run build && start`) HTML 양쪽에서 `class="disclaimer-banner"`,`class="skip-link"` grep | 둘 다 존재 | 개발 서버·프로덕션 빌드 양쪽 모두 존재 확인(TC-023/024/025의 404/에러 경로에서도 동일하게 존재함을 추가 확인, 아래 참조) | PASS | AC-5 |
| TC-017 | AC-6: 금지표현 린트 베이스라인 | 동일 | `npm run lint:copy`, `npm run build`(prebuild 포함) 실행 | 종료 코드 0, "검사 파일 N개" 통과 로그 | 둘 다 exit 0, "금지표현 검사 통과 (검사 파일 14개)" — 5단계 note의 "14개" 수치와 독립 재확인 시에도 동일(TC-029) | PASS | AC-6 |
| TC-018 | AC-6(결함 헌팅): `copy.ko.json`의 `nav.screener`에 금지어 주입 | 동일 | `"screener": "조건 스크리닝"` → `"screener": "매수신호 스크리닝"`로 임시 수정 후 `node scripts/lint-forbidden-copy.mjs` 실행, 이후 원본으로 복구 후 재실행 | 주입 시 exit 1 + 파일:라인 정확히 보고, 복구 후 exit 0 | 주입 시 `EXIT_CODE=1`, `copy.ko.json:15 — 금지어 "매수신호"` 정확히 보고. 복구 후 `EXIT=0`, `git diff`로 원본과 완전히 동일함(unit-05가 도입한 `nav.*` 키 diff만 남고 그 외 차이 없음) 확인 | PASS | 신규 파일(카피 리소스의 신규 키)도 스캔 대상에 포함됨을 실제 주입으로 증명(단순 "포함될 것"이라는 추정이 아님) |
| TC-019 | AC-6(결함 헌팅): `screener/page.tsx` 본문에 금지어 주입 | 동일 | `<h1>조건 스크리닝</h1>` → `<h1>수익보장 스크리닝</h1>`로 임시 수정(TC-018의 `copy.ko.json` 오염 상태와 동시 유지한 채) 후 린트 실행 → 두 파일 모두 원복 후 재실행 | 2건(파일별 1건씩) 동시 보고, 원복 후 exit 0 | `screener/page.tsx:4 — 금지어 "수익보장"`, `copy.ko.json:15 — 금지어 "매수신호"` 2건 정확히 동시 보고(`총 2건`). 두 파일 모두 원복 후 `EXIT=0`, `git diff --stat`로 두 파일 모두 unit-05 기준 diff만 남고 추가 오염 없음 확인 | PASS | 신규 라우트 소스 파일(`.tsx`)도 스캔 대상 포함을 실제 주입으로 증명 |
| TC-020 | AC-7: TypeScript strict 통과 | 동일 | `npx tsc --noEmit` | 오류 0건 | 오류 0건(출력 없음) | PASS | AC-7 |
| TC-021 | AC-7: ESLint 통과 | 동일 | `npm run lint` | 오류/경고 0건 | 오류/경고 0건 | PASS | AC-7 |
| TC-022 | (위험 기반, AC 범위 밖) `/about`(nav 3항목에 속하지 않는 기존 라우트) 접속 시 오작동 없음 | 동일 | `curl /about` 후 nav 마크업 확인 | 크래시 없음, 3개 링크 중 어느 것도 `aria-current` 없음(About은 nav 항목이 아니므로) | 정상 렌더, `aria-current` 매칭 0건, 마크업 동일 | PASS | `isActive()`가 nav에 없는 경로에 대해서도 예외 없이 안전하게 동작함을 확인(빈 입력/예상 외 입력에 대한 방어) |
| TC-023 | (위험 기반) 완전 미존재 라우트(`/nonexistent-route-xyz`, 404) | 동일(프로덕션 빌드) | `curl -w "%{http_code}"` 및 HTML의 nav/배너/스킵링크 확인 | HTTP 404, 그러나 루트 레이아웃은 정상 상속되어 nav/배너/스킵링크는 그대로 존재, 서버 크래시 없음 | HTTP 404, nav 3개 링크 정상 렌더(`aria-current` 0건), `class="disclaimer-banner"`/`class="skip-link"` 존재 | PASS | REQ-007 면책 배너가 404 에러 경로에서도 누락되지 않음을 확인(AC-5가 명시하지 않은 경계지만 규제 요구사항 특성상 위험 기반으로 추가 확인) |
| TC-024 | (위험 기반, 잠재 결함 헌팅) prefix 충돌 라우트(`/screenerxyz`) | 동일 | `curl` 후 nav의 `aria-current` 개수 확인 | `isActive()`의 `pathname.startsWith(href+"/")` 로직이 `/screenerxyz`를 `/screener`의 하위 경로로 오인해 오탐(false positive)하지 않아야 함 | `aria-current` 매칭 **0건**(오탐 없음) — `startsWith(href + "/")`가 정확히 슬래시 경계까지 포함해 검사하므로 `/screenerxyz`(슬래시 없이 이어짐)는 매칭되지 않음 | PASS | `isActive()` 구현의 경계값 안전성 확인. 이 검사가 없었다면 향후 유사 이름의 라우트가 추가될 때 활성 탭 오탐 결함이 조용히 발생할 수 있었음 |
| TC-025 | (위험 기반, 향후 확장 대비) 존재하지 않는 하위 라우트(`/stocks/005930`) | 동일 | `curl` | HTTP 404(현재 동적 라우트 미구현, UNIT-06 범위), 크래시 없음, nav/배너 정상 | HTTP 404, nav/배너/스킵링크 정상 렌더 | PASS | UNIT-05 note가 "향후 `/stocks/[code]` 하위 라우트가 생겨도 상위 탭이 활성 유지" 목적으로 넣은 `startsWith(href+"/")` 방어 로직이, 그 라우트가 아직 없는 현재 시점에도 부작용(크래시/오탐) 없이 안전함을 확인 |
| TC-026 | (문서 대조, 코디네이터 지시 3) 포커스 트랩 범위 판단 검증 | `04-ux-design.md` 원문 열람 | `unit-05-note.md` §1-4/§2 편차1("포커스 트랩은 모바일 바텀시트=`ConditionFilterPanel`, UNIT-07 범위 한정")이 `04-ux-design.md` §5-3 원문과 일치하는지 대조 | 원문이 실제로 포커스 트랩을 "모바일 바텀시트(조건 필터 패널)"에만 한정해 요구하고 있어야 함(임의 축소가 아니어야 함) | `04-ux-design.md` §5-3(라인 373) 원문: "모바일 바텀시트(조건 필터 패널)는 열렸을 때 포커스 트랩(Tab이 시트 내부에서만 순환) 적용, `Esc` 키로 닫기, 닫을 때 포커스를 시트를 연 트리거 버튼으로 복귀." — `ConditionFilterPanel`은 §4 컴포넌트 표에서 "스크리닝 조건 입력"(UNIT-07 범위 컴포넌트)으로 명시됨. `GlobalNav`는 열고 닫는 오버레이가 아닌 상시 노출 탭바이므로 이 요구사항의 적용 대상이 아님 — **note의 주장은 원문과 정확히 일치, 임의 축소 아님** | PASS | 코디네이터가 명시적으로 의심하라고 지시한 항목. 대조 결과 결함 없음 |
| TC-027 | (문서 대조) `sm`/`lg` 브레이크포인트 미구현 사유 검증 | 동일 | `unit-05-note.md` §2 편차2가 `04-ux-design.md` §6 브레이크포인트 표(라인 392-398)와 일치하는지 대조 | `sm`(≥640px)이 "카드 그리드 2열"(홈 요약 카드=UNIT-08 콘텐츠), `lg`(≥1024px)가 "조건 필터 사이드 패널"(=UNIT-07 콘텐츠)로, 실제로 콘텐츠 종속 규칙이어야 함 | 원문과 정확히 일치. `sm`/`lg` 모두 아직 존재하지 않는 화면 콘텐츠(홈 요약 카드, 조건 필터 패널)에 결부된 규칙으로, 셸만 만드는 이 유닛에서 미리 구현하지 않은 것은 과설계 방지 원칙에 부합 | PASS | 이 유닛의 범위 축소가 아니라 정당한 범위 설정임을 확인 |
| TC-028 | (위험 기반, 코디네이터 지시 4) 플레이스홀더 UX 명확성 | `/screener`,`/stocks` HTML/스크린샷 | 렌더링된 실제 텍스트가 "기능이 아직 없다"는 사실을 사용자에게 명확히 전달하는지, 빈 화면으로 오인될 소지가 있는지 검토. `04-ux-design.md`의 `EmptyState` 컴포넌트 정의(§4)와 비교해 적용 가능성 검토 | 최소한 제목(h1) + 왜 비어있는지 설명하는 본문 텍스트가 있어야 하며, 완전한 공백 화면이어서는 안 됨 | `/screener`: `<h1>조건 스크리닝</h1>` + "조건 기반 스크리닝 화면은 후속 작업 단위(UNIT-07)에서 구현됩니다. 이 페이지는 전역 내비게이션 라우트가 정상 동작하는지 확인하기 위한 임시 자리표시자입니다." / `/stocks`도 동일 패턴. 완전한 공백이 아니며, 사용자가 "기능이 없다"가 아니라 "왜 없는지·언제 생기는지" 맥락까지 파악 가능 | PASS(단, 범위 한정 조건부 서술) | **04-ux-design.md의 `EmptyState`(§4, `no-query`/`no-search-result`/`no-screen-result`/`no-data-yet` 4개 변형)는 "기능은 있으나 데이터/결과가 없는 상태"를 위한 컴포넌트로, "기능 자체가 아직 개발되지 않은 상태"는 이 화이트리스트의 적용 대상이 아니다(설계서에 이 시나리오 자체가 정의되어 있지 않음 — 하네스 진행 중 임시 상태이기 때문). 따라서 이 페이지가 정식 `EmptyState` 컴포넌트를 사용하지 않은 것은 설계서 위반이 아니다. 다만 UNIT-04의 홈 플레이스홀더와 동일한 애드혹 패턴을 재사용한 것으로, 이 패턴 자체가 정식 컴포넌트 명세에 없다는 점은 §7 리스크로 남긴다 |
| TC-029 | (게이트 재확인) note가 보고한 "검사 파일 14개" 독립 재확인 | 동일 | `npm run build`의 prebuild 로그를 6단계가 별도로 재실행해 파일 수 확인 | "14개"와 일치 | "금지표현 검사 통과 (검사 파일 14개)" 동일하게 재현 | PASS | 5단계 보고를 그대로 베끼지 않고 독립 재실행으로 확인 |
| TC-030 | (게이트 재확인) 백엔드 무변경/회귀 없음 | 동일 | `git diff --stat`로 이번 유닛이 변경한 전체 파일 목록 확인 | `frontend/`·`docs/harness/` 하위 파일만 존재, 백엔드(`services/`,`shared/` 등) 무변경 | `docs/harness/traceability.md`, `docs/harness/units/unit-04-test.md`(v2 관련), `docs/harness/units/verify-log_unit-04-test.md`, `frontend/src/app/globals.css`, `frontend/src/components/Header.tsx`, `frontend/src/content/copy.ko.json` + 신규 파일(`GlobalNav.tsx`,`screener/page.tsx`,`stocks/page.tsx`,`unit-05-note.md`)만 변경, 백엔드 파일 0건 | PASS | 백엔드 회귀 재실행 불필요 판단의 근거 확보 |
| TC-031 | (위험 기반, WCAG 색 대비) 신규 텍스트 색상 대비 계산 | 소스 리뷰(토큰 값) | `.global-nav__link`(기본 `--color-text-secondary:#4b5563`)와 `[aria-current="page"]`(`--color-brand-primary:#1d4ed8`)를 배경 `#ffffff` 기준 WCAG 상대휘도 공식으로 대비비 계산 | 4.5:1 이상(본문 텍스트 기준) | 계산 결과 `#4b5563` on `#ffffff` ≈ **7.56:1**, `#1d4ed8` on `#ffffff` ≈ **6.71:1** — 둘 다 AA 기준(4.5:1) 및 AAA 기준(7:1)에 근접하거나 충족 | PASS | 두 토큰 모두 UNIT-04에서 이미 채택된 기존 토큰을 재사용한 것이라 신규 리스크는 낮았으나, `GlobalNav`라는 새 사용 맥락에서 독립적으로 재계산해 확인 |

> 정상 경로(TC-001~008, 016, 017, 020, 021, 026~030) + 경계값(TC-009, 010, 014, 024) + 예외/위험 입력(TC-018, 019, 022, 023, 025) + 접근성/비기능(TC-011~015, 031)을 모두 포함했다.

## 5. 커버리지
- 커버리지 지표: `unit-05-note.md` §7의 AC-1~AC-7 전 불릿(총 20개 불릿) 각각에 최소 1개 이상의 TC가 1:1로 대응됨(§4 "비고" 열에 AC 불릿 번호 명시). 코디네이터가 지시한 6개 중점 확인 사항도 전부 최소 1개 TC로 대응됨(TC-009/010=1항, TC-012~015/031=2항, TC-026=3항, TC-028=4항, TC-016/023=5항, TC-017/020/021/029/030=6항).
- 커버되지 않은 부분과 사유:
  1. 실제 물리 모바일 기기/실제 스크린리더(VoiceOver/NVDA) 실기 테스트 — 도구 부재. CDP 기반 실제 Chrome 레이아웃 실측(TC-009/010/014)과 시맨틱 마크업 검증(TC-012/013/015)으로 대체했으나, 이는 "표준 준수 브라우저의 계산된 레이아웃"과 "시맨틱이 올바름"을 증명할 뿐, 특정 스크린리더 제품이 실제로 어떻게 음성 출력하는지까지 보증하지 않는다.
  2. Lighthouse/axe-core 자동 접근성 스캔 — 환경 제약으로 미실행.
  3. 200% 브라우저 확대(줌) 자체의 실측 — 브라우저 "줌" 기능은 헤드리스 CDP의 `Emulation.setDeviceMetricsOverride`(뷰포트 폭 변경)와 완전히 동일한 메커니즘은 아니다. 다만 TC-009에서 320px(일반적인 375~428px 모바일 화면을 200% 확대했을 때의 실효 CSS 폭과 유사한 매우 좁은 폭)까지 내려가도 가로 스크롤이 발생하지 않음을 확인했으므로, 실제 200% 브라우저 확대에서도 유사하게 안전할 개연성이 높다고 판단한다(완전한 대체 증명은 아님).
  4. `sm`/`lg` 브레이크포인트의 실제 콘텐츠 동작 — 해당 콘텐츠(홈 요약 카드, 조건 필터 패널) 자체가 아직 없어 검증 대상이 존재하지 않는다(UNIT-07/08 범위, Not Applicable이지 커버리지 공백이 아님).

## 6. 결함(Defect) 목록

**결함 없음.** TC-001~031(총 31건) 전부 PASS, Fail 0건.

근거: AC-1~AC-7의 20개 불릿 전부 독립 재현으로 실제 결과와 예상 결과가 일치함을 확인했고(§4), 5단계가 스스로 "임의로 범위를 축소한 것 아닌지 의심하라"고 지시받은 포커스 트랩 판단(TC-026)과 브레이크포인트 범위 판단(TC-027)도 04-ux-design.md 원문과 대조해 실제로 일치함을 확인했다. 위험 기반으로 AC 범위 밖까지 확장한 경계 케이스(TC-022~025: 미존재 라우트/prefix 충돌/nav 밖 라우트에서의 크래시·오탐 여부, TC-018/019: 금지어 스캐너의 신규 파일 실제 탐지 여부)에서도 결함을 발견하지 못했다. 유일하게 "결함처럼 보였던" 현상(TC-011, CLI 스크린샷 크롭)은 재현 방법 자체의 타이밍 아티팩트로 확정했고, CDP 기반 정밀 측정(TC-009)과 CDP 스크린샷(TC-011) 양쪽으로 실제 제품에는 결함이 없음을 교차검증했다.

## 7. 리스크 및 잔존 이슈
- **(승계, 신규 아님)** 실제 물리 모바일 기기·스크린리더(VoiceOver/NVDA) 실기 테스트, Lighthouse/axe 자동 스캔, 실제 브라우저 200% 확대 조작 자체는 이번 6단계에서도 도구 제약으로 완전히 닫지 못했다(§5 커버리지 1~3). 5단계 note §3이 이미 투명하게 남긴 항목이며, 6단계는 이를 은폐하지 않고 승계한다. UNIT-06~08이 실 데이터 화면을 이 `GlobalNav`/`Header` 위에 쌓기 전, 별도 접근성 감사(가능하면 실기기/스크린리더 포함)를 한 번은 수행할 것을 권고한다.
- **(신규, Low, 결함 아님)** 플레이스홀더 라우트(`/screener`,`/stocks`)가 04-ux-design.md의 정식 `EmptyState` 컴포넌트 명세를 사용하지 않고 UNIT-04의 애드혹 텍스트 패턴을 재사용했다(TC-028). 이는 설계서 위반이 아니다(설계서에 "기능 미개발 상태" 시나리오 자체가 정의되어 있지 않으므로) — 다만 UNIT-06/07이 이 플레이스홀더를 실제 화면으로 교체할 때, 최종 화면은 `EmptyState`(§4) 등 정식 컴포넌트 명세를 따라야 하며 이 임시 패턴을 그대로 승격시키지 않도록 UNIT-06/07 착수 시 참고해야 한다.
- 코디네이터 지시로 발견된 특이사항(결함 아님, 방법론 기록): 초기 CLI 헤드리스 Chrome `--screenshot` 촬영에서 뷰포트 375px 폭 이미지가 배너 텍스트/3번째 탭이 잘려 보이는 현상이 있었다(TC-011). 이를 그대로 "AC-3 실패"로 단정하지 않고 CDP 기반 정밀 측정 + CDP 자체 스크린샷으로 교차검증해 실제로는 오버플로가 없음(스크린샷 캡처 타이밍 도구 아티팩트)을 확정했다. 이 과정 자체를 투명하게 남긴다(규칙 B "테스트 자체가 잘못 설계되어 결함을 놓치거나 오탐할 가능성을 항상 의심" 이행 사례).

## 8. 결론 및 판정
- [x] **PASS** — 다음 단계(07 통합테스트) 진행 가능
- [ ] CONDITIONAL PASS — 조건: (해당 없음)
- [ ] FAIL — (해당 없음)

**판정 근거**: AC-1~AC-7(20개 불릿) 전부 독립 재현 PASS, 결함 0건. 코디네이터가 지시한 6개 중점 확인 사항 전부 답변 완료:
1. 반응형 브레이크포인트 실동작 — 코드 리뷰(TC-007) + 빌드 산출물 대조(TC-008) + **실제 Chrome CDP 9개 뷰포트 실측**(TC-009/010)으로 확정. 5단계가 "수동 확인 필요"로 남긴 항목을 이번 6단계가 실제 브라우저 엔진으로 닫았다.
2. 접근성(키보드 전체 탐색, `aria-current` 실경로 반영, 터치 타겟 44px) — TC-002~004(경로별 `aria-current`), TC-012(DOM=탭 순서, tabindex 미사용), TC-013(포커스 링 미제거), TC-014(CDP 실측 44px), TC-015(색상+시맨틱 병행) 전부 PASS.
3. 포커스 트랩 범위 판단 대조 — TC-026에서 `04-ux-design.md` §5-3 원문과 정확히 대조해 note의 "UNIT-07 소관" 판단이 임의 축소가 아님을 확정.
4. 플레이스홀더 라우트의 UX 명확성 — TC-028에서 실제 렌더링 텍스트로 "빈 화면 아님"을 확인했고, 정식 `EmptyState` 미사용은 설계서 공백(시나리오 자체 미정의) 때문임을 근거와 함께 리스크로 남겼다(결함 아님).
5. UNIT-04 회귀(면책 배너/금지표현 린트) — TC-016(배너/스킵링크 유지, 404 경로까지 확장 확인), TC-017~019(린트 베이스라인 + 2건의 실제 금지어 주입/탐지/원복)로 확정. 신규 파일이 스캔 대상에서 누락되지 않음을 "그럴 것이다"가 아니라 실제 주입으로 증명했다.
6. 전체 빌드/린트/타입체크 재실행 — TC-020/021(tsc/eslint), TC-017(build+prebuild), TC-029(파일 수 독립 재확인), TC-030(백엔드 무변경 확인) 전부 PASS.

## 9. 내부 검증 (최소 2회, `verification-log-template.md` 사용)
- 1차 검증 결과 요약: AC-1~AC-7 20개 불릿 전부 TC로 커버됐는지 추적표 대조, TC의 "예상 결과"가 실제로 `unit-05-note.md`/`04-ux-design.md` 원문에 근거하는지(추측 아님) 재확인. 결함 1건(TC-011 서술이 최초에는 "결함 발견"처럼 읽혀 혼동 소지가 있었음) 발견 후 조치.
- 2차 검증 결과 요약: "이 결과서만 보고 07 통합테스터가 추가 질문 없이 다음 단계로 넘어가도 되는가"를 의심하며 경계 조건 재검토(nav에 없는 경로, 완전 미존재 경로, prefix 충돌 경로, 하위 동적 경로 4종을 추가 발굴해 TC-022~025로 보강). 결함 0건, 커버리지 보강만 수행.
- 검증 로그 파일 경로: `docs/harness/units/verify-log_unit-05-test.md`
