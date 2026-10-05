# 로그인 기능 운영(Render + Neon) 적용 절차서 (DEC-067)

> 상태: **구현·내부 테스트 완료, 운영 미적용.** 이 문서는 사용자가 직접 수행한다(AI는 운영 배포를 하지 않는다).
> 순서를 바꾸지 않는다. 각 단계 끝의 "확인"을 통과해야 다음 단계로 간다.

## 0. 사전 조건 (반드시 먼저)
1. **내부 토큰 교체**: 채팅에 노출된 `PUBLIC_API_INTERNAL_TOKEN`은 폐기한다. 새 값 = 무작위 40자 이상.
   - PowerShell: `-join ((48..57)+(65..90)+(97..122) | Get-Random -Count 48 | % {[char]$_})`
2. **Neon 비밀번호 교체**: owner, `api_service`, `batch_worker` 비밀번호를 Neon 콘솔에서 재설정하고 Render의 `PUBLIC_API_DATABASE_URL`(및 PC 배치 연결)을 갱신한다.
3. `SESSION_SECRET` 새로 생성(32자 이상 무작위). 바꾸면 모든 회원이 로그아웃된다.

## 1. DB 준비 (Neon, 소유자 연결, PC에서)
1. `deploy/render/neon-auth-setup.sql` 실행: `psql "<owner 접속문자열>" -v auth='<auth_service 새 비밀번호>' -f deploy/render/neon-auth-setup.sql`
2. 마이그레이션: `alembic upgrade head` (0015 적용 — `auth` 스키마, `app_users`, `login_audit`)
3. 확인: `python scripts/manage_users.py check` → 모든 줄 `OK` (환경변수 `AUTH_ADMIN_DATABASE_URL`=owner 연결)

## 2. 회원 추가 (관리자 스크립트)
- `python scripts/manage_users.py add kim --name 김철수` → 비밀번호는 숨김 입력(12자 이상, 아이디와 같으면 거부).
- 그 외: `list`, `set-password`, `disable`/`enable`, `unlock`, `delete`, `audit --limit 20`, `purge-audit --days 90`
- 비밀번호는 명령줄 인자로 넘기지 않는다(히스토리 노출 방지).

## 3. Render 환경변수
| 서비스 | 키 | 값 |
|---|---|---|
| API | `PUBLIC_API_INTERNAL_TOKEN` | 새 토큰 |
| API | `PUBLIC_API_AUTH_DATABASE_URL` | `postgresql+psycopg://auth_service:…@(직접 접속 주소)/neondb?sslmode=require` |
| API | `PUBLIC_API_REQUIRE_INTERNAL_TOKEN` | 처음엔 `false` |
| Web | `PUBLIC_API_INTERNAL_TOKEN` | API와 동일 |
| Web | `SESSION_SECRET` | 새 값 |
| Web | `NEXT_PUBLIC_BROWSER_API_BASE_URL` | `same-origin` |
| Web | `NEXT_PUBLIC_AUTH_ENABLED` | `true` (빌드 때 확정) |
| Web | `AUTH_REQUIRED` | 처음엔 `false` |

## 4. 배포 순서 (Manual Deploy)
1. **API 먼저** 배포(`REQUIRE_INTERNAL_TOKEN=false` 상태) → 확인: 사이트 정상 동작.
2. **Web 배포**(`AUTH_REQUIRED=false`) → 확인: 사이트 정상 동작(로그인 없이).
3. API `PUBLIC_API_REQUIRE_INTERNAL_TOKEN=true` 저장 → API 재배포 → 확인: 브라우저 주소창에 API 주소 직접 열면 401.
4. Web `AUTH_REQUIRED=true` 저장 → 재시작 → 확인: 주소 접속 시 `/login`, 회원 로그인 성공, 홈 표시, 회원 목록, 로그아웃.
5. 확인 시 시크릿 창으로 잘못된 비밀번호 5회 → 잠금 안내가 뜨는지(해제는 `unlock`).

## 5. 롤백 (1분)
`AUTH_REQUIRED=false`(Web) + `PUBLIC_API_REQUIRE_INTERNAL_TOKEN=false`(API) 저장 후 재시작. DB 객체는 그대로 둬도 무해.

## 6. 알려진 한계 (정직한 기록)
- 세션은 서명 쿠키(서버 저장소 없음): 로그아웃은 브라우저 쿠키만 지운다. 탈취된 쿠키는 만료(8시간) 또는 5분 주기 상태 재확인(비활성/삭제 회원)으로 차단된다. 즉시 전체 무효화는 `SESSION_SECRET` 교체.
- `FRONTEND_TRUSTED_PROXY_HOPS=0`이면 감사 기록의 IP가 비어 있을 수 있다(Render 프록시 구조 확인 후 조정).
- 로그인 시도 한도(키당 분당 10, 전체 30)는 공격 시 정상 회원 로그인을 일시 방해할 수 있다(DoS 트레이드오프, 잠금과 별개).
- 무료 CPU에서 argon2 시간, `onrender.com` 서브도메인 쿠키 동작은 실서버에서 미확인 → 적용 후 §4-4에서 확인.
- VPS용 `deploy/db/init/01-roles.sh`에는 `auth_service`가 아직 없다(VPS 경로 적용 시 추가 필요).

## 7. 소유자 전용 투자자 수급 (DEC-068) — 로그인 적용 후에 진행
공개 서버에는 증권사 앱키를 넣지 않는다. 소유자 PC가 수집해 Neon에 올리고, **소유자 아이디로 로그인했을 때만** 표가 보인다(다른 회원은 "준비 중").
1. DB: `alembic upgrade head`(0016 `investor_flow_daily` 생성, `api_service`는 SELECT만).
2. Render 환경변수: API `PUBLIC_API_OWNER_USERNAME`=소유자 아이디, Web `OWNER_USERNAME`=같은 값 → 둘 다 재시작(웹은 환경변수만이므로 재빌드 불필요).
3. 수집(소유자 PC, PowerShell): **`.env`를 고치지 말고** 그 창에서만 Neon 배치 계정을 지정한다.
   ```
   $env:BATCH_DATABASE_URL="postgresql+psycopg://batch_worker:비밀번호@(Neon 직접 접속 주소)/neondb?sslmode=require"
   py -3.12 scripts/collect_investor_flow.py --codes 005930,000660   # 먼저 소수로 검증
   py -3.12 scripts/collect_investor_flow.py                         # 전 종목(호출 약 2,800회, 수 분)
   ```
   KIS_APP_KEY/KIS_APP_SECRET은 PC `.env`의 기존 값을 쓴다. 장 마감 후(20시 이후) 하루 한 번.
4. 확인: 소유자로 로그인 → 종목 상세 → 투자자 탭에 표. 다른 회원으로는 "준비 중". 값은 **증권사 앱 화면과 반드시 대조**(단위·부호 미확인, DEC-054).
5. 되돌리기: 두 환경변수를 비우면 모두 "준비 중". 데이터는 남아 있어도 노출되지 않는다.

## 8. 배포 실패 사례와 점검 (2026-10-05)
- 증상: Render `stock-analyzer-web` 배포가 "Timed out after waiting for internal health check … /login"으로 15분 만에 실패. 서버는 정상 기동(`Ready`)했지만 검사 경로 `/login`이 **배포한 커밋(154fe68, 로그인 구현 전)에 없었다**.
- 원인: Blueprint(`render.yaml`)가 최신 설정(`healthCheckPath: /login`)을 서비스에 동기화했는데, 배포한 코드는 옛 커밋이었다. 설정과 코드 버전이 어긋남.
- 영향: 배포 실패 시 Render는 **이전에 성공한 버전을 계속 서비스**한다(운영은 중단되지 않음, 화면의 "Deploy failed"는 새 배포만 실패).
- 조치: 상태 검사를 어떤 화면에도 의존하지 않는 `/healthz`(항상 200)로 바꿨다. **최신 커밋(PROD_SCH 맨 위)으로 Manual Deploy → "Deploy latest commit"** 을 하면 된다. 옛 커밋을 다시 배포하면 `/healthz`가 없어 또 실패한다.
