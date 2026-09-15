# UNIT-04 구현 노트 — 규제 대응 공통 컴포넌트 (면책 문구 배너 / 금지표현 가이드라인 / 기준시각 표기 공통 UI)

- 작성 에이전트: 05-unit-developer
- 작성일: 2026-09-15
- 포함 REQ: REQ-006(데이터 기준시각 표기), REQ-007(투자자문 아님 면책 문구 상시 노출), REQ-008(금지표현 가이드라인), REQ-009(불특정 다수 대상, 1:1 맞춤 배제), REQ-010(무료 운영 정책 명문화) — **02-planning.md §9가 "규칙 I 대응, 9단계에서 미반영 시 Critical 결함 취급"으로 명시한 항목 전부**
- 입력: `docs/harness/03-system-design.md`(v4, PASS) §1-3(배포 단위, `/frontend`), §2-1(Next.js+TypeScript 채택 근거), §3-4(`meta.data_freshness` 구조), §4-1(공통 envelope, 사용자 식별 파라미터 금지), §6-4(REQ-007~010 구현 위치 표) / `docs/harness/04-ux-design.md`(v3, PASS) §2-0(공통 레이아웃), §2-5(`/about`), §2-6(금지 표현 대조표), §4(컴포넌트 명세), §5(접근성), §6(반응형)
- 의존성: UNIT-01~03이 이미 구현한 백엔드 공통 응답 스키마(`services/public_api/schemas/envelope.py`)를 그대로 재사용(신규 구현 아님)

---

## 재작업 이력 — 6단계 CONDITIONAL PASS 결함 조치 (DEF-001/DEF-002, 2026-09-15)

`docs/harness/units/unit-04-test.md`(06-unit-tester)가 CONDITIONAL PASS 판정과 함께 발견한 결함 2건(둘 다 Medium)을 코디네이터 지시에 따라 즉시 조치했다. 두 결함 모두 "현재 배포된 화면/카피에는 영향 없음"으로 분류되었으나, 규칙 I 대상(REQ-006/008)의 안전망 자체에 구조적 허점이 있다는 지적이었으므로 미루지 않고 이번에 해소했다.

### DEF-002(Medium, 우선 처리) — 금지어 린트의 줄 단위 스캔 우회 가능성

- **원인**: `frontend/scripts/lint-forbidden-copy.mjs`가 파일을 물리적 줄(line)로 쪼개 각 줄에 대해서만 `includes`/정규식을 검사했다. 금지어가 실제 줄바꿈 문자로 분리되면(예: 템플릿 리터럴/멀티라인 JSX 텍스트 안의 `` `손실보\n전` ``) 어느 줄에도 온전한 금지어가 나타나지 않아 탐지를 통과했다(6단계 TC-027 재현).
- **조치**: 파일을 줄 단위로 쪼개지 않고, 파일 전체 내용에서 공백류 문자(스페이스/탭/개행/CR)를 전부 제거한 "정규화 문자열"을 만들어 그 위에서 검사하도록 구조를 바꿨다(`normalizeWithIndexMap()`). 물리적 줄 경계 자체가 검사 로직에서 사라지므로, 금지어가 몇 줄에 걸쳐 쪼개져 있든 정규화 후에는 항상 하나로 합쳐져 탐지된다. 정규화 과정에서 원본 문자 위치를 그대로 추적하는 `indexMap`을 함께 만들어, 정규화 이후에도 원본 파일 기준의 정확한 줄번호를 리포트에 남기도록 했다(사용자가 위반 위치를 여전히 쉽게 찾을 수 있게).
- **부수 정리**: 검사가 공백 제거 후 이뤄지므로 "매수 신호"(공백 포함)와 "매수신호"(공백 없음)가 이제 동일하게 매칭된다. 기존 `FORBIDDEN_TERMS`에 공백 유무로 중복 등록되어 있던 4개 항목(`"매수 신호"`/`"매도 신호"`)을 제거해 리스트를 정리했다(탐지 범위 축소 아님 — 정규화 로직이 이미 양쪽 표기를 모두 잡는다).
- **재현 검증(직접 실행, 결과 첨부는 §4 로그 참조)**:
  1. `frontend/src/lib/__deftest__/multiline-temp.ts`에 `` export const injected = `손실보\n전`; ``(실제 줄바꿈 포함)를 임시 생성 → `node scripts/lint-forbidden-copy.mjs` 실행 → **exit code 1**, `...multiline-temp.ts:1 — 금지어 "손실보전"` 리포트 확인(수정 전에는 이 시나리오가 "금지표현 검사 통과"로 오탐 없이 넘어갔던 것과 대비). 임시 파일 삭제 후 재실행해 다시 통과함을 확인.
  2. 기존 단일 라인 위반 케이스(TC-020~026과 동일한 5종: "매수신호"/"손실보전"/"수익보장"/"확실한"/"PER 상위 20% 구간")를 각각 독립적으로 주입·복구하며 재실행해 **회귀 없이 전부 여전히 exit 1로 잡힘**을 확인.
  3. `copy.ko.json` 원본 상태로 `npm run lint:copy`, `npm run build`(→ `prebuild` 포함) 재실행 → 전부 정상 통과(오탐 없음).

### DEF-001(Medium) — `formatKstDateTime()`의 잘못된 입력 처리

- **원인**: `frontend/src/lib/formatKst.ts`의 `formatKstDateTime()`이 `new Date(iso)`가 `Invalid Date`가 되는 입력(빈 문자열, 형식이 깨진 문자열)에 대해 `Intl.DateTimeFormat.formatToParts()`를 그대로 호출해 `RangeError: Invalid time value`를 던졌다. `DataFreshnessBadge`가 이 함수를 try/catch 없이 렌더 본문에서 호출하므로, 백엔드가 스키마 드리프트/직렬화 버그 등으로 빈 값이나 깨진 ISO 값을 내려보내면 이 컴포넌트를 쓰는 화면 전체가 렌더링 예외로 죽을 수 있었다(현재는 어디서도 쓰이지 않는 dead code라 당장 REQ-006 위반은 아니라는 점은 6단계 판정과 동일).
- **조치**: `new Date(iso)`로 만든 `Date` 객체의 `getTime()`이 `NaN`이면(= 유효하지 않은 날짜) 예외를 던지지 않고 안전한 폴백 문구 `INVALID_DATE_FALLBACK_TEXT`("기준시각 확인 불가")를 즉시 반환하도록 가드를 추가했다. 정상 입력 경로(유효한 ISO 문자열)는 기존 동작을 그대로 유지한다.
- **재현 검증(직접 실행)**: Node에서 `formatKst.ts`를 직접 import해 `formatKstDateTime('')`, `formatKstDateTime('not-a-date')`, `formatKstDateTime('2026-09-11T15:30:00+09:00')` 세 케이스를 실행 — 앞의 두 경우 예외 없이 `"기준시각 확인 불가"` 반환, 마지막 정상 케이스는 기존과 동일하게 `"2026-09-11 15:30"` 반환함을 확인(정상 경로 회귀 없음).

### 조치 후 전체 게이트 재확인

- `npx tsc --noEmit` — 통과(오류 없음).
- `npm run lint`(ESLint) — 0 error / 0 warning.
- `npm run build`(`prebuild` 금지어 린트 포함) — 통과, 라우트 3개 정상 생성.
- 백엔드 회귀: `python -m ruff check .` 전부 통과, `python -m pytest tests/unit -q` — 79 passed(신규 실패 없음, 이번 조치는 프론트엔드 전용이라 백엔드는 원래 영향 없음을 재확인한 것).

---

## 0. 이 유닛의 성격 — 이번에 처음으로 프론트엔드가 생겼다

UNIT-01~03까지는 백엔드(Python/FastAPI)만 존재했다. 이 유닛에서 03-system-design.md가 확정한 프론트엔드 스택(Next.js 16 + React 19 + TypeScript, `/frontend`)을 **최초로 스캐폴딩**했다. 범위는 코디네이터 지시대로 "공통 셸/배너/뱃지/카피 인프라"까지로 한정했다 — REQ-001~004(종목검색/가공지표/스크리닝/시장리포트)의 실제 화면 콘텐츠, 전역 내비게이션(`GlobalNav`)은 만들지 않았다(각각 UNIT-05~08 범위).

---

## 1. 구현 범위

### 1-1. 프론트엔드 스캐폴딩 (`frontend/`)

- Next.js 16.3.5 + React 19.3.0 + TypeScript(strict) + ESLint(`eslint-config-next`, flat config)를 `npm install`로 실제 설치(버전을 임의로 고정하지 않고 그 시점의 npm 레지스트리 최신 안정 버전을 그대로 채택 — 그린필드라 하위호환 제약 없음).
- App Router 사용(`src/app/`), `@/*` → `src/*` path alias.
- 04-ux-design.md §3(디자인 토큰) 중 이번 유닛이 실제로 쓰는 토큰(텍스트/브랜드/경고 색상, 포커스 링, 간격)만 `src/app/globals.css`에 CSS 변수로 반영했다. 화면별 토큰(등락 색상 등)은 해당 화면을 만드는 유닛이 추가한다.

### 1-2. REQ-007 — 면책 문구 상시 노출

- `src/app/layout.tsx`(RootLayout)가 모든 페이지에 강제 적용되는 Next.js App Router의 공통 layout 메커니즘을 그대로 이용(03-system-design.md §6-4가 요구하는 "개별 페이지가 우회 불가" 구조).
- `src/components/DisclaimerBanner.tsx`: sticky(`position: sticky; top: 0`), **닫기(X) 버튼 없음**, 텍스트 말줄임(`text-overflow: ellipsis` 등) 미사용·자동 줄바꿈 허용, 서버 컴포넌트로 구현해 API 응답을 기다리지 않고 최초 렌더에 즉시 나타난다(04-ux-design.md §2-0 "배너가 로딩 스피너로 대체되는 순간이 있으면 안 됨" 원칙).
- 배너 문구는 `src/content/copy.ko.json`의 `disclaimer.banner` 키에서 가져오며, **백엔드 `DISCLAIMER_TEXT`(`services/public_api/schemas/envelope.py`)와 문자 단위로 완전히 동일함을 스크립트로 직접 비교해 확인**했다(§4 검증 로그 참조) — 04-ux-design.md §2-0 "`meta.disclaimer` 값과 `copy.ko.json`의 `disclaimer.banner` 키가 항상 동일해야 한다" 요구를 충족.
- 배너 끝 "자세히 보기" 링크 → `/about`.
- 푸터(`src/components/Footer.tsx`)에 동일 면책 문구 전문 + 데이터 출처 고지 + "원본 시세를 그대로 제공하지 않는다"는 문구를 이중 노출(04-ux-design.md §2-0 항목5).
- `/about`(`src/app/about/page.tsx`): 04-ux-design.md §2-5가 요구한 6개 섹션(서비스 정의/투자자문업 미등록 고지/데이터 지연·기준시각/데이터 가공 원칙/데이터 출처/문의 채널)을 정적 텍스트로 전부 구현(API 호출 없음, 빌드 타임 고정).

### 1-3. REQ-006 — 데이터 기준시각 표기 공통 컴포넌트

- `src/components/DataFreshnessBadge.tsx`: 03-system-design.md §3-4 `meta.data_freshness` 스키마와 1:1 대응하는 `DataFreshness` 타입(`src/lib/types.ts`)을 props로 받는다.
- **프론트엔드는 기준시각/지연 여부를 자체 계산하지 않는다** — §3-4 원칙("계산 로직 이원화로 인한 표기 오류 방지")을 그대로 따라, 서버가 내려준 값(`session_close_at`, `generated_at`, `is_latest_trading_day`, `staleness_note`)을 그대로 포맷해 표시만 한다.
- 표시 형식은 04-ux-design.md §2-1 예시("국내증권시장(KRX) 기준 2026-09-11 15:30 마감 데이터 · 2026-09-12 07:10 갱신")를 그대로 재현. 시각 포맷은 `src/lib/formatKst.ts`가 `Intl.DateTimeFormat`으로 **항상 명시적으로 `Asia/Seoul` 타임존을 지정**해 변환한다(서버 SSR 실행 환경의 로컬 타임존이 KST가 아닐 가능성에 대비 — 백엔드가 이미 KST ISO 8601을 내려주더라도 클라이언트/서버 렌더링 쪽에서 재해석 시 로컬 타임존에 의존하지 않도록 방어).
- `is_latest_trading_day=false`이면 `staleness_note`(서버가 채워준 문구)를 그대로 인라인 경고로 표시한다(프론트엔드가 "N영업일 지연" 문구를 직접 조립하지 않음 — §3-4 "프론트엔드가 판단하지 않음" 원칙).
- 아직 실제 화면(홈/종목상세/시장요약, UNIT-06~08)에 연결되지 않았으므로, 이번 유닛에서는 컴포넌트 단위로만 검증했다(§5 참조). 백엔드의 `data_freshness`/`disclaimer` 공통 응답 스키마 자체는 UNIT-01~03에서 이미 구현되어 있어(예: `GET /calendar/last-trading-day`가 이미 실제 값을 채워 반환) 이번 유닛에서 새로 만들지 않았다.

### 1-4. REQ-008 — 금지표현 가이드라인의 실제 강제 메커니즘

- 중앙 카피 리소스 `src/content/copy.ko.json` 신설(면책 배너/푸터/`/about`/기준시각 배지 문구 전부 이 파일에서만 가져온다 — 03-system-design.md §6-4 "프론트엔드 전 UI 문자열을 중앙 카피 리소스 파일로 일원화").
- `frontend/scripts/lint-forbidden-copy.mjs`: 04-ux-design.md §2-6 금지 표현 대조표의 왼쪽 컬럼(추천/매수신호/매도신호/수익보장/손실보전/원금보장/지금 사세요/매수 타이밍/베스트 종목/확실한/안전한 조건 + "PER/PBR 상위 N% 구간" 임의 구간화 패턴)을 그대로 옮긴 블랙리스트로, `frontend/src/` 하위 `.ts`/`.tsx`/`.json` 파일 전체를 스캔한다.
- `package.json`의 `prebuild` 스크립트로 연결해, **`npm run build`(실제 CI가 프로덕션 빌드 시 실행할 명령)가 이 린트를 반드시 통과해야만 진행**되도록 강제했다(03-system-design.md §6-4 "위반 시 빌드 실패"의 실제 구현).
- **동작 확인(설계 문서화에 그치지 않음)**: `copy.ko.json`에 `"이것은 추천 종목입니다"`를 임시로 주입한 뒤 `node scripts/lint-forbidden-copy.mjs`를 실행해 **exit code 1로 실제 실패**하는 것을 확인했고, 원복 후 다시 실행해 통과하는 것도 확인했다(§4 로그 참조). `npm run build` 전체를 통해서도 동일하게 재현 가능(`prebuild` 훅이 먼저 실행되므로).

### 1-5. REQ-009 — 불특정 다수 대상, 1:1 맞춤 배제 (코드 구현 아님, 재확인)

- 코디네이터 지시에 따라 "사용자 식별자 파라미터가 API 어디에도 없다"를 실제 API 스펙에서 재확인했다. 현재 구현된 엔드포인트는 3개뿐이다: `GET /api/v1/health`, `GET /api/v1/stocks`, `GET /api/v1/calendar/last-trading-day`.
- `services/`, `shared/` 전체를 `user_id`/`holding_price`/`quantity`/세션·쿠키·인증 헤더 관련 키워드로 검색한 결과, 매칭된 `session`은 전부 SQLAlchemy DB 세션(`sqlalchemy.orm.Session`)이며 HTTP 사용자 세션/인증과 무관함을 확인했다. 인증 미들웨어, 쿠키 설정, `Authorization` 헤더 파싱 코드는 어디에도 없다.
- 결론: 03-system-design.md §4-1/§6-1이 명시한 "사용자 식별 파라미터 금지" 원칙이 현재 구현 상태와 일치한다. **이 REQ에 대해 UNIT-04는 별도 코드를 추가하지 않았다** — "만들지 않는 것 자체가 구현"이라는 설계서의 서술을 그대로 재확인만 한 것이다.
- 주의: 이 확인은 "현재 시점" 스냅샷이다. REQ-002/003/004를 구현하는 UNIT-06~08이 새 엔드포인트를 추가하면, 그 시점에 동일한 재확인이 다시 필요하다(회귀 위험 — traceability.md 비고에 명시).

### 1-6. REQ-010 — 무료 운영 정책 (코드 구현 아님, 재확인)

- `frontend/package.json`, `requirements.txt`에 결제/광고 SDK 관련 의존성이 전혀 없음을 확인했다(부재 자체가 구현, 03-system-design.md §6-4).
- 유료화/광고 도입 시 규칙 A 재질문 + `decisions.md` 기록 + 법률 재검토를 선행 조건으로 하는 절차는 `02-planning.md` §8-A7, `03-system-design.md` §6-4에 이미 명문화되어 있어 이번 유닛에서 추가로 작성할 문서가 없다.

---

## 2. 설계서 대비 편차 (사유 포함)

1. **`DataFreshnessBadge`의 `session_close_at`이 `null`인 경우의 표시 방식은 설계서에 명시가 없다.** 03-system-design.md §3-4는 `session_close_at`을 필수처럼 예시로 보여주지만 백엔드 스키마(`envelope.py`)는 이 필드를 `Optional`로 선언해 두었다. 컴포넌트는 방어적으로 `null`이면 `trade_date`(날짜만)로 대체 표시하도록 구현했다 — 실제 값이 없는데 시각을 임의로 지어내지 않기 위함이다. 이 케이스가 실제로 발생하는지(예: 아직 세션 정보가 없는 초기 배치)는 UNIT-06~08이 실 데이터로 연결할 때 재검증이 필요하다.
2. **금지어 린트의 스캔 범위를 `frontend/src/` 하위 `.ts`/`.tsx`/`.json`으로 한정했다.** 03-system-design.md §6-4는 "프론트엔드 전 UI 문자열"이라고만 서술해 정확한 스캔 경로를 지정하지 않았다. 향후 유닛이 카피를 다른 위치(예: 별도 마크다운 콘텐츠 파일)에 추가하면 이 스크립트의 `SCAN_ROOT`/`SCAN_EXTENSIONS`를 갱신해야 한다 — 이 공백을 노트에 명시해 후속 유닛이 놓치지 않게 했다.
3. **헤더(`Header.tsx`)를 워드마크만 있는 최소 형태로 구현했다.** 04-ux-design.md §2-0/§4는 헤더에 "전역 내비게이션(홈/조건 스크리닝/종목 검색)"도 포함하도록 명세하지만, 코디네이터 지시에 따라 UNIT-05(반응형 UI 셸/공통 네비게이션)와의 역할 중복을 피하기 위해 `GlobalNav` 컴포넌트는 만들지 않았다. UNIT-05가 이 헤더를 확장해 실제 내비게이션을 추가해야 한다.
4. **홈(`/`) 화면을 자리표시자로만 구현했다.** REQ-004(시장 동향 리포트)의 실제 콘텐츠는 UNIT-08 범위이므로, 이번 유닛은 레이아웃/배너 동작 검증용 최소 placeholder만 두었다.

이상 4건은 전부 "범위를 벗어난 임의 구현을 피하기 위한 의도적 제한"이거나 "설계서 공백을 상상으로 채우지 않고 방어적으로 처리한 것"이며, REQ-006~010의 핵심 요구사항(면책 문구 상시 노출, 기준시각 표기, 금지어 CI 강제, 사용자 식별 파라미터 부재, 결제/광고 SDK 부재)을 훼손하지 않는다.

---

## 3. 수동 확인이 필요한 부분 (6단계 테스터에게)

1. **실제 브라우저 렌더링에서의 시각적 검증**: 이번 유닛은 `npm run build`/`npm run dev` + `curl`로 서버사이드 렌더링 결과(HTML)만 확인했다. 실제 브라우저에서 (a) 배너가 페이지 스크롤과 무관하게 상단에 고정되는지, (b) 좁은 화면/200% 확대 시 배너 텍스트가 잘리지 않고 2줄 이상으로 자동 줄바꿈되는지, (c) 포커스 링이 스킵 링크/배너 링크에서 시각적으로 보이는지는 실제 브라우저(또는 Lighthouse/axe 등 접근성 도구)로 재검증이 필요하다.
2. **`DataFreshnessBadge`의 실사용 검증**: 현재는 컴포넌트 자체 렌더링만 확인했고, 실제 API 응답(`meta.data_freshness`)을 받아 화면에 연결하는 코드는 아직 없다(UNIT-06~08이 이 컴포넌트를 가져다 쓸 때 연결). 6단계는 다양한 `DataFreshness` prop 조합(정상/지연/`session_close_at=null`)으로 컴포넌트 단위 렌더링 테스트를 수행해야 한다.
3. **CI 파이프라인 실제 연결**: `frontend/scripts/lint-forbidden-copy.mjs`가 `npm run build`의 `prebuild`로 로컬에서는 실제로 동작함을 확인했으나, `automation/github-actions-harness.yml`에는 아직 프론트엔드 빌드 잡이 없다(이 저장소의 CI는 현재 하네스 자체(6~9단계 에이전트 호출)만 실행한다). 실제 GitHub Actions 등 CI에 `cd frontend && npm ci && npm run build`를 추가하는 작업은 이번 유닛 범위에 없었다 — 10단계(배포테스트) 또는 별도 인프라 작업으로 이관 필요.
4. **Next.js가 자동 생성한 `frontend/AGENTS.md`/`frontend/CLAUDE.md`**: `next dev`/`next build` 실행 시 Next.js 16이 자동으로 생성하는 파일이다(`node_modules/next/dist/server/lib/generate-agent-files.js`가 생성 주체이며, 파일 자체에 "committing it with your work keeps the tree clean"라는 안내가 있어 커밋 대상으로 남겼다). 악의적이거나 의도치 않은 파일이 아니라 Next.js 16의 정식 기능임을 확인했다.

---

## 4. 로컬 동작 확인 로그 (요약)

- `cd frontend && npm run build` → `prebuild`(금지어 린트) 통과 후 `next build` 성공, 라우트 3개(`/`, `/_not-found`, `/about`) 정적 생성 확인.
- `npm run lint`(ESLint flat config, `eslint-config-next`) → 0 error, 0 warning.
- `npx tsc --noEmit` → 오류 없음.
- **금지어 린트 실제 실패 재현**: `copy.ko.json`에 `"이것은 추천 종목입니다"`를 임시 주입 → `node scripts/lint-forbidden-copy.mjs` 실행 결과 `금지어 "추천"` 위반 1건 보고 + `exit code 1` 확인 → 원복 → 재실행 시 `금지표현 검사 통과` 확인.
- `python -m ruff check .`(백엔드, 이번 유닛에서 변경 없음) → 전부 통과(회귀 없음 확인).
- 배너/푸터/`/about`/스킵 링크의 실제 렌더링 HTML을 `npm run dev` + `curl`로 직접 확인: 배너 텍스트가 백엔드 `DISCLAIMER_TEXT`와 완전히 동일함(Node 스크립트로 문자열 비교, MATCH), 페이지 어디에도 "닫기"/"close" 마커가 없음, `/about`의 6개 섹션(`<h2>`) 전부 렌더됨을 확인.

---

## 5. 게이트 1 — 정적 분석/린트 결과

- **프론트엔드**: `eslint.config.mjs`(ESLint 9, flat config, `eslint-config-next`) 존재 → `npm run lint` 실행, 0 error/0 warning으로 통과. TypeScript strict 모드(`tsconfig.json`) → `npx tsc --noEmit` 통과.
- **백엔드(변경 없음, 회귀 확인 목적)**: `pyproject.toml`의 `ruff` 설정 존재 → `python -m ruff check .` 실행, 전부 통과.
- 이번 유닛이 신설한 금지어 검사 스크립트(`lint-forbidden-copy.mjs`) 자체도 하나의 정적 검사 게이트이며, `npm run build`에 자동 연결되어 있어 별도 수동 실행 없이도 항상 적용된다.
- 설정이 없어서 건너뛴 검사는 없다.

---

## 6. 게이트 2 — 자체 코드 리뷰 체크리스트

- [x] **설계서/디자인서 명세와 실제 구현이 일치하는가** — 03-system-design.md §6-4 표의 REQ-007~010 구현 위치/강제 방식과 1:1로 대응시켜 구현했다(§1 참조). 04-ux-design.md §2-0/§2-5/§2-6의 문구·구조·상태(닫기 없음, sticky, 말줄임 금지)를 그대로 반영했다.
- [x] **에러 처리가 누락된 경로가 없는가** — 이번 유닛의 컴포넌트는 전부 정적 콘텐츠(배너/푸터/`/about`) 또는 순수 표시용(`DataFreshnessBadge`, props 검증은 TypeScript 타입으로 강제)이라 별도 비동기 에러 경로가 없다. `DataFreshnessBadge`는 `freshness=null`(값 없음) 상태를 명시적으로 분기 처리해 예외를 삼키지 않는다. 린트 스크립트는 위반 발견 시 `console.error` + `process.exit(1)`로 명시적으로 실패하며 조용히 넘어가지 않는다.
- [x] **입력값 검증이 시스템 경계(사용자 입력, 외부 API 응답)에서 이루어지는가** — `DataFreshnessBadge`의 props 타입(`DataFreshness`)이 백엔드 스키마와 1:1 대응하도록 명시적으로 선언되어 있고, TypeScript strict 모드가 타입 불일치를 컴파일 타임에 차단한다. 이번 유닛은 사용자 입력을 직접 받는 폼이 없다(스크리닝 조건 폼은 UNIT-07 범위).
- [x] **하드코딩된 시크릿/자격증명이 없는가** — 이번 유닛은 API 키/토큰/DB 자격증명을 다루지 않는다(`.env` 관련 파일 추가 없음). 확인 결과 없음.
- [x] **범위를 벗어난 변경(곁다리 리팩터링 등)이 섞여 있지 않은가** — 백엔드 코드는 전혀 수정하지 않았다(REQ-001~004 UI, `GlobalNav`, 화면별 데이터 연결은 만들지 않음). `.gitignore`에 `frontend/node_modules`, `frontend/.next` 등 프론트엔드 빌드 산출물 제외 규칙을 추가한 것은 신규 프론트엔드 스캐폴딩에 필연적으로 수반되는 변경이라 범위 외 변경으로 보지 않았다.

---

## 7. 6단계 테스터를 위한 인수 조건 (Acceptance Criteria)

**AC-1 (REQ-007, 면책 배너 상시성)**
- `frontend/`에서 `npm run dev` 실행 후 `/`, `/about` 각 페이지의 최초 렌더 HTML에 `class="disclaimer-banner"` 요소가 존재하고, 그 안에 정확히 다음 문장이 포함되어야 한다: "이 서비스는 투자자문업 등록 사업자가 아니며, 제공되는 정보는 투자 조언이 아닙니다. 투자 판단과 책임은 이용자 본인에게 있습니다."
- 위 HTML 어디에도 배너를 닫는 버튼(예: `aria-label`에 "닫기"/"close" 포함, 또는 `button` 안에 X 아이콘)이 없어야 한다.
- 배너 텍스트에 `text-overflow: ellipsis` 또는 `...`로 잘린 표시가 없어야 한다(`globals.css`의 `.disclaimer-banner__text`에 `white-space: normal`, `overflow-wrap: break-word`만 있고 `text-overflow`/`nowrap` 없음을 코드로 확인 가능).
- `frontend/src/content/copy.ko.json`의 `disclaimer.banner` 값과 `services/public_api/schemas/envelope.py`의 `DISCLAIMER_TEXT` 값이 문자 단위로 동일해야 한다.
- 푸터에도 동일 면책 문구 전문이 존재해야 한다(이중 노출).
- `/about` 페이지에 6개 섹션 제목(`<h2>`)이 모두 존재해야 한다: "이 서비스는 무엇인가요", "투자자문업 등록 여부", "데이터 지연 및 기준시각", "데이터 가공 원칙", "데이터 출처", "문의".

**AC-2 (REQ-006, 데이터 기준시각 표기 컴포넌트)**
- `DataFreshnessBadge`에 `freshness={ market: "KRX", trade_date: "2026-09-11", session_close_at: "2026-09-11T15:30:00+09:00", generated_at: "2026-09-12T07:10:00+09:00", is_latest_trading_day: true, expected_last_trading_day: "2026-09-11", staleness_note: null }`를 넘기면, 렌더 결과 텍스트에 "국내증권시장(KRX) 기준 2026-09-11 15:30 마감 데이터 · 2026-09-12 07:10 갱신"이 포함되어야 한다(공백/구두점 포함 정확히 일치).
- `is_latest_trading_day: false, staleness_note: "예상보다 1영업일 지연된 데이터입니다"`로 렌더하면, 해당 문구가 인라인 경고로 표시되어야 하며 색상에만 의존하지 않고 텍스트로 노출되어야 한다(스크린리더가 읽을 수 있어야 함).
- `freshness={null}`로 렌더하면 예외 없이 대체 문구("데이터 기준시각을 확인하는 중입니다")가 표시되어야 한다(크래시 없음).
- `session_close_at: null`인 경우 컴포넌트가 예외를 던지지 않고 `trade_date`로 대체 표시해야 한다.
- 컴포넌트는 어떤 형태로도 시각을 자체 계산하지 않아야 한다(코드 리뷰: `formatKstDateTime` 호출 시 항상 서버가 내려준 ISO 문자열을 그대로 입력으로 사용하는지 확인).
- **(DEF-001 재발 방지, 신규)** `formatKstDateTime('')`, `formatKstDateTime('not-a-date')`처럼 빈 문자열/형식이 깨진 ISO 문자열을 넘겨도 예외(`RangeError` 등)를 던지지 않고 `INVALID_DATE_FALLBACK_TEXT`("기준시각 확인 불가")를 반환해야 한다. 정상 ISO 문자열 입력 시의 기존 출력 형식은 변하지 않아야 한다(회귀 없음).

**AC-3 (REQ-008, 금지표현 가이드라인 CI 강제)**
- `cd frontend && npm run lint:copy`(또는 `npm run build`)를 현재 코드베이스에서 실행하면 종료 코드 0, "금지표현 검사 통과" 메시지가 출력되어야 한다.
- `frontend/src/content/copy.ko.json`의 임의의 문자열 값에 "추천", "매수신호", "손실보전", "수익보장", "원금보장" 중 하나라도 삽입한 뒤 같은 명령을 실행하면 **종료 코드 1**로 실패하고, 실패한 파일 경로/줄번호/금지어가 콘솔에 출력되어야 한다.
- `npm run build`를 실행했을 때 `prebuild` 단계가 먼저 실행되어, 금지어가 있으면 `next build` 자체가 시작되지 않아야 한다(빌드 완전 중단).
- `04-ux-design.md` §2-6 대조표의 좌측 컬럼 항목이 `frontend/scripts/lint-forbidden-copy.mjs`의 `FORBIDDEN_TERMS`/`FORBIDDEN_PATTERNS`에 전부 반영되어 있는지 대조 확인.
- **(DEF-002 재발 방지, 신규)** `frontend/src/` 하위 임의의 `.ts` 파일에 금지어가 실제 줄바꿈으로 쪼개진 멀티라인 문자열(예: `` `손실보\n전` ``)을 넣으면, 여전히 **종료 코드 1**로 탐지되어야 한다(물리적 줄 경계로 우회 불가 — `normalizeWithIndexMap()`이 공백류 문자를 전부 제거한 뒤 비교하는지 코드 리뷰로 확인).

**AC-4 (REQ-009, 사용자 식별 파라미터 부재)**
- `services/public_api/api/*.py`의 모든 `@router.get(...)` 핸들러의 `Query(...)` 파라미터 목록에 `user_id`, `holding_price`, `quantity`, `account`, `token` 등 사용자 식별/개인화 관련 파라미터가 없어야 한다(현재 3개 엔드포인트: `/health`, `/stocks`, `/calendar/last-trading-day`).
- 요청 헤더/쿠키를 파싱해 응답을 분기하는 코드가 없어야 한다(동일 요청 파라미터면 항상 동일 응답).

**AC-5 (REQ-010, 결제/광고 SDK 부재)**
- `frontend/package.json`의 `dependencies`/`devDependencies`, `requirements.txt`, `requirements-dev.txt`에 결제(예: `stripe`, `iamport` 등)·광고(예: `google-adsense` 등) 관련 패키지가 없어야 한다.

---

## 8. 다음 단계

- 6단계(단위테스트)를 이 노트에 대해 즉시 호출해야 한다.
- 이 유닛 완료 후에도 UNIT-05(반응형 UI 셸/`GlobalNav`)가 이 레이아웃의 `Header`를 확장해야 하며, UNIT-06~08은 `DataFreshnessBadge`를 실제 데이터에 연결해야 한다 — 두 경우 모두 REQ-006/007이 여전히 지켜지는지 코드 리뷰에서 재확인이 필요하다(02-planning.md §9 "UNIT-06~08은 UNIT-04를 포함한 뒤에만 완료로 인정" 원칙).
