# 인수인계 (2026-10-06 기준) — 새 세션은 이 파일과 `docs/harness/decisions.md`를 먼저 읽는다

## 상시 규칙 (사용자 지시)
- 20년차 개발/기획/설계/보안담당자/디자이너 기준으로 일한다. 모르면 묻되, **아주 특이한 점만** 묻고 나머지는 그대로 진행한다. 마음대로 하지 않는다.
- 사용자에게 같은 작업을 두 번 시키지 않는다. 내가 할 수 있는 것은 내가 한다(Render 화면 조작, 비밀값 열람은 불가 → 꼭 필요한 최소 단계만 한 번에 정확히 안내).
- 모든 작업은 **내부 테스트 결과서를 완벽하게** 작성한다(`docs/qa/`).
- 보안 이야기는 하지 않는다("보안은 나중에").
- 운영 변경은 사용자가 요청했을 때만. 응답은 짧고 결과 중심으로.

## 현재 운영 구조 (2026-10-06 전환 완료)
- Render 서비스 **1개** `stock-analyzer-web` (https://stock-analyzer-web-q7cx.onrender.com): 컨테이너 안에서 API(내부 127.0.0.1:8000)와 웹(공개 PORT)을 `scripts/run_unified.py`가 함께 기동·감시 (DEC-078). 이미지 `deploy/unified.Dockerfile`, 블루프린트 `render.yaml`.
- 이전 2개 서비스 구성: `deploy/render/render.two-services.yaml`(롤백용). 기존 `stock-analyzer-api` Render 서비스는 **Suspended**(삭제 전, 롤백 경로). 며칠 안정 확인 뒤 사용자가 삭제.
- DB: Neon Postgres(스키마 `auth`), 배치(내 PC 스케줄러/GitHub Actions)는 DB에 직접 쓴다.
- **요금제: Starter(유료, 월 $7, 0.5 CPU/512MB)로 전환(2026-10-06, 사용자가 Render Compute 화면에서 변경 → `render.yaml`의 `plan: starter`로 동기화).** 15분 유휴 후 잠들지 않아 콜드스타트가 없다. 48시간 평균 메모리 사용률 10~25%. Blueprint 서비스는 대시보드에서만 바꾸면 되돌아갈 수 있어 변경 시 `render.yaml`도 함께 바꾼다.
- 검증(전환 후): `/auth/status` web ok·api ok, 로그인 401(틀린 비번), 비로그인 차단 확인. 첫 접속(콜드스타트)은 30초대 소요 가능.

## 결정 이력
- DEC-074 회원제 로그인(가입→관리자 승인, DB 역할, 투자자 탭 관리자 전용) / DEC-075 로컬 서버에도 로그인 적용(`scripts/setup_local_auth.py`) / DEC-076 "서버를 깨우는 중" 팝업 제거 / DEC-077 로그인 콜드스타트 재시도 / **DEC-078 웹+API 1개 서비스 통합**.
- 결과서: `docs/qa/2026-10-05-auth-redesign-test-result.md`, `docs/qa/2026-10-06-unified-service-test-result.md`. 절차서: `docs/ops/unified-service-guide.md`.

## 사용자가 아직 해야 하는 것
1. 며칠 사용해 이상 없으면 Render의 `stock-analyzer-api`(Suspended) 삭제.
2. 내 PC 로컬 로그인: `git pull` → `py -3.12 scripts\setup_local_auth.py` → `scripts\start_local_api.ps1`, `npx next dev -p 4000` 재기동 (DEC-075, 아직 확인 못 받음).
3. (선택) GitHub Secrets `NEON_OWNER_URL`, `RENDER_DEPLOY_HOOK_WEB` 등록 시 푸시 자동 배포(현재는 Secrets 없어 건너뜀).

## 열린 항목
- (유료 전환으로 콜드스타트 이슈는 사라짐. DEC-077의 재시도는 Neon DB 자동 정지 대비로 유지.)
- Render 무료 512MB 안의 통합 서비스 메모리 실측(로컬 측정 약 245MB).
- 방문자 IP 속도제한이 전 사용자 1버킷(기존 한계, `FRONTEND_TRUSTED_PROXY_HOPS=0`).

## 시험 환경 메모
- 임시 PG: `/var/tmp/pgd2`(포트 5544, 소켓 /tmp/pgsock), 환경변수 `/tmp/claude-0/pgenv.sh`, 파이썬 3.12 venv `/var/tmp/venv312`. 새 컨테이너에서는 다시 만들어야 할 수 있음.
- 로그인 E2E: `python tests/e2e/login_stack.py [--unified]`(322건), 로컬 모드: `tests/e2e/local_mode_stack.py --mode on|off`.
- `pkill -f`/`pgrep -f`로 프로세스를 죽이면 도구 셸이 같이 죽는다(사용 금지, PID/프로세스 그룹으로).
