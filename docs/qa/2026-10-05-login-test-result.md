# 로그인 기능 내부 테스트 결과서 (DEC-067)

- 작성일: 2026-10-05 / 대상 커밋: 4205fb9(U1 DB·관리), 826ba2c(U2 API), c69c47d(U3 웹) 및 후속(purge-audit, render.yaml, 절차서)
- 범위: 회원가입 없음, 관리자가 넣은 회원만 로그인, 로그인 회원은 회원 목록(아이디·이름만) 조회, 운영(Render)만 적용, 로컬은 변경 없음.
- 설계서: `docs/harness/login-feature-design.md` / 적용 절차: `docs/ops/login-rollout-runbook.md`

## 1. 시험 환경 (정직한 기록)
임시 PostgreSQL 16(소켓 5544, 역할 migrator/batch_worker/api_service/auth_service) + Python 3.12 venv + 실제 FastAPI(포트 4321, 토큰 강제) + 실제 `next start`(포트 4322, 로그인 켬) + Playwright(chromium). **Render·Neon 실서버가 아니다.**

## 2. 결과 요약
| 구분 | 건수 | 결과 |
|---|---|---|
| 단위: 비밀번호 정책·argon2id (`test_auth_passwords`) | 52 | 통과 |
| 단위: 내부 토큰 강제 (`test_internal_token_enforcement`) | 26 | 통과 |
| 단위: 프런트 세션·리다이렉트·origin 등 (`check-auth.mjs`) | 16 | 통과 |
| 통합: auth 스키마·권한·관리 CLI (`test_auth_schema_db`) | 37 (purge-audit 1건 추가) | 통과 |
| 통합: 로그인/세션확인/회원목록 API (`test_auth_api_db`) | 27 | 통과 |
| E2E: 실제 API+웹+Playwright (`login-e2e.mjs`, A–F) | 142 | 통과 |
| 회귀: 백엔드 전체 `pytest tests` | 1033 통과·1 건너뜀 (purge 추가 전 기준, 추가 후 auth 스키마 37 통과) | 통과 |
| 회귀: 프런트 `node --test check-*.mjs` | 104 | 통과 |
| tsc / eslint / ruff | — | 오류 0 |

## 3. 검증된 보안 속성
- 미로그인: 모든 페이지 `/login` 이동(`next` 안전 경로만), `/api/*` 401, API 직접 호출은 내부 토큰 없으면 401, 문서/openapi 비활성.
- 쿠키 `__Host-session`: HttpOnly·Secure·SameSite=Lax·Path=/ , 변조·만료·형식오류·비활성 회원 쿠키 거부, 5분 초과 시 상태 재확인(`/auth/renew`).
- 로그인: 존재하지 않는 아이디와 틀린 비밀번호가 같은 응답·같은 처리(dummy_verify), 5회 실패 15분 잠금(배수 증가, 상한 24h), 원자적 UPDATE, 로그인 요청 한도, CSRF(Origin=Host) 검사, 열린 리다이렉트 차단.
- 최소 권한: `auth_service`는 `app_users` SELECT + 지정 컬럼 UPDATE + `login_audit` INSERT만. 회원 목록에 해시 미노출, XSS 문자열은 이스케이프되어 표시.
- 설정 오류(약한 시크릿·누락) 시 fail-closed 503.
- 화면: `docs/qa/2026-10-05/login-360.png`, `login-1280.png`, `members-360.png`, `members-1280.png` (확인: 360px에서 아이디 열 줄바꿈 발생 — 가독성 경미, 아래 미해결).

## 4. 미확인 / 미해결
1. Render·Neon 실서버에서의 동작(무료 CPU의 argon2 소요 시간, `onrender.com` 쿠키, 깨우기 지연 중 로그인) — 적용 후 절차서 §4에서 확인.
2. 다중 탭 동시 만료·갱신, 모바일 실기기, 접근성 도구(스크린리더) 실측 미수행(자동 점검 항목만 통과).
3. members 360px 표: "아이디" 머리글이 두 줄로 꺾임(`아이/디`). 기능 영향 없음, 표시 개선 후보.
4. 세션 즉시 무효화(서버 저장소) 없음 — 설계상 한계(절차서 §6).
5. VPS 경로(`deploy/db/init/01-roles.sh`)에 `auth_service` 미반영.
6. 선행 조건(내부 토큰·Neon 비밀번호 교체)은 사용자 수행 대기.
7. AI는 운영 배포·Neon 변경을 수행하지 않았다.
