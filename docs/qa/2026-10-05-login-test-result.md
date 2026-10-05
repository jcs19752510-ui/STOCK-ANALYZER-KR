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
- 화면: `docs/qa/2026-10-05/login-360.png`, `login-1280.png`, `members-360.png`, `members-1280.png` (확인: 360px에서 머리글 줄바꿈은 nowrap으로 수정함(재촬영은 미수행)).

## 4. 미확인 / 미해결
1. Render·Neon 실서버에서의 동작(무료 CPU의 argon2 소요 시간, `onrender.com` 쿠키, 깨우기 지연 중 로그인) — 적용 후 절차서 §4에서 확인.
2. 다중 탭 동시 만료·갱신, 모바일 실기기, 접근성 도구(스크린리더) 실측 미수행(자동 점검 항목만 통과).
3. members 360px 표 머리글 줄바꿈 → `white-space: nowrap` 적용(스크린샷 재촬영 미수행).
4. 세션 즉시 무효화(서버 저장소) 없음 — 설계상 한계(절차서 §6).
5. VPS 경로(`deploy/db/init/01-roles.sh`)에 `auth_service` 미반영.
6. 선행 조건(내부 토큰·Neon 비밀번호 교체)은 사용자 수행 대기.
7. AI는 운영 배포·Neon 변경을 수행하지 않았다.

## 5. 추가: "아이디 저장" + 브라우저 비밀번호 관리자 연계 (DEC-069)
요구 "아이디/패스워드 자동저장"을 **아이디는 앱이 저장, 비밀번호는 브라우저·OS 비밀번호 관리자가 저장**하는 방식으로 구현했다. 앱이 비밀번호를 저장하지 않는 이유: JS가 읽을 수 있는 저장소(localStorage·쿠키)의 비밀번호는 XSS 한 번에 탈취되며, 서버는 argon2 해시만 갖고 있어 원문을 돌려줄 수도 없다. "자동 로그인(세션 연장)"은 만들지 않았고(8시간·5분 재확인 유지) 필요하면 별도 결정이다.

| 구분 | 건수 | 결과 |
|---|---|---|
| 단위 `check-auth.mjs` 신규 4건(저장·해제, 형식 불량·변조 값 삭제, 저장소 예외, 소스에 비밀번호 저장 경로 없음) | 22(전체 프런트 110) | 통과 |
| E2E 섹션 H 27건: 체크박스·라벨·안내·44px·가로 넘침·Tab 순서·스페이스·axe(360/1280), 성공 로그인 시 비밀번호 관리자 호출(아이디·비밀번호 전달, 응답 없어도 로그인 완료), 아이디만 저장·비밀번호는 localStorage/sessionStorage/cookie 어디에도 없음, 재방문 시 아이디 채움+비밀번호 칸 포커스, 해제 시 삭제, 실패 로그인은 저장·제안 안 함, 변조 저장값 무시·스크립트 미실행, 저장소 접근 불가·PasswordCredential 미지원 브라우저 | 27 | 통과 |
| E2E 전체(A–H) 1회 재실행 | 182 중 182 | 통과 |
| 회귀: tsc·eslint·금지표현 검사 | 오류 0 | 통과 |
화면: `docs/qa/2026-10-05/login-remember-360.png`.

미확인: 실제 Chrome/Edge/Safari/Firefox의 비밀번호 저장 창 표시(자동화 브라우저는 창이 없어 **API 호출 여부만** 확인), 모바일 실기기 자동완성, 비밀번호 관리자 앱(1Password 등) 연동. 사용자가 운영 적용 후 실제 브라우저에서 "비밀번호 저장" 제안이 뜨는지 확인해야 한다.
