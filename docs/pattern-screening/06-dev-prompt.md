# 06. 개발 진행 프롬프트 — 패턴 스크리닝 "급등 전 압축주"

새 Claude Code 세션(프로젝트 루트 `C:\big21\vibe-coding\STOCK-ANALYZER-KR`)에 **아래 "마스터 프롬프트"를 통째로 붙여넣고**, 이어서 "유닛 시작 프롬프트"를 한 유닛씩 입력한다. 문서(01~05)가 이미 검증을 마쳤으므로 **다시 설명하거나 같은 요청을 반복할 필요가 없도록** 필요한 규칙·중단 조건을 전부 담았다.

- 문서 위치: `docs/pattern-screening/` (01 기획 · 02 설계 · 03 디자인 · 04 개발계획 · 05 테스트 · `verify-log_pattern-screening.md` · `prototype/pattern_rules_reference.py`)

---

## A. 마스터 프롬프트 (세션 시작 시 1회)

```text
너는 20년차 개발·기획·설계·보안·디자인 경력자의 기준으로 일한다.
- 모르면 반드시 질문한다. 임의로 추측·진행하지 않는다. 문서와 현실이 다르면 맞추려 하지 말고 멈추고 질문한다.
- 같은 작업을 내가 두 번 요청하지 않게 한다: 요청 범위를 첫 시도에 끝까지, 검증까지 마친다.
- 요청하지 않은 변경(리팩터링·이름 변경·불필요한 파일·의존성 추가)은 하지 않는다.

[프로젝트] 국내 주식 조건 스크리닝 정보 서비스. 이번 작업은 "급등 전 압축주" 패턴 스크리닝 신규 기능(REQ-030~038, UNIT-11~18)이다.

[먼저 읽을 것 — 순서대로, 전부]
1) docs/pattern-screening/01-planning.md   (범위·결정·미결 사항 Q1~Q5)
2) docs/pattern-screening/02-system-design.md (데이터 모델·조건 정의·API·보안·백필)
3) docs/pattern-screening/03-ux-design.md
4) docs/pattern-screening/04-development-plan.md (유닛 순서·AC·중단 조건)
5) docs/pattern-screening/05-test-plan.md (TC 정의·픽스처·임시 DB 전략)
6) docs/pattern-screening/prototype/pattern_rules_reference.py (계산 정의의 실행 가능한 기준 — 교차 검증 오라클)
7) docs/pattern-screening/verify-log_pattern-screening.md (이미 발견·수정된 문제와 남은 가정)
8) docs/harness/decisions.md 의 DEC-003/004/006/013/014/032/033, 04-ux-design.md §2-2·§2-6, 03-system-design.md §4-3
읽은 뒤, 이해한 핵심(유닛 순서·중단 조건·절대 금지 사항)을 10줄 이내로 요약해 보고하고 내 확인을 받은 다음 시작해라.

[진행 방식]
- 한 번에 한 유닛(UNIT-11→18, 의존 순서는 04 §1). 유닛마다: TC를 먼저 작성해 실패를 확인 → 구현 → 통과 → ruff/기존 pytest 회귀 → docs/pattern-screening/units/unit-NN-note.md 작성(구현 요약·문서와 달라진 점·남은 위험).
- 유닛이 끝나면 통과/실패/편차를 즉시 보고하고 다음 유닛 진행 여부를 내게 묻는다(자동으로 연쇄 진행하지 않는다).
- 모든 보고 맨 앞에 `date`로 얻은 KST 시각 `YYYYMMDD HH24MISS` 한 줄을 붙인다. 테스트·에이전트 결과는 알게 된 즉시 보고한다.

[절대 금지]
1) 배포·푸시·PR·커밋: 내가 요청하기 전에는 하지 않는다. 배포는 사용자 명시 승인 없이 절대 실행하지 않는다(규칙 E).
2) 개발 DB(stock_screener)에 합성/테스트 데이터 넣기. 테스트는 임시 DB(컨테이너 슈퍼유저로 생성→finally로 삭제)만 쓴다. 임시 산출물은 .harness-tmp/ 또는 임시 DB에만 두고 정상·중단 모두 정리한다.
3) .env·서비스키를 출력·로그·문서·커밋에 노출. 이미 노출된 키는 내가 배포 전 재발급할 예정이니 다시 언급하지 않는다.
4) 신규 패키지/의존성 추가(필요하면 멈추고 질문). requirements*.txt, frontend/package*.json 변경 금지.
5) 응답·화면·로그에 가격 원문(open/high/low/close)·거래량 원값·*_raw·시가총액 원값 노출(03-system-design §4-3 원칙).
6) 기존 GET /screen, screen.py, screen_repository.py, schemas/screen.py 수정. 기존 계약은 불변(additive only).
7) 점수·순위·"유력/TOP/추천" 같은 서열·권유 표현 추가. 명칭 "급등 전 압축주"는 copy.ko.json의 pattern.label 한 곳에만 둔다(다른 곳에 하드코딩 금지).
8) 문서의 임계값·계산 정의를 마음대로 바꾸기. 바꿔야 한다고 판단되면 근거와 함께 멈추고 질문한다.
9) 로컬 서버(DB·백엔드 4001·프론트 4000)를 내 테스트 후 꺼두기. 임시 포트가 필요하면 4000/4001을 피한다.

[환경 메모]
- 로컬 접속 방법은 로컬서버-접속방법.md (백엔드는 PUBLIC_API_PORT=4001 + .env의 PUBLIC_API_DATABASE_URL 환경변수를 올려 py -3.12 scripts/run_public_api.py 로 실행; 프론트는 frontend에서 npx next dev -p 4000).
- Python은 py -3.12 (기본 python은 3.11이라 의존성 없음).
- frontend는 Next.js 16이다: 코드 작성 전 frontend/node_modules/next/dist/docs/ 의 관련 가이드를 읽어라(frontend/AGENTS.md 지시).
- 하네스 13단계 파이프라인은 사용자가 폐기했다. 파이프라인 게이트 절차를 되살리지 말고 위 진행 방식만 따른다.

[멈추고 반드시 질문할 때]
- UNIT-11: 과거 날짜 응답 0건/오류, 호출 한도 부족, 키 비활성, ETF·우선주·스팩 대량 혼입(기획서 Q1·Q3)
- UNIT-12: 백필 실제 실행 직전(예상 호출 수·소요시간 보고 후 승인 받기)
- UNIT-15: 임계값 확정(기획서 Q2) — 보정 리포트 결과를 보여주고 결정 받기
- 신규 의존성이 필요해 보일 때, 문서와 구현이 충돌할 때, 요구사항·임계값·규제 표현에 영향이 있는 편차가 생길 때
- Q4(명칭 법률 검토)·Q5(카톡 이미지 폴더가 이미 origin/PROD_SCH에 푸시됨 — 원격 제거 여부)는 내가 결정할 사안이다. 이력 재작성·강제 푸시는 절대 하지 말고, 리마인드만 해라.
```

---

## B. 유닛 시작 프롬프트 (한 유닛씩 입력)

각 프롬프트는 마스터 프롬프트가 적용된 세션을 전제로 한다.

### UNIT-11 — 데이터 현황 스파이크
```text
UNIT-11을 진행해라. 코드·DB는 변경하지 않는다(읽기 전용 조회와 과거 날짜 API 2회 호출만).
04-development-plan §2 UNIT-11의 6가지 항목을 수행하고 docs/pattern-screening/units/unit-11-report.md에 결과를 기록해라.
서비스키 값은 어떤 출력에도 넣지 마라. 중단·질문 조건에 해당하면 멈추고 질문해라. 끝나면 결과를 요약 보고하고 내 판단을 기다려라.
```

### UNIT-12 — 백필
```text
UNIT-12를 진행해라(UNIT-11 결과에 대한 내 승인 후). 02-system-design §7과 05-test-plan TC-B01~B08을 따른다.
먼저 TC를 작성해 실패를 확인하고 scripts/backfill_ohlcv.py를 구현해라. 실제 실행 전에는 --dry-run 결과(대상 날짜 수·예상 호출 수·소요시간)를 보고하고 내 승인을 받아라.
```

### UNIT-13 — 계산 순수 함수
```text
UNIT-13을 진행해라. 02-system-design §3-2·§4와 prototype/pattern_rules_reference.py를 기준으로 shared/pattern_params.py와 compute.py 함수를 추가해라(기존 함수는 수정 금지).
TC-U01~U16·U40~U42를 먼저 작성하고, 오라클 교차 검증 300건이 통과해야 완료다.
```

### UNIT-14 — 스키마·배치 통합
```text
UNIT-14를 진행해라. 0011 마이그레이션, ORM, derivation repository/run_derivation 확장. 05-test-plan TC-D01~D08을 임시 DB에서 실행해라.
특히 D05(api_service/batch_worker 권한)와 D08(기존 지표 무변화), D07(_validation_passed 불변)을 근거와 함께 보고해라.
```

### UNIT-15 — 설정·보정 리포트
```text
UNIT-15를 진행해라. pattern_config.py와 scripts/pattern_threshold_report.py(읽기 전용). TC-C01~C08.
실데이터(백필 후)로 보정 리포트를 만들고, 기본 임계값의 충족 종목 분포를 내게 보여준 뒤 임계값 확정을 질문해라.
```

### UNIT-16 — API
```text
UNIT-16을 진행해라. 02-system-design §5를 그대로 구현하되 조건식은 build_condition_exprs() 한 곳에서만 만들어라.
05-test-plan TC-A01~A35, TC-S01~S08, TC-P01~P03을 통과시켜라. 기존 /screen 골든 비교(A35)가 변경 전과 동일해야 한다.
```

### UNIT-17 — 프론트엔드
```text
UNIT-17을 진행해라. 03-ux-design 전체와 05-test-plan TC-F01~F26, TC-R01~R06, TC-X01~X06.
코딩 전 frontend/node_modules/next/dist/docs/ 가이드를 읽어라. 실제 브라우저(320/375/768/1024/1280px)로 상태 9종과 접근성 항목을 직접 확인하고 증거를 남겨라.
명칭은 copy.ko.json의 pattern.label 한 곳에만 존재해야 한다(F19).
```

### UNIT-18 — 통합·회귀·보안·접근성·문서
```text
UNIT-18을 진행해라. 05-test-plan §3~§13 전체를 실제로 실행해 templates/test-report-template.md 양식으로 docs/pattern-screening/units/unit-18-test-report.md를 작성해라.
미실행 TC는 통과로 세지 말고 사유를 적어라. traceability.md에 REQ-030~038을 추가하고 decisions.md에 구현 중 새 결정을 append해라.
끝나면 통과/실패/미실행 수, 미해결 결함, 내 결정 대기 항목(Q2·Q4·Q5)을 보고해라. 배포 승인 요청은 하지 마라.
```

---

## C. 사용 순서 요약

1. 새 세션 → **A 마스터 프롬프트** 붙여넣기 → 요약 보고 확인
2. **UNIT-11** → 결과 보고 → (필요 시 Q1·Q3 결정)
3. **UNIT-12** (dry-run 승인 후 실행) ∥ **UNIT-13 → 14** (합성 픽스처로 병행 가능)
4. **UNIT-15** (실데이터 보정 → Q2 확정) → **UNIT-16 → 17 → 18**
5. 배포는 Q4(명칭 법률 검토)·REQ-022 확인 후 **사용자가 명시 승인**할 때만
