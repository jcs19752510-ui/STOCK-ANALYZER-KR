# 통합 서비스(웹+API 1개) 내부 시험 결과서 (DEC-078)

- 일자: 2026-10-06 / 브랜치: `PROD_SCH`
- 대상: 웹(Next.js)+API(FastAPI)를 Render 서비스 1개(컨테이너 1개)로 합치는 변경 일체
- 결론: **자동 시험 전부 통과. 단, 이 환경에는 Docker가 없어 컨테이너 이미지의 실제 빌드는 시험하지 못했다(§6).**

## 1. 변경 요약

| 구분 | 파일 | 내용 |
|---|---|---|
| 기동·감시 | `scripts/run_unified.py` | API(내부 127.0.0.1:8000) 기동 → `/api/v1/live` 응답 후 웹(공개 PORT) 기동. 한쪽 종료 시 나머지 종료+비정상 종료 코드(→ Render 재시작). SIGTERM은 둘 다에 전달 후 0 종료. 웹은 `node next` 직접 실행, `NODE_OPTIONS` 기본 256MB 힙 |
| 이미지 | `deploy/unified.Dockerfile` | 웹 빌드·운영 의존성 단계 + 파이썬 최종 이미지(node 실행 파일 복사, 일반 계정 `app`, `CMD run_unified.py`) |
| 블루프린트 | `render.unified.yaml` | 서비스 1개(이름 `stock-analyzer-web` 유지 → 주소 동일). **전환 전까지 `render.yaml`은 그대로**(Render가 푸시마다 render.yaml을 동기화하므로 미리 바꾸면 운영이 즉시 바뀐다) |
| 자동 배포 | `.github/workflows/render-deploy.yml` | API 배포 훅을 선택 사항으로(통합 후엔 웹 훅만 필요) |
| 시험 | `tests/unit/test_run_unified.py`(9), `tests/unit/test_unified_deploy_files.py`(11), `tests/e2e/login_stack.py --unified` | §2~§5 |
| 문서 | DEC-078, `docs/ops/unified-service-guide.md` | 구조·전환 절차·롤백·한계 |

기존 동작은 바꾸지 않았다: `render.yaml`·`deploy/backend.Dockerfile`·`deploy/frontend.Dockerfile`·앱 코드(웹/API)는 수정하지 않았다.

## 2. 단위 시험 — 기동·감시 (가짜 API/웹 프로세스, 9건 통과)

| # | 확인 내용 | 결과 |
|---|---|---|
| 1 | API가 1.5초 늦게 준비돼도 웹은 API 응답 뒤에 시작 | PASS |
| 2 | API는 `127.0.0.1:<내부포트>`, 웹에는 `NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:<포트>`, `NODE_OPTIONS=--max-old-space-size=256` | PASS |
| 3 | 이미 설정된 `NODE_OPTIONS`/API 주소는 덮어쓰지 않음 | PASS |
| 4 | SIGTERM → 둘 다 종료, 종료 코드 0 | PASS |
| 5 | API가 죽으면 웹도 종료, **죽은 쪽 종료 코드(7) 그대로 전달** | PASS |
| 6 | 웹이 죽으면 API도 종료, 코드(3) 전달 | PASS |
| 7 | API가 준비되지 않으면(대기 한도 초과) 웹을 띄우지 않고 1로 실패, API 정리 | PASS |
| 8 | API가 시작하자마자 죽으면 그 코드(5)로 실패, 웹은 뜨지 않음 | PASS |
| 9 | 기본 기동 명령은 npx 없이 `node …/next start -H 0.0.0.0 -p PORT` | PASS |

## 3. 정적 시험 — 배포 파일 (11건 통과)

Dockerfile `COPY` 원본 경로 전부 존재 / 필수 코드 폴더 포함 / `USER app` 후 `CMD`, uvicorn 직접 실행 없음(공식 기동기 경유) / 웹 실행 산출물(`node`, `node_modules`, `.next`, `next.config.mjs`)과 `libstdc++6`·`tzdata` 포함 / 내 PC 전용 기능(`NEXT_PUBLIC_LOCAL_INTRADAY_ENABLED`) 미설정 / 빌드 인자 ⊂ 블루프린트 환경변수 / 서비스 1개·이름·헬스체크·브랜치 / **기존 두 서비스의 환경변수가 빠짐없이 합쳐졌는지**(CORS·프록시 대역·HOST/PORT만 의도적으로 제외) / 비밀값은 `sync:false`이고 값 미기재 / 통합 고정값(`NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000`, `REQUIRE_TRUSTED_PROXY=false`) / 워크플로 게이트가 API 훅 없이도 통과·API 훅은 있을 때만 호출.

## 4. 실제 프로세스 시험 (실제 API + 실제 웹, `scripts/run_unified.py` 하나로 기동)

원본 출력: `docs/qa/2026-10-06/unified-real-process.txt`

| 항목 | 결과 |
|---|---|
| 기동 → `/healthz` 200 | 2초(이미 빌드된 상태) |
| **API 바인딩** | `127.0.0.1:4321`만 — 외부에 열리지 않음 |
| 웹 바인딩 | `0.0.0.0:4322` |
| 메모리(유휴) | API 73MB + 웹 96MB + 기동기 21MB |
| 메모리(로그인 화면·상태 조회 60회 후) | API 87MB + 웹 137MB + 기동기 21MB = **약 245MB** (Render 무료 512MB 이내, 여유 약 2배) |
| API를 `kill -9` | 기동기가 웹을 종료하고 **비정상 종료 코드(247=−9)** → Render가 재시작 |
| 웹을 `kill -9` | 기동기가 API를 종료하고 비정상 종료 코드 |
| SIGTERM(배포 종료) | **0.3초** 만에 둘 다 종료, 코드 0, 포트 모두 해제 |

※ 메모리는 가벼운 부하 기준이다. 실제 Render 환경(무료 0.1 vCPU)의 실측은 전환 후 §6 항목으로 확인한다.

## 5. 종단간(E2E) — 로그인 전체 시험을 통합 구성으로 재실행

`python tests/e2e/login_stack.py --unified` (임시 PostgreSQL + `run_unified.py`로 API·웹 기동 + 실제 브라우저, 시나리오 A~M)

- **결과: 322/322 통과** (기존 분리 구성의 322건과 동일 시나리오). 요약: `docs/qa/2026-10-06/unified-login-e2e.txt`
- 시나리오별 통과 수: A 51, B 20, C 39, D 33, E 2, F 3, G 15, H 27, I 38, J 19, K 30, L 40, M 5 (합계 322)
- 회귀: 기존 단위 시험 전체 `791 passed, 1 skipped`, `ruff check` 통과.

시험 중 발견·수정한 것(시험 도구 쪽 결함, 제품 결함 아님): 통합 모드에서 셸의 개발 DB 주소가 임시 DB 주소를 덮어 API가 엉뚱한 DB를 봄 → 환경 병합 순서 수정 후 재실행(첫 실행은 이 때문에 2건 실패했고 수정 후 전부 통과).

## 6. 이 환경에서 시험하지 못한 것 (한계 — 숨기지 않고 적는다)

| 항목 | 이유 | 전환 때 확인 방법 |
|---|---|---|
| **Docker 이미지 실제 빌드** | 시험 환경에 Docker 없음 | Render 첫 빌드 로그. 실패해도 기존 버전은 그대로 유지(운영 영향 없음). 로그를 알려 주면 바로 수정 |
| 파이썬 이미지 위에서 복사한 `node`의 실행 | 동일 | 기동 로그의 `[unified] API 준비 완료 → 웹 기동` 이후 웹 로그 |
| Render 무료 512MB 안의 실제 메모리 | Render에서만 측정 가능 | Render Metrics. 부족하면 `NODE_OPTIONS`를 192MB로 낮춤 |
| 콜드스타트 실제 소요(서비스 1개가 깨어나는 시간) | 동일 | 15분 방치 후 접속 시간 |
| Render 프록시 뒤에서의 방문자 IP(속도 제한 버킷) | 기존과 동일한 한계(웹이 IP 헤더를 신뢰하지 않음, 전 사용자가 한 버킷) | 변경 없음 — 기존 항목 |

## 7. 위험과 대응

| 위험 | 대응 |
|---|---|
| 한 프로세스만 죽은 채 "정상"으로 남음 | 기동기가 어느 한쪽 종료 시 전체 종료 → Render 재시작(§2·§4 시험) |
| 메모리 초과 | 웹 힙 256MB 제한, API 단일 워커, npx 래퍼 제거. 실측 약 245MB |
| 전환 중 운영 중단 | 블루프린트를 별도 파일로 두고 전환 때만 교체, 기존 API 서비스는 검증 전까지 유지(롤백 경로) |
| 빌드 인자 누락으로 `NEXT_PUBLIC_*` 빠짐 | 정적 시험이 인자와 환경변수 일치를 검증 |

## 8. 전환 절차 요약

사용자 작업: ① API 서비스의 DB 주소 2개를 웹 서비스 환경변수로 복사 ② "했다"고 알림 ④ Deploy latest commit. 나머지(블루프린트 교체 푸시, 접속·로그인 확인)는 에이전트가 진행. 상세: `docs/ops/unified-service-guide.md`.
