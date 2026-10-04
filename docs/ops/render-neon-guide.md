# Render + Neon 무료 베타 배포 절차서 (DEC-063)

> 대상: 처음 해보는 사람. 순서대로 따라 하면 됩니다. 모르는 단계가 나오면 그 자리에서 멈추고 물어보세요.
> 이 절차서의 코드·스크립트는 모두 내부 시험을 마쳤지만, **Render·Neon 사이트에서 직접 해 봐야만 알 수 있는 부분**은 "⚠ 확인 필요"로 표시했습니다.
> 실제 운영 배포는 이 문서의 모든 단계를 끝내고 마지막 "공개 전 점검표"가 통과한 뒤에만 합니다.

## 0. 큰 그림

```
방문자 ─▶ Render 웹(Next.js) ─▶ Render API(FastAPI) ─▶ Neon DB(PostgreSQL)
                                                          ▲
        내 PC(작업 스케줄러, 주) ── 배치(수집·가공) ────────┤
        GitHub Actions(보조) ───── 배치 ───────────────────┘
GitHub PROD_SCH 푸시 ─▶ Actions: 백업 → DB 변경(마이그레이션) → Render에 배포 요청
```

| 항목 | 내용 |
|---|---|
| 비용 | Render 무료 + Neon 무료 + GitHub(비공개 저장소는 월 2,000분 무료) + Cloudflare R2 백업(소량 무료). 가격/한도는 검색 결과 기준이라 **가입 화면에서 직접 확인**하세요. |
| 한계 | 15분 동안 접속이 없으면 서버가 잠듭니다. 첫 접속은 약 1분 걸립니다. "서버를 깨우는 중" 안내는 **브라우저가 API를 부르는 요청이 4.5초 넘게 걸릴 때만** 뜹니다. 웹 서비스 자체가 잠든 첫 접속은 안내 없이 대기하며, 서버에서 API를 부르는 화면(홈, 종목 상세 첫 화면)은 응답이 올 때까지 빈 화면이거나 "일시적인 오류"가 날 수 있습니다(결과서 2026-10-04 F-8). DB(Neon)도 5분 유휴 시 잠듭니다. |
| 주소 | DuckDNS 도메인은 사용할 수 없습니다(CNAME 불가). `xxxx.onrender.com` 주소를 씁니다. |
| 데이터 | 163MB(월 +35~45MB 추정). Neon 무료 용량(0.5GB로 알려짐, ⚠ 확인 필요)을 넘기 전에 정리 방침을 정해야 합니다(결정: 지금은 정리 안 함). |

**공개 전 반드시 지킬 것**: §7의 프록시 대역 확인이 끝나기 전에는 주소를 남에게 알리지 않습니다(기동 거부 장치가 이를 돕습니다).

## 1. Neon 프로젝트 만들기

1. https://neon.tech 가입(GitHub 계정으로 가능).
2. **Create project** → 이름 `stock-analyzer-kr`, **리전: AWS Asia Pacific (Singapore)**. 한국에 가장 가까운 곳이며 Render 싱가포르와 같은 지역이라 빠릅니다. 생성 화면에는 버전 선택이 없고 **Postgres 18**로 만들어집니다(2026-10-04 확인). 그래서 GitHub Actions 백업 도구도 18로 맞춰 두었습니다(`deploy/render/install-pg-client.sh`). ⚠ 18 서버로 `pg_dump`가 도는지는 첫 백업 실행에서 확인합니다. 또 18 도구로 뜬 백업은 **16 이하 `pg_restore`로는 열리지 않을 수 있으니**, VPS로 되돌릴 때는 복원 도구도 18을 쓰세요.
3. 만들어지면 **Connection details**가 나옵니다. 주소가 두 종류입니다.
   - **직접(Direct) 주소**: 호스트에 `-pooler`가 **없음** → 우리는 이것만 씁니다(마이그레이션, 배치 잠금, 시간제한 옵션이 모두 이 주소에서 동작).
   - 풀러(Pooled) 주소: 호스트에 `-pooler`가 있음 → **쓰지 않습니다**. (스크립트가 풀러 주소를 넣으면 거부합니다.)
   - Neon 화면의 "Connection pooling" 스위치를 끄면 직접 주소가 보입니다.
4. 소유자 계정(보통 `neondb_owner`)의 접속 문자열을 복사해 메모장에 둡니다(저장소·채팅에 붙이지 마세요).
   형태: `postgresql://neondb_owner:비밀번호@ep-xxxx.ap-southeast-1.aws.neon.tech/neondb?sslmode=require`

> 이 서비스에서 쓰는 형태는 앞부분이 `postgresql+psycopg://` 입니다. 아래에서 `postgresql://` → `postgresql+psycopg://` 로만 바꿔 쓰세요.

## 2. 앱 전용 계정(역할) 만들기 — 내 PC에서

앱이 쓰는 계정은 둘입니다: `batch_worker`(배치), `api_service`(공개 API, 읽기 전용·원본 테이블 접근 불가). 비밀번호 2개를 영문+숫자로 길게(24자 이상) 만들어 메모하세요.

PowerShell(프로젝트 폴더 `C:\big21\vibe-coding\STOCK-ANALYZER-KR`)에서, 이미 실행 중인 DB 컨테이너 `stock-screener-pg`의 psql을 빌려 씁니다.

```powershell
docker cp deploy\render\neon-setup.sql stock-screener-pg:/tmp/neon-setup.sql
docker exec stock-screener-pg psql "postgresql://neondb_owner:소유자비번@ep-xxxx.ap-southeast-1.aws.neon.tech/neondb?sslmode=require" -v ON_ERROR_STOP=1 -v bat=배치용비번 -v api=API용비번 -f /tmp/neon-setup.sql
```

성공하면 오류 없이 끝납니다. 여러 번 실행해도 안전합니다(비밀번호만 갱신).

## 3. 테이블 만들기 + 내 PC 데이터 옮기기

순서가 중요합니다: **계정(§2) → 복원 → 마이그레이션 확인**.

```powershell
docker cp C:\stock-dump\stock.dump stock-screener-pg:/tmp/stock.dump
docker exec stock-screener-pg pg_restore --no-owner --exit-on-error -d "postgresql://neondb_owner:소유자비번@ep-xxxx.ap-southeast-1.aws.neon.tech/neondb?sslmode=require" /tmp/stock.dump
```

- `--no-owner`: 옛 소유자(migrator)를 Neon 소유자로 바꿔 복원합니다. 권한(batch_worker/api_service)은 덤프 안의 GRANT로 그대로 복원됩니다(시험 확인).
- 중간에 오류가 나면 즉시 멈추므로(`--exit-on-error`) 반쯤 들어간 채로 넘어가지 않습니다. 오류가 나면 Neon 화면에서 데이터베이스를 지우고 다시 만든 뒤 §2부터 다시 하세요.
- 덤프는 최신 데이터가 아닐 수 있습니다. 공개 직전에 PC에서 새로 덤프(`pg_dump -Fc`)해 다시 올리는 것을 권장합니다. PER/PBR 수집이 끝난 뒤가 가장 좋습니다.

확인(PC 프로젝트 폴더, `.env`는 건드리지 않고 변수만 임시 지정):

```powershell
$env:ALEMBIC_DATABASE_URL="postgresql+psycopg://neondb_owner:소유자비번@ep-xxxx.ap-southeast-1.aws.neon.tech/neondb?sslmode=require"
python -m alembic current      # 0014 (head) 가 나와야 함
python -m alembic upgrade head # 이미 최신이면 아무 일도 안 함
```

## 4. GitHub Secrets 넣기

저장소 → **Settings → Secrets and variables → Actions → New repository secret**

| 이름 | 값 | 필수 |
|---|---|---|
| `NEON_OWNER_URL` | `postgresql+psycopg://neondb_owner:소유자비번@…neon.tech/neondb?sslmode=require` (직접 주소) | 배포·백업 |
| `BATCH_DATABASE_URL` | `postgresql+psycopg://batch_worker:배치용비번@…neon.tech/neondb?sslmode=require` | 보조 배치 |
| `GOV_DATA_PORTAL_SERVICE_KEY` | 공공데이터포털 키(**재발급한 새 키**) | 보조 배치 |
| `DART_API_KEY` | DART 키(**재발급한 새 키**) | 보조 배치 |
| `DATA_FRESHNESS_WEBHOOK_URL` | 알림 웹훅 주소 | 선택 |
| `RENDER_DEPLOY_HOOK_API`, `RENDER_DEPLOY_HOOK_WEB` | §5에서 복사 | 배포 |
| `AGE_RECIPIENT`, `R2_BUCKET`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_ENDPOINT` | R2 백업 5종(**전부 넣거나 전부 비움**) | 백업 |

- 아직 없는 Secret이 있으면 워크플로는 **실패하지 않고 "건너뜀"** 으로 끝납니다.
- R2 5종을 비우면 배포 전 백업이 생략됩니다(Neon의 6시간 이력만 안전망). 공개 전에는 R2 설정을 권장합니다(`docs/ops/oracle-deploy-guide.md`의 R2·age 키 만들기 단계를 그대로 사용).
- ⚠ 확인 필요: 미국에 있는 GitHub 실행기에서 공공데이터포털/DART에 접속되는지는 **직접 한 번 돌려 봐야** 압니다(§9-4).

## 5. Render에 올리기

1. https://render.com 가입 → **New → Blueprint** → GitHub 저장소 연결 → 브랜치 `PROD_SCH` 선택. 저장소의 `render.yaml`을 읽어 서비스 2개(`stock-analyzer-api`, `stock-analyzer-web`)를 만듭니다.
2. 값 입력 화면이 나옵니다(비밀값은 저장소에 없고 여기서 직접 입력).

   **API 서비스**

   | 키 | 넣을 값 |
   |---|---|
   | `PUBLIC_API_DATABASE_URL` | `postgresql+psycopg://api_service:API용비번@…neon.tech/neondb?sslmode=require` (직접 주소) |
   | `PUBLIC_API_CORS_ALLOWED_ORIGINS` | 웹 서비스 주소 `https://stock-analyzer-web.onrender.com` (실제 주소를 만든 뒤 확인) |
   | `PUBLIC_API_INTERNAL_TOKEN` | 긴 무작위 문자열(웹과 **같은 값**) |
   | `PUBLIC_API_TRUSTED_PROXY_IPS` | 지금은 **비워 둠**(§7에서 채움) |
   | `PUBLIC_API_REQUIRE_TRUSTED_PROXY` | 지금은 `false` (§7 끝나면 `true`) |
   | `PUBLIC_API_LOG_PEER_IPS` | 지금은 `1` (§7 끝나면 삭제) |

   **웹 서비스**

   | 키 | 넣을 값 |
   |---|---|
   | `NEXT_PUBLIC_API_BASE_URL` | API 서비스 주소 `https://stock-analyzer-api.onrender.com` |
   | `PUBLIC_API_INTERNAL_TOKEN` | API와 같은 값 |

   서비스 이름이 이미 쓰이고 있으면 주소 뒤에 숫자가 붙을 수 있습니다. 만든 뒤 실제 주소를 보고 위 값을 고치세요.
   ⚠ 확인 필요: Render가 화면에 입력한 `NEXT_PUBLIC_API_BASE_URL`을 Docker **빌드 때** 전달하는지(전달돼야 브라우저 코드에 들어갑니다). 안 되면 알려주세요 — 빌드 인자 방식으로 바꿉니다.
3. 두 서비스 모두 **Settings → Deploy Hook** 주소를 복사해 GitHub Secrets `RENDER_DEPLOY_HOOK_API/WEB`에 넣습니다. `render.yaml`에서 코드 푸시 자동 배포는 꺼 두었으므로(`autoDeployTrigger: off`), 배포는 항상 "백업 → DB 변경 → 배포 요청" 순서로만 일어납니다.
4. 첫 배포가 끝나면 API 로그에 `PEER-DIAG` 줄이 보이기 시작합니다(§7).

## 6. 내 PC 배치를 Neon으로 향하게 하기 (주 실행)

PC `.env`의 `BATCH_DATABASE_URL`을 Neon의 batch_worker 직접 주소로 바꿉니다.
`postgresql+psycopg://batch_worker:배치용비번@…neon.tech/neondb?sslmode=require`
- 기존 로컬 DB를 쓰던 개발 작업과 섞이지 않도록, 바꾸기 전 `.env` 사본(`.env.local-db`)을 만들어 두세요.
- 작업 스케줄러 시각은 그대로(14:30, 18:30). GitHub Actions 보조 배치는 20분 뒤(14:50, 18:50)라 PC가 먼저 돌고, 이미 최신이면 즉시 끝납니다. 겹치면 DB 잠금으로 한쪽이 양보합니다(`[정보] 다른 일일 배치가 이미 실행 중…`).
- 보조 배치 수동 시험: GitHub → Actions → scheduled-batch → **Run workflow** → `dry-run`.

## 7. Render 프록시 대역 확인 (공개 전 필수)

왜 필요한가: API는 방문자별 요청 한도(분당 60회)를 접속 IP로 셉니다. Render 앞단 프록시의 주소 대역을 모르고 설정을 비우면 **모든 방문자가 한도를 같이 쓰고**, `*`로 두면 **한도를 우회**할 수 있습니다. 그래서 대역을 확인해 지정하기 전에는 공개하지 않습니다.

1. API 서비스 환경변수가 `PUBLIC_API_LOG_PEER_IPS=1`, `PUBLIC_API_REQUIRE_TRUSTED_PROXY=false`, `PUBLIC_API_TRUSTED_PROXY_IPS` 비어 있음인지 확인.
2. 브라우저로 **API 주소 + `/api/v1/stocks?query=삼성&market=ALL`** 를 서로 다른 네트워크(PC, 휴대폰 LTE)에서 몇 번 엽니다.
3. Render → API 서비스 → **Logs**에서 `PEER-DIAG`를 검색합니다. 처음 20건만 기록됩니다.
   `peer=10.x.x.x  x-forwarded-for='내공인IP, 10.x.x.x'` 같은 줄에서 **peer 값**이 Render 프록시 주소입니다.
4. 여러 줄의 peer가 같은 사설 대역(예: 모두 `10.` 으로 시작)인지 봅니다. 값이 일정하지 않으면 Render 문서/지원에 대역을 문의하세요. **추측으로 넓게 지정하지 마세요.**
5. 확인된 대역을 CIDR로 `PUBLIC_API_TRUSTED_PROXY_IPS`에 입력(예: `10.0.0.0/8` 처럼 확인된 범위만, `*` 금지). 그다음 `PUBLIC_API_REQUIRE_TRUSTED_PROXY=true`, `PUBLIC_API_LOG_PEER_IPS` 삭제. (방문자 IP가 로그에 남으므로 확인이 끝나면 반드시 끕니다.)
6. 검증: 같은 네트워크에서 `/api/v1/stocks?...`를 70번 빠르게 호출하면 429가 나오고, 다른 네트워크(LTE)에서는 정상이어야 합니다(방문자별로 센다는 뜻).
7. 웹 서비스의 `FRONTEND_TRUSTED_PROXY_HOPS`는 `0`으로 둡니다(서버 화면 요청은 방문자 IP를 API에 전달하지 않고 내부 공용 버킷으로 처리).

## 8. 시간 제한(이미 설정됨)

`render.yaml`에 DB 연결 10초, 쿼리 8초, 요청 15초로 넣어 두었습니다(기본값은 3초/3초/4.5초이고 코드 기본값은 그대로입니다). Neon이 잠들었다 깨어나는 첫 요청이 실패하지 않게 하기 위함입니다. 변경은 `PUBLIC_API_DB_CONNECT_TIMEOUT_SECONDS`(1~30), `PUBLIC_API_DB_STATEMENT_TIMEOUT_MS`(500~30000), `PUBLIC_API_REQUEST_TIMEOUT_SECONDS`(1~60)입니다. 범위를 벗어나면 서버가 시작하지 않고 이유를 알려줍니다.

## 9. 공개 전 점검표

| # | 확인 | 방법 |
|---|---|---|
| 1 | API가 살아 있음 | `…/api/v1/live` → `{"data":{"status":"ok"}}` |
| 2 | DB까지 연결됨 | `…/api/v1/health` (Neon을 깨웁니다. 헬스체크로 반복 호출하지 마세요) |
| 3 | 화면에 데이터가 보임 | 웹 주소 → 종목 검색 → 종목 상세 |
| 4 | 보조 배치가 해외에서 동작 | Actions → scheduled-batch → `dry-run` 성공(공공데이터 접속 확인) |
| 5 | 자동 배포 흐름 | 코드 변경 1건을 PROD_SCH에 푸시 → render-deploy 성공 → Render에서 배포 완료 |
| 6 | 잠든 뒤 첫 접속 | 20분 방치 후 접속 → "서버를 깨우는 중" 안내 → 1~2분 안에 화면 표시 |
| 7 | 프록시 대역 확인 완료 | §7의 6단계 통과, `REQUIRE_TRUSTED_PROXY=true` |
| 8 | 키 재발급 완료 | KIS·공공데이터포털·DART 키 재발급, PC `.env` 갱신 |
| 9 | 법률·약관 검토 | "급등 전 압축주" 표현, 데이터 이용 약관(REQ-022/Q4) |
| 10 | 백업 복원 연습 | R2 백업 1건을 임시 DB에 복원해 보기 |

## 10. 문제가 생기면

| 증상 | 원인/조치 |
|---|---|
| render-deploy가 "Secrets not set → skipped" | 정상(아직 Secret 미등록). §4 |
| "pooled endpoint" 오류로 중단 | `NEON_OWNER_URL`에 `-pooler` 주소를 넣음 → 직접 주소로 교체 |
| "backup failed → deployment stopped" | R2/age 설정 오류. DB는 바뀌지 않았고 Render도 배포되지 않음. 수정 후 Actions에서 **Re-run** |
| "migration failed (nothing was deployed)" | 마이그레이션 오류. 이전 버전은 그대로 서비스 중. 로그 확인 후 알려주세요 |
| API가 시작하지 않고 "기동 거부" | `REQUIRE_TRUSTED_PROXY=true`인데 대역이 비어 있음 → §7 |
| 첫 접속이 오래 걸림 | 정상(무료 서버가 깨어나는 중). 계속 1분 넘게면 Render 로그 확인 |
| 배치가 "다른 일일 배치가 이미 실행 중" | 정상(중복 방지). 계속 반복되면 이전 실행이 멈췄는지 확인 |
| GitHub Actions 스케줄이 멈춤 | 60일 동안 저장소 활동이 없으면 GitHub이 끕니다 → Actions 탭에서 다시 켜기 |

## 11. 되돌리기

- 앱: Render → 서비스 → **Events/Deploys**에서 이전 배포를 **Rollback**. DB 변경은 되돌리지 않으므로, 스키마 변경이 포함된 배포는 반드시 "추가만 하는 변경"으로 유지합니다(현재 마이그레이션 14개 모두 해당).
- DB: R2 백업에서 복원(`deploy/scripts/restore.sh`) 또는 Neon 6시간 이력 복원.
- 베타를 접고 VPS로 이동: `docs/ops/oracle-deploy-guide.md`의 흐름을 그대로 사용(코드 변경 없음, `deploy/` 구성 유지).
