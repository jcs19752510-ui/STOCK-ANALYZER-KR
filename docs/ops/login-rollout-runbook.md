# 로그인·소유자 투자자 수급 운영(Render + Neon) 적용 절차서 (DEC-067~071)

> 상태: **구현·내부 테스트 완료, 운영 미적용.** 사용자가 직접 수행한다(AI는 운영 배포·Neon 변경을 하지 않는다).
> 모든 명령은 **PC의 PowerShell, 프로젝트 폴더(`C:\big21\vibe-coding\STOCK-ANALYZER-KR`)** 에서 실행한다.
> 비밀값(비밀번호·토큰)은 `Read-Host`로 **입력창에 직접 입력**한다(명령 안의 글자를 고칠 필요 없음, 채팅·메모장·저장소에 붙이지 않는다).
> 각 단계 끝의 **확인**을 통과해야 다음 단계로 간다. 이상하면 **멈추고** 화면(비밀값 제외)을 알려 준다.

## 적용 순서 한눈에
| 단계 | 내용 | 운영 영향 |
|---|---|---|
| 0 | 점검(자동 배포 여부, 최신 코드, 도구) | 없음 |
| 1 | 비밀값 새로 만들기 + Neon 비밀번호 교체 | Render·GitHub 값 갱신 필요 |
| 2 | DB 준비(0015~0017, `auth_service`, 권한 점검) | 없음(표만 추가) |
| 3 | 회원 등록 | 없음 |
| 4 | Render에 **최신 코드 배포(로그인은 꺼진 채)** | 사이트는 지금과 동일해야 함 |
| 5 | 로그인 켜기(API 설정 → 웹 설정·재빌드 → API 강제) | **로그인 필요해짐** |
| 6 | 확인 체크리스트 | — |
| 7 | 소유자 투자자 수급 수집 | 소유자만 표 확인 |
| 8 | 되돌리기 | — |

## 0. 점검
1. **GitHub 자동 배포 여부 확인.** 저장소 → **Actions → render-deploy**. `Secrets not set … deploy skipped`이면 자동 배포 없음. 성공 기록이 있으면 **PROD_SCH 푸시마다 이미 Neon 마이그레이션이 적용되고 Render 배포 요청이 나갔을 수 있다**(그 경우 2단계 `alembic current`가 이미 `0017`이고, 4단계 배포도 이미 끝났을 수 있다 — 그대로 확인만 하면 된다).
2. 최신 코드 받기와 도구 설치(내 PC에 로컬 변경이 있으면 `git status` 결과를 먼저 알려 줄 것 — **`git push`는 하지 않는다**):
   ```powershell
   git status --short
   git pull origin PROD_SCH
   py -3.12 -m pip install -r requirements.txt
   ```
   `git pull`이 병합 편집 화면(vim)을 띄우면 `:wq` + Enter. 충돌이 나면 멈추고 알려 줄 것.
3. 입력 도우미(이 PowerShell 창에서 **한 번만** 붙여 넣기, 창을 닫으면 다시):
   ```powershell
   function Ask($label){ $s = Read-Host $label -AsSecureString; [Net.NetworkCredential]::new('', $s).Password }
   function NewSecret($n){ $b = New-Object byte[] 64; [Security.Cryptography.RNGCryptoServiceProvider]::new().GetBytes($b); ([Convert]::ToBase64String($b) -replace '[^A-Za-z0-9]','').Substring(0,$n) }
   $NEON_HOST = Read-Host "Neon 직접 주소 호스트만(예 ep-xxxx.ap-southeast-1.aws.neon.tech, -pooler 없는 것)"
   $API = Read-Host "API 서비스 주소(https://로 시작, 끝에 / 없이)"
   $WEB = Read-Host "웹 서비스 주소(https://로 시작, 끝에 / 없이)"
   ```
4. **확인**: `docker ps`에 `stock-screener-pg`가 보이고, 브라우저에서 `$WEB`이 지금처럼 열린다.

## 1. 비밀값 새로 만들기 + Neon 비밀번호 교체 (필수 — 채팅에 노출된 값을 폐기)
1. 새 값 4개 생성(화면에 나온 값을 **메모장에 임시 보관**, 끝나면 삭제):
   ```powershell
   $TOKEN = NewSecret 48      # 내부 토큰: API·웹 같은 값
   $SESSION = NewSecret 48    # 세션 서명키: 웹만
   $AUTH_PW = NewSecret 32    # auth_service 계정 비밀번호
   $BAT_PW = NewSecret 32; $API_PW = NewSecret 32   # batch_worker / api_service 새 비밀번호
   "TOKEN=$TOKEN"; "SESSION=$SESSION"; "AUTH_PW=$AUTH_PW"; "BAT_PW=$BAT_PW"; "API_PW=$API_PW"
   ```
2. **Neon 소유자 비밀번호 재설정**: Neon 콘솔 → 프로젝트 → 해당 브랜치의 **Roles & Databases** → `neondb_owner` → **Reset password**(메뉴 이름은 화면과 조금 다를 수 있음). 새 비밀번호를 복사해서:
   ```powershell
   $OWNER_PW = Ask "Neon 소유자(neondb_owner) 새 비밀번호"
   $OWNER = "postgresql://neondb_owner:$OWNER_PW@$NEON_HOST/neondb?sslmode=require"
   $env:ALEMBIC_DATABASE_URL = "postgresql+psycopg://neondb_owner:$OWNER_PW@$NEON_HOST/neondb?sslmode=require"
   $env:AUTH_ADMIN_DATABASE_URL = $env:ALEMBIC_DATABASE_URL
   ```
3. `batch_worker`·`api_service` 비밀번호를 새 값으로 바꾼다(여러 번 실행해도 안전, 비밀번호만 갱신):
   ```powershell
   docker cp deploy\render\neon-setup.sql stock-screener-pg:/tmp/neon-setup.sql
   docker exec stock-screener-pg psql "$OWNER" -v ON_ERROR_STOP=1 -v bat=$BAT_PW -v api=$API_PW -f /tmp/neon-setup.sql
   ```
4. 새 비밀번호를 쓰는 곳을 **모두** 갱신한다(안 하면 해당 기능이 접속 실패):
   | 곳 | 항목 | 새 값 |
   |---|---|---|
   | GitHub → Settings → Secrets → Actions | `NEON_OWNER_URL` | `postgresql+psycopg://neondb_owner:새소유자비번@호스트/neondb?sslmode=require` |
   | 〃 | `BATCH_DATABASE_URL` | `postgresql+psycopg://batch_worker:BAT_PW@호스트/neondb?sslmode=require` |
   | Render → API → Environment | `PUBLIC_API_DATABASE_URL` | `postgresql+psycopg://api_service:API_PW@호스트/neondb?sslmode=require` |
   | PC `.env` | `BATCH_DATABASE_URL`(Neon을 가리키고 있다면) | batch_worker 새 URL |
   (표의 `새소유자비번`·`BAT_PW`·`API_PW`는 위 1~2에서 만든 **실제 값**으로 바꿔 넣는다.)
5. **확인**: 임시로 `docker exec stock-screener-pg psql "$OWNER" -c "select 1"` 가 `1`을 돌려준다.

## 2. DB 준비 (Neon, 소유자 연결)
1. 마이그레이션 상태 확인·적용:
   ```powershell
   py -3.12 -m alembic current
   py -3.12 -m alembic upgrade head
   py -3.12 -m alembic current
   ```
   **확인**: 마지막 출력이 `0017 (head)`. (0015 `auth` 스키마·회원표·로그인 기록, 0016 투자자 수급 표, 0017 서버 쪽 세션표)
2. 로그인 전용 DB 계정 `auth_service` 만들기 + 권한(여러 번 실행해도 안전):
   ```powershell
   docker cp deploy\render\neon-auth-setup.sql stock-screener-pg:/tmp/neon-auth-setup.sql
   docker exec stock-screener-pg psql "$OWNER" -v ON_ERROR_STOP=1 -v auth=$AUTH_PW -f /tmp/neon-auth-setup.sql
   ```
3. 권한 점검:
   ```powershell
   py -3.12 scripts/manage_users.py check
   ```
   **확인**: 모든 줄이 `OK`(하나라도 `FAIL`이면 멈추고 알려 줄 것).

## 3. 회원 등록 (관리자 스크립트, 가입 화면 없음)
```powershell
py -3.12 scripts/manage_users.py add jcs1973 --name "표시할 이름"
```
- 비밀번호는 **숨김 입력창**에 직접 입력(두 번). **8자 이상**, 아이디와 달라야 하고 흔한 비밀번호는 거부된다. 채팅에 노출된 비밀번호는 쓰지 말 것.
- 다른 회원도 같은 방식으로 추가. 확인: `py -3.12 scripts/manage_users.py list`
- 이후 관리: `set-password`(그 회원 전 기기 로그아웃), `disable`/`enable`, `unlock`, `delete`, `audit --limit 20`, `purge-audit --days 90`, `sessions`, `revoke-sessions <아이디>`(분실·탈취 대응 — 전 기기 즉시 취소), `purge-sessions --days 7`(월 1회).

## 4. Render에 최신 코드 배포 — 로그인은 **꺼진 채** (사이트가 지금과 같아야 정상)
1. Render → `stock-analyzer-api` → **Manual Deploy → Deploy latest commit**. 끝나면 **확인**:
   ```powershell
   curl.exe -s -o NUL -w "%{http_code}`n" "$API/api/v1/live"      # 200
   ```
2. Render → `stock-analyzer-web` → **Manual Deploy → Deploy latest commit**(꼭 *latest*. 옛 커밋은 `/healthz`가 없어 실패한다).
   - Blueprint 동기화가 새 환경변수(`AUTH_REQUIRED` 등)의 값을 묻거나 빈 칸으로 보이면 **지금은 비워 둔다**(비어 있으면 로그인 꺼짐).
   - **확인**:
     ```powershell
     curl.exe -s -o NUL -w "%{http_code}`n" "$WEB/healthz"    # 200
     curl.exe -s -o NUL -w "%{http_code}`n" "$WEB/"           # 200 (로그인 없이 홈이 그대로 열림)
     ```
     브라우저에서 홈·조건 스크리닝·종목 상세가 **지금과 똑같이** 동작해야 한다. 아니면 멈추고 알려 줄 것.

## 5. 로그인 켜기 — **이 순서 그대로**
> `NEXT_PUBLIC_*` 값은 웹을 **다시 빌드**할 때만 바뀐다. 로그인이 꺼진 상태에서는 `NEXT_PUBLIC_BROWSER_API_BASE_URL=same-origin`을 넣지 말 것(브라우저의 API 호출이 막힌다). 아래 5-2에서 한꺼번에 켠다.

**5-1. API 먼저 설정(아직 강제하지 않음)** — Render → API → Environment 에 추가·수정 후 저장(재배포 선택):
| 키 | 값 |
|---|---|
| `PUBLIC_API_INTERNAL_TOKEN` | 1단계 `TOKEN` |
| `PUBLIC_API_AUTH_DATABASE_URL` | `postgresql+psycopg://auth_service:AUTH_PW@호스트/neondb?sslmode=require` |
| `PUBLIC_API_OWNER_USERNAME` | `jcs1973,jcs1975`(투자자 수급을 볼 수 있는 계정들, 쉼표로 구분) |
| `PUBLIC_API_REQUIRE_INTERNAL_TOKEN` | `false`(비워 둬도 됨) |
**확인**: API 배포 성공(`$API/api/v1/live` 200), 사이트 정상.

**5-2. 웹 설정 + 재빌드** — Render → Web → Environment 에 추가·수정, **"Save, rebuild, and deploy"**:
| 키 | 값 |
|---|---|
| `PUBLIC_API_INTERNAL_TOKEN` | 1단계 `TOKEN`(API와 동일) |
| `SESSION_SECRET` | 1단계 `SESSION` |
| `OWNER_USERNAME` | `jcs1973,jcs1975`(API의 `PUBLIC_API_OWNER_USERNAME`과 동일) |
| `NEXT_PUBLIC_BROWSER_API_BASE_URL` | `same-origin` |
| `NEXT_PUBLIC_AUTH_ENABLED` | `true` |
| `AUTH_REQUIRED` | `true` |
**확인**:
```powershell
curl.exe -s -o NUL -w "%{http_code}`n" "$WEB/healthz"      # 200
curl.exe -s -o NUL -w "%{http_code}`n" "$WEB/login"        # 200
curl.exe -s -o NUL -w "%{http_code}`n" "$WEB/"             # 307 (로그인 화면으로 이동)
```
브라우저(시크릿 창): `$WEB` → 로그인 화면 → 3단계에서 만든 계정으로 로그인 → 홈 표시.
**배포가 실패하거나 503("설정 오류")이면**: 환경변수 오타(`SESSION_SECRET`·토큰 32자 이상, `same-origin` 철자)를 확인하고, 급하면 8단계로 되돌린다.

**5-3. API에서 내부 토큰 강제** — Render → API → `PUBLIC_API_REQUIRE_INTERNAL_TOKEN` = `true` 저장(재배포).
**확인**:
```powershell
curl.exe -s -o NUL -w "%{http_code}`n" "$API/api/v1/market-summary"   # 401 (브라우저·외부에서 API 직접 호출 차단)
curl.exe -s -o NUL -w "%{http_code}`n" "$API/api/v1/live"             # 200 (헬스체크는 열려 있음)
```
다시 브라우저에서 로그인 후 홈·조건 스크리닝·종목 상세가 정상이어야 한다.

## 6. 확인 체크리스트
- [ ] 비로그인으로 `$WEB/stocks`, `$WEB/members` → 로그인 화면으로 이동
- [ ] 로그인 성공 → 홈, "○○○님 · 회원 목록 · 로그아웃 · 모든 기기에서 로그아웃" 메뉴
- [ ] 틀린 비밀번호 5회 → 잠금 안내(풀기: `manage_users.py unlock jcs1973`)
- [ ] 회원 목록에 아이디·이름만 표시
- [ ] "아이디 저장"·"로그인 상태 유지(30일)" 체크박스, 브라우저 "비밀번호 저장" 제안이 뜨는지(자동화 시험으로는 창 표시를 확인하지 못함)
- [ ] 로그아웃 → 로그인 화면, "모든 기기에서 로그아웃" → 확인창 → 로그인 화면
- [ ] 15분 이상 쉰 뒤(서버 잠듦) 접속하면 "서버를 깨우는 중" 팝업이 나오고 이후 정상
- [ ] 첫 로그인이 느리면(무료 CPU의 비밀번호 검증) 대기 팝업 후 성공하는지

## 7. 소유자 전용 투자자 수급 (DEC-068)
공개 서버에는 증권사 앱키를 넣지 않는다. 소유자 PC가 수집해 Neon에 올리고 **소유자 아이디로 로그인했을 때만** 표가 보인다(다른 회원은 "준비 중").
1. 수집(소수 종목으로 먼저). 증권사 앱키(`KIS_APP_KEY`·`KIS_APP_SECRET`)는 프로젝트 `.env`에서 **그 두 개만** 자동으로 읽는다(`.env`의 DB 주소는 읽지 않음 — Neon 주소는 아래처럼 직접 지정):
   ```powershell
   $env:BATCH_DATABASE_URL = "postgresql+psycopg://batch_worker:$BAT_PW@$NEON_HOST/neondb?sslmode=require"
   py -3.12 scripts/collect_investor_flow.py --codes 005930,000660
   ```
   `[완료] … 오류 0건`이면 성공. `KIS_APP_KEY … 설정되지 않았습니다`면 `.env`에 두 값이 있는지 확인.
2. **값 대조(필수)**: 증권사 앱의 같은 종목·같은 날짜 개인/외국인/기관 순매수와 비교한다(단위: 수량 주, 대금 백만원, 부호 ▲순매수 ▼순매도 — 실제 KIS 응답은 이 환경에서 확인하지 못함).
   ```powershell
   docker exec stock-screener-pg psql "$OWNER" -c "select * from public_serving.investor_flow_daily where stock_code='005930' order by trade_date desc limit 5"
   ```
3. 브라우저: 소유자(`jcs1973`)로 로그인 → 종목 상세 → **투자자** 탭에 표. 다른 회원으로 로그인하면 "준비 중".
4. 전 종목 수집(호출 약 2,800회, 수 분): `py -3.12 scripts/collect_investor_flow.py` — 장 마감 후(**KST 20시 이후**) 하루 한 번(당일 행은 20시 이전에는 적재하지 않음, 확정 시각은 미확인). 연속 20회 실패하면 스스로 중단한다.
5. 끄기: 두 환경변수(`PUBLIC_API_OWNER_USERNAME`, `OWNER_USERNAME`)를 비우면 모두 "준비 중".

## 8. 되돌리기 (1분)
- 로그인만 끄기: Web `AUTH_REQUIRED` = `false` 저장(재시작) + API `PUBLIC_API_REQUIRE_INTERNAL_TOKEN` = `false`. **단, 웹을 `same-origin`으로 빌드했다면 브라우저의 API 호출이 막히므로** `NEXT_PUBLIC_BROWSER_API_BASE_URL`을 비우고 `NEXT_PUBLIC_AUTH_ENABLED`를 `false`로 한 뒤 **재빌드**("Save, rebuild, and deploy")해야 완전히 이전 상태가 된다.
- DB 객체(`auth` 스키마, `investor_flow_daily`)는 남겨 둬도 무해하다.
- 배포 자체가 실패하면 Render는 **이전 성공 버전을 계속 서비스**한다(운영은 중단되지 않는다).

## 9. 운영 메모와 알려진 한계
- **세션**: 기본 8시간, "로그인 상태 유지(30일)"를 켠 기기만 30일(절대 만료). 5분마다 서버가 세션 취소 여부·회원 활성 여부를 확인한다. 이번 적용 후 **모든 회원이 한 번 다시 로그인**해야 한다.
- **반영 지연**: 로그아웃·비활성화·세션 취소는 서버에 즉시 기록되나, 이미 복사된 쿠키는 **최대 5분** 통과한다. 로그아웃 때 API가 잠들어 있으면 서버 취소가 실패할 수 있다(쿠키는 지워짐) → 의심되면 `revoke-sessions <아이디>`.
- **"모든 기기에서 로그아웃"**: 서버 취소가 확인되지 않으면 오류 안내와 함께 로그인이 유지되니 다시 누른다.
- 방문자 IP: `FRONTEND_TRUSTED_PROXY_HOPS=0`이면 로그인 기록의 접속 주소가 비고, 로그인 시도 한도는 **전체 공용**으로 센다(분당 30회). Render 프록시 구조 확인(`docs/ops/render-neon-guide.md` §7)이 끝나면 조정.
- 로그인 시도 한도(키당 분당 10, 전체 30)는 공격 시 정상 로그인을 일시 방해할 수 있다(잠금과 별개).
- 무료 CPU에서의 비밀번호 검증 시간, `onrender.com` 쿠키 동작, 실기기 재방문은 **실서버에서 확인 전**이다.
- VPS용 `deploy/db/init/01-roles.sh`에는 `auth_service`가 아직 없다(VPS 경로 적용 시 추가 필요).
- 이 절차서는 자동화 시험(임시 DB·임시 서버)으로 검증된 코드 기준이며 **실제 Render·Neon·KIS 환경에서 실행한 적은 없다.**

## 10. 막혔을 때 (증상 → 조치)
| 증상 | 원인·조치 |
|---|---|
| Render 웹 배포가 "health check … timed out" | 옛 커밋을 배포했거나 환경변수 오류. 상태 검사는 `/healthz`이며 **latest commit** 으로 다시 배포. 로그 아래쪽 오류 줄을 알려 줄 것 |
| 로그인 화면에서 "서버에 연결하지 못했습니다" | API가 잠들어 있거나 `PUBLIC_API_INTERNAL_TOKEN`이 API·웹에서 다름(32자 이상, 같은 값) |
| 모든 화면이 "서비스 설정 오류" | `SESSION_SECRET`/토큰이 32자 미만이거나 `NEXT_PUBLIC_BROWSER_API_BASE_URL`이 `same-origin`이 아님(빌드 값이므로 재빌드 필요) |
| 로그인은 되는데 조건 스크리닝이 비어 있음 | 웹이 `same-origin`으로 빌드되지 않았거나 API 강제(5-3) 전에 웹이 옛 빌드. 5-2 재빌드 확인 |
| `alembic upgrade`가 권한 오류 | 소유자 URL이 아님(`neondb_owner`) 또는 풀러 주소(`-pooler`) 사용. 직접 주소로 |
| `manage_users.py check`가 FAIL | `neon-auth-setup.sql`을 다시 실행(2-2) |
| 투자자 탭에 "불러오지 못했습니다" | 아직 수집 안 됨(7-1), 두 환경변수 불일치, 소유자 아이디 철자 |
