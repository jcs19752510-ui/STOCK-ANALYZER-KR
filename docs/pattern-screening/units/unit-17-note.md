# UNIT-17 구현 노트 및 내부 테스트 결과서 — 프론트엔드 `/screener/pattern` (REQ-033~035)

- 작성: 2026-10-02 15:2x KST · 관련: 03 디자인서 전체, 05 테스트계획 §10(TC-F01~F26)·§11(TC-X01~X06)·§12(TC-R01~R06)
- **결론: 구현 완료. 정적 검증(tsc·ESLint·금지어 린트·`next build`)과 실제 브라우저 검증(5개 폭, 상태 9종, 접근성)을 통과했다. 검증 중 결함 3건을 발견해 모두 고쳤다. 한계(§6)는 숨기지 않고 적었다.**

## 1. 구현 요약

| 구분 | 파일 | 내용 |
|---|---|---|
| 신규 라우트 | `app/screener/pattern/page.tsx` | 서버 셸: 메타데이터(제목은 `copy.pattern.label`에서 조합)·기능 스위치(`notFound()`) |
| 신규 컴포넌트 | `PatternScreenerClient`, `PatternFilterPanel`, `PatternResultsTable`, `PatternResultsList`, `ConditionStatusBadge`, `PatternDefinitionPanel`, `ReadinessNote`, `PatternNotice`, `ScreeningModeNav` | 설계서 03 §4 목록 그대로 |
| 신규 lib | `patternApi.ts`, `patternFormat.ts`, `patternValidation.ts`, `patternDefaults.ts`, `patternFeature.ts` | API 호출·표시 문구·검증(순수 함수)·기본값·기능 스위치 |
| 수정(추가) | `types.ts`, `copy.ko.json`(`pattern.*` 31개 키), `errorMapping.ts`(`PATTERN_DATA_NOT_READY`), `EmptyState.tsx`(변형 2종), `app/screener/page.tsx`(전환 링크 1줄), `globals.css`(패턴 전용 블록 추가) | 기존 동작·기존 화면 불변(§4-F05) |

- **명칭 단일 출처**: "급등 전 압축주"는 소스에서 `copy.ko.json`의 `pattern.label` **한 곳에만** 있다(제목·전환 링크·`h1`·메타데이터가 모두 이 키에서 나온다). 법률 검토(Q4) 결과에 따라 한 줄로 바꿀 수 있다.
- **판정 로직 없음**: 화면은 서버가 준 `met`/`reason`/`ma60_stage`를 그대로 표시한다. 임계값을 하드코딩하지 않으며 조건 정의 패널은 API `definition`을 그대로 렌더한다(서버 설정이 바뀌면 문구가 따라간다 — 실측 §4-F12).
- 접근성·규제 장치: 상시 비예측 고지(닫기 없음), 상태는 글리프+텍스트(색에만 의존 안 함), 산정 불가 사유는 배지 아래 항상 표시, 점수·순위·서열 표현 없음, 가격·거래량 원값 필드 없음, `<table>`+`caption`+`scope`, 바텀시트 포커스 트랩.
- 새 디자인 토큰·새 의존성 없음(`package.json`·`package-lock.json`·`requirements*.txt` 변경 0줄). 기존 컴포넌트(`MarketFilterControl`·`ConditionField`·`Pagination`·`DataFreshnessBadge`·`LoadingSkeleton`·`ErrorState`·`useFocusTrap`·`useIsDesktopViewport`)와 CSS 클래스(`inline-notice--info`, `condition-filter-panel*`)를 재사용했다.

## 2. 문서와 달라진 점·구현 중 판단 (편차 기록)

| # | 내용 | 영향 |
|---|---|---|
| 1 | **결과 표를 `role="region"`+`tabIndex=0`인 스크롤 영역으로 감쌌다**(설계서에 없음). 사이드 패널(280px)과 함께 있으면 1024px에서 폭이 좁아, 넘치더라도 페이지 가로 스크롤이 아니라 표 안에서만 스크롤되도록 한 안전장치. 실측상 1024·1280px에서는 넘치지 않는다 | 키보드로 스크롤 영역 접근 가능 |
| 2 | 조건 정의 패널에 "계산 기준: 종가·거래량 일봉 기준" 줄을 추가 | 설계서 §3-3의 "계산 기준" 항목을 별도 줄로 구현 |
| 3 | **R04("급등" 사용처) 허용 목록 확정**: `pattern.label`, c9 열 제목 "급등 이력", c9 근거 문장 "급등·거래량 급증 이력", 그리고 `proxyFootnote`("거래량·급등 이력은 …대리 지표입니다"). 마지막은 설계서 §7이 정한 푸트노트 원문 그대로인데, 같은 절의 "푸트노트에는 '급등'을 쓰지 않는다"와 문구상 모순이다 | 원문(문서)을 따랐다. 문구를 바꾸려면 사용자 결정 — 법률 검토(Q4) 때 함께 검토 권장 |
| 4 | 백엔드가 `FEATURE_DISABLED`(404)를 반환하는데 프런트 스위치는 켜진 불일치 상황은 기존 기본 매핑(일반 오류 문구)으로 표시된다 | 정상 배포에서는 두 스위치를 함께 둔다(설계서 §9). 별도 문구는 추가하지 않음 |
| 5 | 프런트 단위 테스트 프레임워크가 이 저장소에 없고(새 의존성 금지) 검증은 tsc·eslint·린트·빌드·실제 브라우저로 한다(05 §10 방침). 순수 함수(`patternFormat`/`patternValidation`)는 브라우저에서 간접 검증 | `node:test` 같은 별도 러너는 추가하지 않음 |
| 6 | 필수 조건 체크박스 오류는 첫 체크박스(`pattern-required-c1`)로 포커스를 옮기고 모든 체크박스에 `aria-invalid`·`aria-describedby`를 건다(ARIA는 `fieldset`의 `aria-invalid`를 지원하지 않음) | 접근성 |

문서의 임계값·계산 정의·카피 원문은 바꾸지 않았다(편차 #2·#3은 추가/원문 유지).

## 3. 검증 방법 (재현 가능)

- **정적**: `tsc --noEmit`, `eslint .`, `node scripts/lint-forbidden-copy.mjs`, `next build`. 개발 서버의 `.next`를 건드리지 않도록 **임시 복사본(`.harness-tmp/fe-build`)에서 빌드**했다.
- **브라우저(실제 Chrome, Browser 2)**: 개발 DB·개발 서버(4000/4001)를 건드리지 않도록 **임시 DB(픽스처 T00001~T00010)와 별도 백엔드(4601)·프런트(4600) 스택**을 만들어 사용했다. 상태 재현은 임시 스택에서 데이터·백엔드를 바꿔 실제로 일으켰다(준비 중: 모든 상태를 `INSUFFICIENT_HISTORY`로, 오류: 백엔드 중지, 캘린더 미확인: 캘린더 삭제, 429: 분당 한도 2로 재기동). 폭은 같은 출처 `iframe`으로 정확한 뷰포트(320·375·768·1024·1280·640·480px)를 만들어 측정했다.
- 검증 후 **임시 스택·임시 DB·임시 빌드 폴더를 모두 삭제**했다(잔여 임시 DB 0개, `.harness-tmp` 비어 있음).

## 4. 테스트 결과 (실제 실행 출력)

### 4-1. 요약

| 구분 | 결과 |
|---|---|
| `tsc --noEmit` | 오류 0 |
| `eslint .` | 오류·경고 0 |
| `npm run lint:copy` | 통과(검사 파일 62개) |
| `next build`(격리 빌드) | 통과, `/screener/pattern` 정적 경로 생성 |
| 기존 회귀 | `pytest tests/unit` 520 passed, `tests/integration` 125 passed |
| 증거 | 데스크톱 스크린샷 `units/evidence/unit-17-desktop-table-1496px.jpg`(픽스처 데이터, 표 화면) |
| 정리 | 임시 DB 0개, 4600/4601 종료, 개발 서버 4000·4001 유지 |

### 4-2. TC별 결과 (05 §10~§12)

| TC | 시나리오 | 결과 | 근거 |
|---|---|---|---|
| F01 | tsc·eslint·build | PASS | 위 표 |
| F02 | 린트 `pattern.*` 포함 통과 | PASS | 62개 파일, 위반 0 |
| F03 | **금지어 음성 검사** | PASS | `pattern.scopeFootnote`에 "추천" 주입 → 종료코드 **1**, 원복 후 0(diff는 신규 70줄뿐) |
| F04 | 전환 링크 2개·`aria-current` | PASS | `/screener`: 현재=직접 조건 설정, `/screener/pattern`: 현재=패턴. `<nav aria-label="스크리닝 방식">` |
| F05 | `/screener` 불변 | PASS | 전환 링크 외 동일: 기본값(시가총액 500·거래량 100000)·화면 구성 유지 |
| F06 | 진입 시 자동 1회 조회 | PASS | 로드 직후 결과 표시(기본값: 시장 전체·500억·100,000주·6개 조건) |
| F07 | 로딩 | PASS | 스켈레톤 5개·높이 88px 고정, `aria-busy="true"`, 버튼 비활성+스피너, 필터 입력 조작 가능, 이전 결과 숨김 |
| F08 | ≥1024px 표 | PASS | `<table>`, 열 7개 `scope="col"`, 종목 셀 `scope="row"`, 캡션(sr-only) "패턴 조건 충족 여부" |
| F09 | <1024px 카드·**가로 스크롤 없음** | PASS | 320·375·480·640·768px 모두 `scrollWidth ≤ clientWidth` |
| F10 | 글리프+텍스트 | PASS | 모든 셀에 `✓/✕/–`(aria-hidden)와 충족/미충족/산정 불가 텍스트 동시 표시 |
| F11 | 산정 불가 사유 상시 표시 | PASS | 평탄 종목: 이평선 수렴·거래량 셀에 "산정 불가 + 사유: 지표 산출 불가"(사유 줄 항상 표시, 툴팁 아님) |
| F12 | 정의 패널이 서버 설정을 따름 | PASS | 서버를 `PATTERN_RANGE_MAX_PCT=35`·`PATTERN_CROSS_EARLY_MAX_DAYS=6`으로 재기동 → 패널이 "평균의 35% 이하"·"최근 6거래일"로 변경(40%/10거래일 사라짐), **프런트 재빌드 없음** |
| F13 | 필수 조건 전부 해제 | PASS | 인라인 오류 "필수로 적용할 조건을 하나 이상 선택해 주세요."(`role=alert`), 첫 체크박스로 포커스, **요청 0건** |
| F14 | 결과 0건 | PASS | 지정 문구, 대안 제시·추천 문구 없음, 고지·준비 현황·정의 패널 유지 |
| F15 | `PATTERN_DATA_NOT_READY` | PASS | `empty-state`(에러 스타일·`role=alert` 아님), 문구 "…시세 기간이 아직 부족합니다…" |
| F16 | `ready_ratio<1` | PASS | "시세 기간이 충분한 8/10종목을 평가했습니다. 나머지는 '산정 불가'로 표시됩니다." |
| F17 | 오류 3종 | PASS | 네트워크(백엔드 중지)·캘린더 미확인(424)·요청 과다(429) 각각 올바른 문구+다시 시도 버튼, 백엔드 복구 후 "다시 시도"로 정상 복구 확인 |
| F18 | 기능 스위치 off | PASS | `NEXT_PUBLIC_PATTERN_SCREEN_ENABLED=false` 빌드: `/screener/pattern` → **404**, `/screener` HTML에 패턴 링크 **0개** |
| F19 | **명칭 단일 출처** | PASS | 소스 검색 결과 `copy.ko.json` 1곳(CSS 주석에 있던 한 건은 제거). 키만 바꿔 빌드 → 제목·`h1`·두 화면의 전환 링크가 모두 변경, 옛 명칭 0건 |
| F20 | 키보드 | PASS(부분) | 바텀시트 Esc 닫기·포커스 복귀 확인. 탭 순서는 DOM 순서(전환 링크→제목→고지→트리거→필터→결과→페이지네이션→정의)로 구성 |
| F21 | 바텀시트 포커스 트랩 | PASS | 열리면 첫 요소("필터 닫기")로 이동, Shift+Tab→마지막("조건 적용")·Tab→첫 요소로 순환, `role=dialog`·`aria-modal`·`aria-label` |
| F22 | 접근성 트리 | PASS(부분) | 속성 수준 확인(배지 텍스트, `caption`, `role=region`+`aria-label`, 결과 영역 `aria-live="polite"`). **실제 스크린리더 음성 출력은 미확인(§6)** |
| F23 | 200% 확대 | PASS | 확대 200% 상당 폭(640·480px)에서 가로 스크롤 없음 |
| F24 | `prefers-reduced-motion` | PASS(정적) | 스켈레톤 애니메이션은 `no-preference`일 때만, 스피너·시트 전환은 `reduce`에서 제거(CSS 규칙 확인). 브라우저 설정 에뮬레이션은 하지 않음 |
| F25 | 면책 배너 유지 | PASS | `DisclaimerBanner` 존재·닫기 버튼 없음 |
| F26 | 내비 활성 | PASS | `/screener/pattern`: "조건 스크리닝" `aria-current=page`, `/screenerxyz`(404): 비활성 |
| X01 | 명도 대비(렌더된 색 계산) | PASS | 고지 6.87 · 근거 문장 7.56 · 충족 배지 6.09 · 미충족 7.56 · **산정 불가 5.02**(사유 줄 12px도 5.02) · 준비 안내 6.87 · 정의 요약 17.74 · 전환 링크 6.09/7.56 · 적용 버튼 6.70 · 필수 조건 라벨 17.74 — 전부 4.5:1 이상 |
| X02 | 터치 타깃 ≥44px | PASS | 패턴 화면 영역의 모든 버튼·링크·체크박스 라벨이 5개 폭 전부에서 44px 이상(수정 후). 전역 배너·헤더·푸터 링크는 기존 유닛 소관이라 범위 밖(§6) |
| X03 | 헤딩 구조 | PASS | `h1`("급등 전 압축주") → `h2`(결과 제목) |
| X04 | 입력 라벨 | PASS | 라벨 없는 `input` 0개 |
| X05 | 오류 연결 | PASS | `aria-invalid`·`aria-describedby="pattern-required-error"`, `role=alert` |
| X06 | `lang` | PASS | `ko` |
| R01 | 금지어 린트 | PASS | F02와 동일 |
| R02 | **비예측 고지 상시 노출** | PASS | 로딩·정상·0건·준비 중·네트워크/캘린더/429 오류·검증 오류 **모든 상태에서 DOM에 존재**, 닫기 컨트롤 없음 |
| R03 | 서열 표현 부재 | PASS | 패턴 관련 소스·카피에서 TOP/BEST/1위/유력/추천/점수/순위(표시 문구) 0건 |
| R04 | "급등" 사용처 | PASS | 허용 목록 4곳 외 0건(편차 #3) |
| R05 | REQ-022 범위 | UNIT-18 | 문서 갱신 항목 |
| R06 | 정의 패널 고지 2줄 | PASS | 대리 지표·수급/실적 미반영 안내 존재 |
| S10 | 프런트 정적 점검 | PASS | `dangerouslySetInnerHTML` 0건, `eval`/`innerHTML` 0건, 키·시크릿 문자열 0건(검색에 걸린 3건은 기존 `retryToken` 변수) |

### 4-3. 검증 중 발견·수정한 결함 (실제 브라우저 측정으로 발견)

| # | 결함 | 심각도 | 원인 / 조치 | 재검증 |
|---|---|---|---|---|
| 1 | **1024·1280px에서 표가 페이지 가로 스크롤을 만듦**(설계가 금지한 동작) | High | 그리드 `1fr` 열이 표의 최소 너비 때문에 줄어들지 못함 → `minmax(0,1fr)`, 셀 줄바꿈·좁은 패딩, 표 스크롤 컨테이너 | 1024/1280px `pageHScroll=false` |
| 2 | 패턴 화면의 터치 타깃이 44px 미만("조건 설정" 37px, 종목 링크 24/40px) | Medium | 이 화면 범위에서 `min-height:44px`·`inline-flex` 적용 | 5개 폭 모두 44px 미만 0개 |
| 3 | 표의 종목 열이 73px로 좁아 종목명이 글자 단위로 쪼개짐 | Low | 종목 열 최소 폭 120px·`word-break: keep-all` | 종목명 한 줄(링크 높이 44px) |

(수정 후 위 항목과 연관된 TC를 모두 다시 실행해 PASS를 확인했다.)

## 5. 개발 환경 변경 기록(숨기지 않음)

- **개발 백엔드(4001)를 새 코드로 재시작했다**(UNIT-16 결과 반영, 이전 PID 종료 후 `scripts/run_public_api.py`를 환경변수 로드해 재기동). 재시작 후 `/screen`·`/stocks/{code}/metrics` 200, 새 엔드포인트 `/screen/pattern`은 개발 DB에 패턴 지표가 없어 **424 `PATTERN_DATA_NOT_READY`**(예상대로). 이는 0011 적용 DB에서 새 ORM 모델이 정상 동작한다는 실측이기도 하다.
- 개발 프런트(4000)는 재시작하지 않았다(개발 모드가 새 파일을 반영해 `/screener/pattern` 200).
- 개발 DB에는 쓰기를 하지 않았다.

## 6. 한계와 남은 위험

1. **실제 스크린리더(NVDA·VoiceOver) 출력은 확인하지 못했다.** 접근성 트리 속성(배지 텍스트·caption·region·aria-live·aria-invalid)만 확인했다.
2. **모바일 폭 스크린샷은 남기지 못했다**: 자동화 도구가 `iframe`이 열린 상태에서 캡처 시간 초과로 실패했다. 대신 5개 폭의 DOM 측정(레이아웃 전환·가로 스크롤·터치 타깃)으로 검증했다. 데스크톱(1496px) 실제 스크린샷은 증거로 저장했다.
3. 자동화 탭이 백그라운드로 간주돼 `requestAnimationFrame`이 지연되어, 바텀시트 첫 포커스 이동이 즉시가 아니라 늦게 일어났다(자동화 환경 특성, `document.hidden=true` 확인). 포커스 이동·트랩 순환·Esc·복귀 자체는 모두 정상 동작했다.
4. `prefers-reduced-motion`은 브라우저 설정으로 에뮬레이션하지 않고 CSS 규칙을 정적으로 확인했다.
5. 전역 요소(면책 배너 링크·헤더 링크·푸터 링크·"홈" 탭)는 높이 44px 미만이다(기존 유닛에서 만든 것, 이 유닛 범위 밖). 개선이 필요하면 별도 결정.
6. 실제 개발 DB에는 패턴 데이터가 없어 개발 화면(4000)에서는 "데이터 준비 중" 상태만 볼 수 있다. 백필·배치 후 정상 결과가 보인다.
7. 명칭 "급등 전 압축주"의 법률 검토(Q4)와 푸트노트의 "급등 이력" 문구(편차 #3)는 사용자 결정 사항으로 남아 있다.
