# 테스트 결과서 (Test Result Report) — 패턴 스크리닝 "급등 전 압축주" 통합·회귀·보안·접근성

> 양식: `templates/test-report-template.md`(전 섹션 필수). 근거 없는 "이상 없음"은 쓰지 않았고 **실행하지 못한 TC는 통과로 세지 않았다.** 개별 증거는 각 유닛 노트(`unit-11-report.md`, `unit-12~17-note.md`)에 있고 이 문서는 그 전체 통합본이다.

## 1. 개요
- 테스트 대상: **패턴 스크리닝 신규 기능 전체**(REQ-030~038, UNIT-11~18) — 백필·계산·스키마/배치·설정/리포트·API·프런트엔드와 기존 기능 회귀
- 테스트 유형: 시스템(통합·회귀·보안·접근성·문서)
- 적용 Tier: **High**(공개 서비스·규제 도메인)
- 적용 속도 트랙: N/A(13단계 파이프라인은 사용자가 2026-09-22 폐기, `decisions.md` DEC-038 작업 방식 참조)
- 테스트 목적: 05 테스트계획 §3~§13의 TC 139개를 실제로 실행해 결과를 근거와 함께 기록, 미실행·한계·잔존 위험을 명시
- 관련 산출물: `docs/pattern-screening/01~06`, `units/unit-11-report.md`, `unit-12~17-note.md`, `docs/harness/traceability.md`(REQ-030~038), `decisions.md`(DEC-032~039)
- 테스트 수행자(에이전트): Claude (Sonnet 5.5)
- 테스트 일시: 2026-10-02 12:46 ~ 15:30 KST (실행 시각은 각 노트 참조, 최종 재실행 15:22~15:26)

## 2. 테스트 범위 및 제외 범위
- **범위(In-Scope)**: REQ-030~036의 구현 전체(계산 함수·백필 스크립트·마이그레이션 0011·배치 확장·설정 로더·보정 리포트·`GET /api/v1/screen/pattern`·`/screener/pattern`), 기존 기능 회귀(단위 213건 + 통합 2건 + 기존 API 5종 + 프런트 4개 경로), 보안(S01~S12), 성능(P01~P04), 접근성(X01~X06), 규제 표현(R01~R06).
- **제외 범위 및 사유**
  - REQ-037(실적 c8)·REQ-038(수급 c6·c7): 이번 릴리스 설계 제외(로드맵) — **구현되지 않았음**을 TC-G07로 확인.
  - **실제 공공데이터포털 API로 백필 실행**: 서비스키 일일 호출 한도 확인 대기(사용자 결정). 따라서 **TC-B08**(실데이터 완료 비율 ≥95%)과 개발 DB 실데이터 기반 **임계값 적정성(Q2)**은 미검증.
  - 모바일 Lighthouse(**TC-P04**): 새 패키지(`lighthouse`) 설치 없이는 측정 도구가 없어 미실행(이 저장소는 새 의존성 금지).
  - 배포·원격 푸시·PR: 사용자가 요청하기 전에는 하지 않는다(규칙 E). **배포 승인 요청은 하지 않았다.**

## 3. 테스트 환경
- 실행 환경: Windows 10 Pro, Python 3.12(`py -3.12`), Node v24.18.0 / Next.js 16.3.5(Turbopack), Docker `stock-screener-pg`(PostgreSQL 16), Chrome(Browser 2, 사용자 선택)
- 테스트 데이터: **임시 DB**(`stock_screener_test_<난수>`, `alembic upgrade head`로 실제 스키마·GRANT 적용)에 픽스처 종목 T00001~T00010(각 130거래일, 시드 고정)과 합성 2,700종목(P01). 개발 DB `stock_screener`에는 합성 데이터를 넣지 않았다(쓰기는 사용자 승인한 마이그레이션 0011 적용 1건뿐). 외부 API는 `httpx.MockTransport`로 대체(실 호출은 UNIT-11의 2회뿐).
- 전제 조건: Docker 컨테이너 기동, `.env`의 DB 접속 정보, `frontend/node_modules` 설치. 오라클 `prototype/pattern_rules_reference.py`로 계산 결과 교차 검증.

## 4. 테스트 케이스 및 결과

### 4-1. 최종 재실행 요약 (2026-10-02 15:22~15:26 KST, 실제 출력)

| 항목 | 결과 |
|---|---|
| `pytest tests/unit` | **520 passed** (착수 전 기준선 213 → +307) |
| `pytest tests/integration` | **125 passed** (착수 전 2 → +123, 임시 DB 통합) |
| 이번 작업에서 새로 만든 테스트 | **430건**(단위 307 + 통합 123), 실패 0 · 건너뜀 0 |
| `ruff check shared services scripts tests db` | `All checks passed!` |
| `ruff check .`(저장소 전체) | 18건 — **전부 기존 프로토타입 문서 `prototype/pattern_rules_reference.py`**(사용자 결정 "그대로 둠", DEC-039). 신규 위반 0 |
| 프런트 `tsc --noEmit` · `eslint .` · `lint:copy` | 오류 0 · 오류 0 · 통과(검사 파일 62개) |
| `next build`(격리 복사본) | 통과, `/screener/pattern` 생성 |
| 임시 DB 잔여(`stock_screener_test_%`) | **0개** |

파일별(새 테스트): 단위 — `test_backfill_ohlcv` 28, `test_pattern_compute` 46, `test_run_derivation_pattern` 11, `test_pattern_config` 137, `test_pattern_api` 85 / 통합 — `test_backfill_ohlcv_db` 13, `test_pattern_derivation_db` 9, `test_pattern_conditions_db` 55, `test_pattern_report_db` 11, `test_pattern_api_db` 35.

### 4-2. 05 테스트계획 TC 139개 전수 (그룹별 · ID 범위 · 판정 · 근거)

| TC | 내용 | 판정 | 근거(유닛 노트) |
|---|---|---|---|
| U01~U16, U40~U42 (19) | 계산 순수 함수(손계산·경계·0분모·순수성·**오라클 교차 검증 300건**·윈도우 절단·입력 규약) | PASS 19 | `unit-13-note.md` §3 — 수치 2,206건 비교 최대 오차 5.0e-05, 변이 12/12 적발 |
| B01~B07 (7) | 백필(dry-run·건너뜀·0건 경고·**서킷브레이커 비오염**·키 비노출·재개·`--max-calls`) | PASS 7 | `unit-12-note.md` §3 — 임시 DB 통합 13건 + 단위 28건, B04 변이로 효력 입증 |
| **B08** (1) | 백필 후 `n≥80` 종목 비율 ≥95%(실데이터) | **미실행** | 실제 백필 미실행(호출 한도 확인 대기). 검증 쿼리 로직만 `test_coverage_ratio_counts_stocks_with_enough_rows`로 확인 |
| D01~D08 (8) | 마이그레이션 가역·CHECK·구 행 보존·`run_once` 멱등·**실제 역할 권한**·혼합 발행·`_validation_passed` 불변·기존 지표 무변화 | PASS 8 | `unit-14-note.md` §3 — 변이 8/9 적발(1건 동등 변이) |
| C01~C08 (8) | 설정 로더(기본값·범위·타입·MIN<MAX·교차 일수·끝값·스위치·`definition`) | PASS 8 | `unit-15-note.md` §3 — 137건 |
| A01~A35 (35) | API: envelope·시장·`required`·정렬·페이지·NULLS LAST·3값·readiness·424/200/503·화이트리스트·`definition`·스위치·**골든 `/screen` 불변** 등 | PASS 35 | `unit-16-note.md` §3 — 단위 85 + 통합 35 + SQL 계층 55(UNIT-15). A15는 문구 정정(DEC·05 문서 정정), A35는 골든 5건+소스 해시+`git diff` |
| S01~S12 (12) | 인젝션·대량 입력·알 수 없는 파라미터·임계값 우회·rate limit·보안 헤더·원본 필드 비노출·DB 장애·**백필 키 비노출**·프런트 정적 점검·CORS·의존성 불변 | PASS 12 | `unit-16-note.md`(S01~S08·S11·S12), `unit-12-note.md`(S09=B05), `unit-17-note.md`(S10) |
| P01~P03 (3) | API p95(합성 2,700종목 50회: median 32.7ms · **p95 42.1ms**), 실행 계획(기존 인덱스 Bitmap Index Scan), 배치 전후(1.19배, 2,880종목 ≈ +2초) | PASS 3 | `unit-16-note.md` §3, `unit-14-note.md` §4 |
| **P04** (1) | 모바일 Lighthouse Performance ≥80 | **미실행** | 측정 도구 미설치·새 패키지 금지. 개발 서버 빌드/번들 크기 측정은 하지 않음 |
| F01~F19, F21, F23, F25, F26 (23) | 프런트: 정적 검증·금지어 음성·전환 링크·`/screener` 불변·자동 조회·로딩·표/카드·**320px 가로 스크롤 없음**·배지·사유·정의 패널·검증 오류·0건·준비 중·부분 산정·오류 3종·스위치 off·**명칭 단일 출처**·바텀시트 트랩·200% 확대·면책 배너·내비 활성 | PASS 23 | `unit-17-note.md` §4 — 실제 Chrome(임시 스택)·격리 빌드 |
| **F20, F22, F24** (3) | 키보드 탭 순서 전수 측정 / 접근성 트리(스크린리더 음성) / `prefers-reduced-motion` 에뮬레이션 | **부분 확인** | F20: Esc·포커스 복귀·트랩 순환 확인, 탭 순서는 DOM 순서로 구성(전수 측정 미실시). F22: 속성 수준만, **실제 스크린리더 미확인**. F24: CSS 규칙 정적 확인, 브라우저 에뮬레이션 미실시 — 통과로 세지 않음 |
| X01~X06 (6) | 대비(렌더 색 계산, 전부 4.5:1 이상)·터치 타깃 ≥44px·헤딩·라벨·오류 연결·`lang` | PASS 6 | `unit-17-note.md` — X02는 패턴 화면 범위(전역 배너·푸터 링크는 기존 유닛 소관, §6 참조) |
| R01~R06 (6) | 금지어 린트·**비예측 고지 상시**·서열 표현 부재·"급등" 사용처·REQ-022 범위 명시·정의 패널 고지 | PASS 6 | `unit-17-note.md`, **R05는 이번에 `traceability.md`에 명시 완료**(REQ-034 비고와 REQ-022 확인 범위 문구) |
| G01~G07 (7) | 회귀: 전체 pytest·ruff·tsc/eslint/build·기존 스크리너 골든·**기존 API 5종 200**(`/health`, `/stocks`, `/stocks/{code}/metrics`, `/market-summary`, `/screen`)·**마이그레이션 체인 base↔head**·범위 밖 미구현 | PASS 7 | 4-1 표 + 4-3 (G05·G06·G07 실행 출력) |
| **합계 139** | | **PASS 134 · 부분 3 · 미실행 2** | 미실행·부분은 위 표에 사유 명시. **통과로 세지 않음** |

### 4-3. 이번 유닛에서 새로 실행한 회귀 항목(실제 출력)
- **G05** (개발 서버 4001·4000, 새 코드로 재시작한 뒤): `/api/v1/health` 200 · `/api/v1/stocks?query=삼성` 200 · `/api/v1/stocks/005930/metrics` 200 · `/api/v1/market-summary` 200 · `/api/v1/screen?market=KOSPI&page_size=2` 200. 프런트 `/`·`/screener`·`/screener/pattern`·`/stocks`·`/about` 전부 200. (신규 `/api/v1/screen/pattern`은 개발 DB에 패턴 지표가 없어 424 — 예상된 정상 응답)
- **G06** (임시 DB): head `0011`(앱 테이블 9개) → `alembic downgrade base` 종료코드 0·버전 없음·앱 테이블 **0개** → `alembic upgrade head` 종료코드 0·`0011`·앱 테이블 **9개**. `alembic heads` = `0011` 단일 head.
- **G07**: `c6`/`c7`/`c8` 및 수급·실적 관련 코드가 `services`·`shared`·`scripts`·`frontend/src`에 **없음**(검색 결과 0건, 화면 푸트노트의 "미반영" 안내 문구만 존재).
- **S12/A35**: `git diff HEAD`로 `requirements*.txt`·`frontend/package*.json`·기존 `/screen` 소스 3개 **변경 0줄**, 소스 3개 SHA-256(줄바꿈 정규화)이 UNIT-16 시작 시점과 동일, 변경 전 골든 5건과 현재 응답이 완전히 동일.

### 4-4. 테스트 유효성(변이 테스트) 총괄
구현의 경계·분기를 하나씩 훼손해 테스트가 실패하는지 확인했다: UNIT-12(1) + 13(12) + 14(9) + 15(16) + 16(16) = **54건 중 53건 적발, 1건은 동등 변이**(PostgreSQL이 `DROP COLUMN` 시 CHECK 제약을 함께 제거해 `downgrade`의 명시적 `drop_constraint`가 동작에 영향이 없음 — 테스트 결함 아님). 처음에 생존했던 변이 1건(UNIT-15 분포의 OK-전용 필터)은 테스트를 보강해 적발했다. 모든 변이 후 원본 복원을 확인했다.

## 5. 커버리지
- **라인/브랜치 커버리지 수치는 측정하지 않았다**: `pytest-cov`가 `requirements-dev.txt`에 없고 새 패키지 추가는 금지다. 대신 (1) 요구사항→설계→유닛→TC 추적(`traceability.md` REQ-030~038), (2) TC 139개 전수 매핑(위 표), (3) **변이 테스트 54건**, (4) 오라클 교차 검증(계산 300건, SQL 판정 800행×2 임계값 세트, ma60_stage↔c4 798격자 전수)으로 기능 커버리지와 검증의 효력을 확인했다.
- **커버되지 않은 부분과 사유**
  - 실제 공공데이터포털 API로의 대량 백필(응답 형식 변화·한도·지연 실측): 사용자 승인·한도 확인 대기. 파싱은 기존 `GovDataPortalClient`가 실제로 쓰이던 경로(2026-09-22 실 서비스키 실행 이력)를 재사용하고, 과거 날짜 가용성은 UNIT-11에서 2회 실호출로 확인했다.
  - 개발 DB 실데이터 기반 임계값 적정성(Q2): 보정 리포트 도구는 완성·검증했으나 입력 데이터(80거래일 이상)가 없다.
  - 실제 스크린리더 출력, 모바일 폭 스크린샷, `prefers-reduced-motion` 에뮬레이션, Lighthouse.

## 6. 결함(Defect) 목록

| ID | 설명 | 재현 절차 | 심각도 | 상태 | 조치 내용 |
|---|---|---|---|---|---|
| DEF-PS-01 | 설계서 D-8 "백필의 `batch_run`은 서킷브레이커에 영향이 없다"가 코드상 사실이 아님(백필 SUCCESS가 연속 실패 집계를 끊고 FAILED는 오작동) | `recent_ingest_statuses`가 `ingest` 행 최근 3건을 봄 — 코드 확인 | Medium | **Fixed** | 사용자 결정 A안으로 `BACKFILL` 접두 행 제외(DEC-034), TC-B04로 입증·변이 적발 |
| DEF-PS-02 | 05 TC-A15가 "이력 부족 종목이 전 조건 null로 응답 행에 나온다"고 했으나 설계상(`required`=IS TRUE) 불가능 | 설계서 §5-4와 TC 대조 | Low(문서) | **Fixed** | 05 문서 정정(매핑·SQL 계층·비필수 셀로 검증) |
| DEF-PS-03 | 결과 표가 1024·1280px에서 **페이지 가로 스크롤**을 만듦(설계가 금지한 동작) | 실제 Chrome, iframe 1024/1280px로 `scrollWidth>clientWidth` 측정 | **High** | **Fixed** | 그리드 `minmax(0,1fr)`·셀 줄바꿈·표 스크롤 영역, 재측정 `pageHScroll=false` |
| DEF-PS-04 | 패턴 화면 터치 타깃 44px 미만("조건 설정" 37px, 종목 링크 24/40px) | 동일 방법으로 요소 높이 측정 | Medium | **Fixed** | `min-height:44px`, 5개 폭 재측정 0건 |
| DEF-PS-05 | 표의 종목 열이 73px로 좁아 종목명이 글자 단위로 쪼개짐 | 열 폭 측정 | Low | **Fixed** | 종목 열 최소 폭·`keep-all` |
| DEF-PS-06 | 명칭 "급등 전 압축주"가 CSS 주석에 한 번 더 있어 F19(소스 1곳) 위반 | 소스 검색 | Low | **Fixed** | 주석에서 제거, 재검색 1곳 |
| DEF-PS-07 | (작업 프로세스) 통합 테스트 코드가 DB 연결을 닫지 않아 다음 테스트의 `TRUNCATE`가 락에 걸려 멈춤. 이를 끄는 과정에서 이름이 비슷한 프로세스 6개를 함께 종료했고 임시 DB 1개가 잔여 | UNIT-12 작업 중 | Low(제품 결함 아님) | **Fixed** | 테스트 코드 수정(연결 종료 헬퍼), 잔여 DB만 삭제, 이후 PID를 특정해 종료. 개발 서버·DB 영향 없음 확인 |
| DEF-PS-08 | 일일 배치 스케줄러가 `python`(3.11)을 호출해 2026-09-29부터 매일 `No module named 'sqlalchemy'`로 실패(기존 결함, UNIT-11에서 발견) | `logs/daily_batch.log` | High(기존 운영 결함) | **Fixed(코드) — 실제 동작은 다음 스케줄(2026-10-03 07:00)에서 확인 필요** | `run_daily_batch.ps1`을 `py -3.12`로 수정(사용자 승인, DEC-036), 스케줄러와 같은 호출 형태로 sqlalchemy 임포트 성공 확인. **일일 배치 자체는 실행하지 않음** |
| DEF-PS-09 | 푸트노트 원문 "거래량·급등 이력은…"이 같은 문서의 "푸트노트에는 '급등'을 쓰지 않는다"와 모순 | 03 §7 대조 | Low(문서·규제 표현) | **Deferred(사용자 결정 대기)** | 문서 원문 유지(허용 목록 R04에 명시, DEC-037). 법률 검토(Q4) 때 함께 결정 |
| DEF-PS-10 | 전역 요소(면책 배너·헤더·푸터 링크, "홈" 탭)의 터치 타깃이 44px 미만 | 같은 측정 | Low(기존 유닛 소관) | **Deferred** | 이번 범위 밖. 개선하려면 별도 결정 |

- **Critical 결함: 없음.** High는 DEF-PS-03(Fixed), DEF-PS-08(코드 Fixed, 실행 확인 대기). 위 결함은 모두 실제 실행·측정으로 발견했고, 수정 후 해당 TC와 의존 TC를 다시 실행해 통과를 확인했다.

## 7. 테스트 환경 정리(Teardown) 확인 — 규칙 K
- **이번 작업에서 생성한 임시 아티팩트**
  - 임시 DB `stock_screener_test_<난수>`(수십 회 생성): **전부 DROP**, 최종 잔여 0개.
  - `.harness-tmp/ruff-venv`(ruff 검증용 venv, 여러 번 생성) · `.harness-tmp/fe-build`(프런트 격리 빌드·임시 개발 서버용 복사본, `node_modules` 복사 포함): **삭제**, `.harness-tmp` 비어 있음.
  - 임시 서버 프로세스(포트 4511·4512·4513·4600·4601): **전부 종료**(PID를 특정해 종료). 임시 백엔드가 쓴 DB는 스택 종료 시 삭제.
  - 브라우저 탭(임시 화면): **닫음**. 증거 스크린샷 1장만 `units/evidence/`에 보관(픽스처 데이터).
  - 스크래치 스크립트(변이·측정·패치용): 저장소 밖 세션 스크래치 디렉터리에만 생성(저장소에 남지 않음).
- `.harness-tmp/` 하위에서만 생성했는가: **예**(저장소 안 임시 산출물은 `.harness-tmp`에만 생성, ruff venv·fe-build). 임시 DB는 Docker 컨테이너 내부 DB.
- 정리 후 상태: 개발 서버(DB·백엔드 4001·프런트 4000)는 **켜 둔 상태**를 유지(사용자 규칙). `frontend/node_modules` 279개 항목 온전(정리 중 임시 폴더의 연결 폴더를 지우는 명령이 실제 `node_modules`를 건드리지 않았음을 확인).
- 정리 후 `git status`(그대로):

```text
 M docs/harness/04-ux-design.md
 M docs/harness/decisions.md
 M docs/harness/traceability.md
 M docs/pattern-screening/00-README.md
 M docs/pattern-screening/02-system-design.md
 M docs/pattern-screening/04-development-plan.md
 M docs/pattern-screening/05-test-plan.md
 M frontend/src/app/globals.css
 M frontend/src/components/PatternResultsTable.tsx
 M "\353\241\234\354\273\254\354\204\234\353\262\204-\354\240\221\354\206\215\353\260\251\353\262\225.md"
?? docs/pattern-screening/units/evidence/
?? docs/pattern-screening/units/unit-17-note.md
?? docs/pattern-screening/units/unit-18-test-report.md
```

- 이번 테스트 도중 강제 중단: **있음**(UNIT-12 통합 테스트가 락으로 멈춰 프로세스를 종료) — 종료 직후 남은 임시 DB 1개를 확인해 **그 DB만** 삭제했고, 이후 모든 실행에서 잔여 0을 확인했다(DEF-PS-07).
- 위 `git status`에서 새 파일·변경은 전부 이번 작업의 의도된 산출물(코드·테스트·문서)이며 임시 아티팩트는 없다.

## 8. 리스크 및 잔존 이슈
- **커버되지 않은 알려진 리스크**
  1. 실제 대량 백필·실데이터 계산 미검증(TC-B08, Q2). 개발 화면에서는 "데이터 준비 중"만 볼 수 있다.
  2. 일일 배치 스케줄러 수정(`py -3.12`)의 실제 동작은 **2026-10-03 07:00 실행 결과**로만 확인된다(그 시점에 Derivation이 새 컬럼으로 정상 INSERT되는지 포함 — 개발 DB는 0011 적용 상태).
  3. 접근성: 실제 스크린리더·모바일 실기기·reduced-motion 에뮬레이션·Lighthouse 미확인.
  4. 계산·정의의 투자적 유효성(실제로 급등 전 신호인지)은 검증 범위 밖이며 서비스도 예측력을 주장하지 않는다(고지문).
- **후속 조치가 필요한 항목(사용자 결정 대기 — 알람 대상)**
  - **서비스키 일일 호출 한도 확인 → 백필 실제 실행 승인**(예상 호출 315회, 약 15~25분)
  - **Q2 임계값 확정**(백필 후 `scripts/pattern_threshold_report.py` 결과 기반)
  - **Q3 스팩·우선주 포함 여부**(활성 2,760종목 중 스팩 69 + 우선주 117, 이름 패턴 기준)
  - **Q4 명칭 "급등 전 압축주"의 공개 배포 적합성(법률 검토, REQ-022 확인 범위에 포함)** — 푸트노트 "급등 이력" 문구(DEF-PS-09)도 함께
  - **Q5** `정찬욱주식현황요청_카톡/` 이미지가 이미 `origin/PROD_SCH`에 푸시됨 — 원격 제거 여부(이력 재작성·강제 푸시는 하지 않았고 하지 않는다)
  - 배포는 위 Q4·REQ-022 확인 후 **사용자의 명시적 승인**이 있을 때만(규칙 E). 이 문서는 배포 승인 요청이 아니다.

## 9. 결론 및 판정
- [ ] PASS
- [x] **CONDITIONAL PASS** — 조건: (1) ~~백필 실제 실행 후 TC-B08·보정 리포트~~ → 2026-10-02 수행 완료(후속 보완 참조), (2) 2026-10-03 07:00 일일 배치 정상 실행 확인, (3) Q3·Q4·Q5 사용자 결정, (4) TC-P04·F20/F22/F24의 부분·미실행 항목은 별도 수행 또는 위험 수용 결정.
  근거: TC 139개 중 134 PASS, 부분 3, 미실행 2(전부 사유 명시). Critical 결함 없음, High 결함은 수정·재검증 완료 또는 실행 확인 대기. 코드·계산·API·화면은 설계서와 05 테스트계획이 요구한 범위에서 동작함을 실제 실행으로 확인했고, 남은 조건은 모두 **외부 요인(실 API 호출 한도·법률 검토·스케줄 실행)** 이다.
- [ ] FAIL

## 10. 내부 검증 (최소 2회)
- **1차 검증(유닛별 TDD)**: 각 유닛에서 TC를 먼저 작성해 실패를 확인 → 구현 → 통과 → ruff·기존 회귀 → 변이 테스트로 테스트의 효력 확인(54건 중 53건 적발·1건 동등). 변이에서 살아남은 테스트 결함은 테스트를 보강해 재적발. 근거는 `unit-12~17-note.md` 각 §3.
- **2차 검증(독립 재실행·교차 확인)**: 마지막에 전체 스위트를 새로 실행(단위 520·통합 125, ruff, tsc/eslint/lint:copy/build), 마이그레이션 체인 base↔head(G06), 기존 API 5종·프런트 5경로(G05), 범위 밖 미구현(G07), 의존성·기존 계약 파일 불변, 개발 환경 상태(서버·임시 DB·임시 폴더)를 직접 조회해 확인. 실제 브라우저에서 상태 9종·5개 폭·접근성 항목을 직접 조작해 측정했다(결함 3건 발견·수정 후 재측정).
- **문서 정합성 점검**: TC 139개 전수가 4-2 표에 정확히 한 번씩 매핑되는지 스크립트로 확인(아래 부록 A), `decisions.md` 신규 행 열 수·`traceability.md` 신규 행 열 수 확인, 05 TC-A15·02 설계서 변경 지도·04 개발계획·00-README·`로컬서버-접속방법.md`를 구현 사실에 맞게 정정.
- 검증 로그 파일 경로: 각 유닛 노트의 "테스트 유효성 검증(변이 테스트)" 절 + 이 문서 4~10절. (`verify-log_pattern-screening.md`는 문서 단계 검증 로그이며, 구현 단계 검증은 위 노트들이 대체한다.)

## 후속 보완 (2026-10-02, 위 표는 변경하지 않고 사후 결과만 추가)

| 항목 | 실제 실행 결과 |
|---|---|
| **B08 실데이터 백필** | `backfill_ohlcv.py --days 130 --max-calls 300` 실행: 99일/284,724행 저장, 호출 300회, 상태 PARTIAL(오래된 5일 남음, 재실행 시 이어서 처리). 80일 이상 보유 종목 **2,861/2,925(97.8%)** → 기준 95% 충족 → **B08 PASS로 갱신**(집계표의 '미실행'은 당시 기준). |
| **파생 지표 계산** | `run_derivation --trade-date 2026-09-21` SUCCESS(개발 DB 기록). |
| **Q2 보정 리포트(기본 임계값)** | 평가 대상 2,577 중 산정 가능 2,403(93.2%). 6조건 동시 충족 26건(1.0%) → 판정 **OK**. 조건별 충족률 c1 29.2% · c2 46.5% · c3 38.1% · c4 32.2% · c5 13.9% · c9 78.7%. |
| **Q3 스팩·우선주 제외(DEC-040)** | 구현·테스트 완료(위 평가 대상 2,577은 제외 후 기준). 신규 `test_pattern_universe_db.py` 2건 + 설정·API·리포트 테스트 추가. 제외 규칙 변형(코드 끝자리 조건 변경) 시 테스트 실패 확인. |
| **전체 회귀** | `pytest tests/unit tests/integration` **658 passed**, ruff check/format(변경 파일) 통과. |
| **화면(4000) 실확인** | 실브라우저에서 `/screener/pattern`이 실제 데이터로 표시됨(화면 기본 필터 적용 시 2건). 데이터 기준일 2026-09-21이라 "7영업일 지연" 안내가 함께 표시됨(정상 동작, 최신일 파생은 재무·시총 미수집으로 보류). |

## 부록 A. TC 매핑 점검 결과
- 05 테스트계획에 정의된 TC: **139개**, 결과서 4-2 표에 매핑된 TC: **139개**
- 누락: 없음 · 중복: 없음 · 정의에 없는 ID: 없음
- 판정 집계: PASS 134 · 부분 3 · 미실행 2 (합계 139)
- 미실행: ['B08', 'P04'] · 부분: ['F20', 'F22', 'F24']
