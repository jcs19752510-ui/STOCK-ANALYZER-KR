# 운영 서버 배포 절차서 — Oracle 무료 VM 한 대 + Cloudflare R2 백업 (2026-10-03, DEC-060)

> **이 문서는 처음 서버를 다뤄 보는 사람 기준**으로 썼습니다. 순서대로 따라 하면 됩니다.
> 각 단계 끝에 **"이렇게 보이면 성공"** 이 있습니다. 그게 안 보이면 **다음 단계로 가지 말고** 그 화면을 캡처해서 알려 주세요.
> 서버 생성·결제·키 발급은 **본인 계정으로 직접** 해야 합니다(제가 대신할 수 없습니다). 이 저장소가 제공하는 것은 설정 파일과 스크립트입니다.
> **배포 방식(DEC-062, 2026-10-03 변경)**: `PROD_SCH` 브랜치에 푸시하면 **서버가 몇 분 안에 알아서 반영**합니다. 승인 버튼, `release` 브랜치, GitHub Actions, GitHub Secrets는 **쓰지 않습니다.** 사용자가 이 "항상 자동 반영" 방식을 상시 승인으로 선택했습니다(11번).
> **서버 업체**: 이 문서는 Oracle 무료 VM 기준으로 쓰였지만, Docker가 되는 리눅스 서버(국내·해외 VPS)라면 4~5번의 "방화벽·접속" 부분만 업체 화면에 맞게 바꾸면 **나머지는 그대로** 쓸 수 있습니다.

---

## 0. 먼저 큰 그림 (3분)

### 0-1. 서버 한 대 안에 이렇게 들어갑니다
```
인터넷 ──https──▶ [Caddy]  문지기: HTTPS 인증서 자동 발급, 요청을 나눠 줌
                    │
                    ├─ /api/* ─────▶ [API (FastAPI)] ──▶ [DB (PostgreSQL 16)]
                    └─ 그 외 ──────▶ [웹 화면 (Next.js)] ──▶ (API 호출)

[cron] 평일 14:30·18:30 ──▶ [배치] 주가 수집·지표 계산 ──▶ DB
[cron] 매일 03:20      ──▶ [백업] DB 덤프 → 암호화 → Cloudflare R2 (서버 밖 보관함)
```
- 위 박스는 **전부 Oracle VM 한 대 안의 Docker 컨테이너**입니다. 바깥에 있는 것은 R2(백업 보관함)뿐입니다.
- **DB는 외부에서 접속할 수 없습니다**(포트를 열지 않음). API와 웹만 Caddy를 통해 나갑니다.
- API 문서 화면(`/docs`)도 외부에는 열리지 않습니다(`/api/*` 만 API로 전달).

### 0-2. 파일 목록 (이 저장소 안, 제가 만든 것)
| 파일 | 하는 일 |
|---|---|
| `deploy/docker-compose.yml` | 서버 전체 구성(DB·API·웹·Caddy와 1회성 작업) |
| `deploy/backend.Dockerfile`, `frontend.Dockerfile`, `backup.Dockerfile` | 프로그램 포장(이미지) 설명서 |
| `deploy/Caddyfile` | HTTPS·경로 나누기·보안 헤더 |
| `deploy/db/init/01-roles.sh` | DB 계정 3개(migrator/batch_worker/api_service) 자동 생성 |
| `deploy/.env.production.example` | 서버 설정 템플릿(비밀번호·키 자리) |
| `deploy/scripts/init-env.sh` | 설정 파일 만들고 랜덤 비밀번호 채움 |
| `deploy/scripts/deploy.sh` | 배포(백업→빌드→DB 갱신→재시작→실패 시 되돌리기) |
| `deploy/scripts/auto-deploy.sh` | **자동 배포**: 몇 분마다 `PROD_SCH`를 확인해 코드가 바뀌었을 때만 `deploy.sh` 실행 |
| `deploy/tests/test-auto-deploy.sh` | 자동 배포 시험 코드(가짜 docker로 78개 항목 점검) |
| `deploy/scripts/bootstrap-data.sh` | 처음 데이터 채우기 |
| `deploy/scripts/backup.sh`, `restore.sh`, `restore-run.sh` | 백업·복구 |
| `deploy/crontab.example`, `logrotate.stock-analyzer` | 자동 실행 시간표, 로그 정리 |

### 0-2-1. 준비물과 예상 시간·비용
| 항목 | 내용 |
|---|---|
| 계정 | Oracle Cloud, Cloudflare(R2), GitHub(이미 있음), DuckDNS(무료 주소, 구글/GitHub 로그인) |
| 카드 | Oracle 가입에 **카드 인증**이 필요합니다(무료 한도 안에서는 과금 없음, 최신 조건은 공식 페이지 확인). R2도 카드 등록이 필요할 수 있습니다. |
| 내 PC | Windows. 이미 PowerShell과 Git이 있습니다. SSH(`ssh`)는 Windows 10/11에 기본 포함입니다. |
| 시간 | 처음엔 반나절~하루 (Oracle 서버 생성이 "자원 부족"으로 막히면 더 걸릴 수 있음) |

### 0-3. Render 무료 주소(`xxx.onrender.com`)를 쓸 수 있나요?
**못 씁니다.** 그 주소는 Render가 호스팅하는 서비스에만 붙습니다. Oracle VM에는 아래 3번의 **무료 주소(DuckDNS)** 를 쓰면 됩니다.

---

## 1. 시작 전 반드시 할 일 (보안·법률) — 건너뛰지 마세요

1. **노출된 키를 모두 새로 발급**합니다. 아래는 대화 또는 화면 캡처에 한 번이라도 나왔으므로 "이미 유출된 것"으로 봅니다.
   - 한국투자증권 앱키·시크릿 → (이 서버에는 **넣지 않습니다**. 개인 PC용으로만 재발급)
   - 공공데이터포털 서비스키 → 마이페이지에서 재발급
   - DART API 키 → opendart 마이페이지에서 재발급
2. **서버에는 한국투자증권 키를 절대 넣지 않습니다.** (개인 로컬 모드는 서버에서 꺼져 있어야 합니다. 이 배포 파일은 그 변수를 서버에 전달하지도 않습니다.)
3. **법률·약관 확인**: `docs/ops/pre-deploy-checklist.md` A항(공공데이터 약관의 재배포 조항, DART 약관, "급등 전 압축주" 문구)은 **사용자만 확인할 수 있습니다.** 확인 전까지 서버 설정의 `PRICE_EXPOSURE_ENABLED=false`(원 시세값 비공개)를 유지하는 것을 권장합니다. 켤지 끌지는 **사용자가 결정**합니다.

---

## 2. 준비 ① Cloudflare R2 (백업 보관함) + 암호화 키

### 2-1. 암호화 키 만들기 — 내 PC에서 (가장 중요)
백업 파일은 서버에서 **암호화한 뒤** R2에 올립니다. 서버에는 **공개키**만 두고, **개인키는 내 PC에만** 둡니다. (서버가 해킹돼도 옛 백업은 못 읽습니다.)

1. PowerShell에서 age 설치: `winget install FiloSottile.age` (설치 후 PowerShell을 새로 엽니다)
2. 키 만들기:
   ```
   age-keygen -o age-private-key.txt
   ```
3. 화면에 `Public key: age1xxxxxxxx...` 가 나옵니다. **이 `age1...` 줄(공개키)** 을 메모합니다. 나중에 서버 설정에 넣습니다.
4. `age-private-key.txt`(개인키)는 **절대 서버나 GitHub에 올리지 않습니다.** 비밀번호 관리자 + USB 등 **2곳 이상**에 보관합니다.
   > ⚠️ 이 파일을 잃어버리면 **백업이 있어도 복구할 수 없습니다.**

### 2-2. R2 버킷과 접속키
1. Cloudflare 가입 → 왼쪽 메뉴 **R2 Object Storage** → (안내에 따라 활성화, 카드 등록이 필요할 수 있음)
2. **Create bucket** → 이름 `stock-analyzer-backup`, 위치는 APAC(아시아) 권장.
3. R2 화면 오른쪽의 **Manage API tokens** → **Create API token**
   - 권한: **Object Read & Write**
   - 범위: **이 버킷만**(Specify bucket) 선택
4. 발급 직후 한 번만 보이는 값을 메모: **Access Key ID**, **Secret Access Key**, 그리고 **엔드포인트** `https://<계정ID>.r2.cloudflarestorage.com`.
- 이 값들은 아래 7번에서 서버 `.env`에만 넣습니다. 채팅·GitHub에 붙여넣지 마세요.
- 무료 저장 용량 등 최신 한도는 Cloudflare 공식 R2 요금 페이지에서 확인하세요(이 문서 작성 시 직접 확인하지 못했습니다).

---

## 3. 준비 ② 무료 주소 만들기 (DuckDNS)

도메인이 없으면 **무료 서브도메인**을 씁니다.
1. https://www.duckdns.org 에서 로그인(구글/GitHub 등).
2. 원하는 이름 입력(예: `mystockkr`) → **add domain** → `mystockkr.duckdns.org` 가 만들어집니다.
3. **IP는 4번에서 서버를 만든 뒤에** 그 서버의 고정 공용 IP를 입력합니다.
- 이 주소(`mystockkr.duckdns.org`)가 서버 설정의 `SITE_HOST` 입니다. (`https://` 는 붙이지 않습니다.)
- 나중에 본인 도메인을 사서 `SITE_HOST`만 바꾸고 다시 배포하면 교체됩니다.
- DuckDNS는 개인용 무료 서비스라 가용성 보증이 없습니다. 정식 서비스 단계에서는 본인 도메인을 권장합니다.

---

## 4. Oracle Cloud 가입과 서버(VM) 만들기

### 4-1. 가입
1. https://www.oracle.com/kr/cloud/free/ → **무료로 시작하기**.
2. **홈 리전(Home Region)은 가입 때 한 번 정하면 못 바꿉니다.** **서울(South Korea Central, Seoul)** 을 선택하세요(국내 사용자·국내 API 호출에 유리). 서울에 무료 서버 자리가 없으면 춘천(Chuncheon)을 고려합니다.
3. 카드 인증. 무료 한도 안에서는 과금되지 않습니다. 단 **"Pay As You Go"로 업그레이드하지 않으면** 한도를 넘는 리소스는 아예 생성되지 않습니다(안전).

### 4-2. SSH 키 만들기 — 내 PC에서
서버 접속은 **비밀번호가 아니라 키**로 합니다.
```
ssh-keygen -t ed25519 -f $HOME\.ssh\oracle_server -C "stock-oracle-server"
```
- 비밀번호(passphrase)를 물으면 **설정을 권장**합니다.
- `oracle_server`(개인키, 비공개)와 `oracle_server.pub`(공개키)가 생깁니다. **개인키는 절대 공유 금지.**

### 4-3. 서버 만들기 (콘솔: 메뉴 ☰ → Compute → Instances → Create instance)
| 항목 | 값 |
|---|---|
| 이름 | `stock-server` |
| 이미지 | **Canonical Ubuntu 24.04** (aarch64 / ARM용) |
| 모양(Shape) | **Ampere → VM.Standard.A1.Flex**, **OCPU 2, 메모리 12GB** (무료 한도 최대치. 한도는 2026-06에 줄었으므로 이 값을 넘기지 마세요) |
| 네트워크 | 새 VCN 자동 생성, **퍼블릭 IPv4 주소 할당** 체크 |
| SSH 키 | "공개키 붙여넣기" → `oracle_server.pub` 파일 내용(한 줄) |
| 부트 볼륨 | 50~100GB (무료 한도 안에서) |

- **"Out of capacity(용량 부족)"** 오류가 나면: 다른 가용성 도메인(AD)을 선택하거나, 시간대를 바꿔 다시 시도합니다. 흔한 일입니다.
- 생성이 끝나면 **퍼블릭 IP**가 보입니다. 메모합니다.
- **IP 고정**: 인스턴스 → Attached VNICs → IPv4 Addresses에서 임시(Ephemeral) IP를 **예약된(Reserved) IP**로 바꿔 두면 서버를 재생성해도 주소가 유지됩니다(요금 조건은 공식 페이지 확인).
- 이제 3번의 DuckDNS에서 **current ip** 칸에 이 퍼블릭 IP를 입력하고 **update ip** 를 누릅니다.

### 4-4. 방화벽(보안 목록) 열기 — 2군데에서 열어야 합니다
**(가) Oracle 콘솔의 보안 목록**: Networking → Virtual Cloud Networks → (내 VCN) → Subnet → Security List → **Ingress Rules**
| 소스 CIDR | 프로토콜 | 포트 | 용도 |
|---|---|---|---|
| `0.0.0.0/0` | TCP | **80** | HTTP (인증서 발급용) |
| `0.0.0.0/0` | TCP | **443** | HTTPS |
| **내 공인 IP/32** | TCP | **22** | SSH (내 IP만. 기본 규칙에 `0.0.0.0/0`의 22가 있으면 **내 IP로 좁히세요**) |
- 내 공인 IP는 https://ifconfig.me 에서 확인합니다. 집 IP가 바뀌면(유동 IP) SSH가 막히므로, 그땐 콘솔에서 규칙을 바꿉니다.
- 다른 포트(5432 DB 등)는 **절대 열지 않습니다.**

**(나) 서버 안의 iptables** (Oracle Ubuntu 이미지는 기본으로 80/443을 막아 둡니다. 5번에서 설정합니다.)

> **이렇게 보이면 성공**: 인스턴스 상태가 **Running(실행 중)** 이고 퍼블릭 IP가 보인다.

---

## 5. 서버 접속과 기본 보안 설정

### 5-1. 접속 (내 PC PowerShell)
```
ssh -i $HOME\.ssh\oracle_server ubuntu@<서버 퍼블릭 IP>
```
- 처음 접속 때 "fingerprint ... continue connecting?" → `yes`.
- 프롬프트가 `ubuntu@stock-server:~$` 로 바뀌면 성공입니다. **이후 5~10번 명령은 모두 서버 안에서 실행**합니다.

### 5-2. 업데이트·기본 도구·시간대
```
sudo apt-get update && sudo apt-get -y upgrade
sudo apt-get install -y ca-certificates curl git openssl iptables-persistent unattended-upgrades fail2ban
sudo timedatectl set-timezone Asia/Seoul
timedatectl | grep "Time zone"
```
- `iptables-persistent` 설치 중 "현재 규칙 저장?" 질문이 나오면 **Yes**.
- `unattended-upgrades`: 보안 패치 자동 설치(켜짐 확인: `sudo dpkg-reconfigure -plow unattended-upgrades` → Yes).
- `fail2ban`: SSH 무차별 대입 시도를 자동 차단.
- 마지막 줄에 `Asia/Seoul` 이 나오면 성공(배치 시각이 한국 시간으로 동작).

### 5-3. 서버 안 방화벽(iptables)에서 80/443 열기
```
sudo iptables -L INPUT -n --line-numbers
```
`REJECT ... icmp-host-prohibited` 줄 번호를 확인한 뒤, **그 줄보다 앞** 번호에 넣습니다. 아래 명령의 `5`는 예시이므로 **본인 화면의 REJECT 줄 번호**로 바꾸세요(보통 5 또는 6):
```
sudo iptables -I INPUT 5 -p tcp --dport 80  -m conntrack --ctstate NEW -j ACCEPT
sudo iptables -I INPUT 5 -p tcp --dport 443 -m conntrack --ctstate NEW -j ACCEPT
sudo netfilter-persistent save
sudo iptables -L INPUT -n --line-numbers | head -12
```
> **이렇게 보이면 성공**: 목록에 `tcp dpt:80`, `tcp dpt:443` ACCEPT 가 REJECT 줄보다 위에 있다.

### 5-4. SSH 보안 확인
```
sudo sshd -T | grep -Ei "passwordauthentication|permitrootlogin"
```
- `passwordauthentication no`, `permitrootlogin no`(또는 prohibit-password)면 정상입니다. 아니면 알려 주세요.

### 5-5. (권장) 메모리 여유용 스왑 2GB
```
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

---

## 6. Docker 설치 (서버 안)
Docker 공식 방법입니다.
```
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" | sudo tee /etc/apt/sources.list.d/docker.list
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker $USER
```
**한 번 로그아웃했다가 다시 접속**(`exit` 후 5-1 명령 재실행)한 뒤:
```
docker --version && docker compose version
docker run --rm hello-world
```
> **이렇게 보이면 성공**: `Hello from Docker!` 문구가 나온다.
> 참고: `docker` 그룹 사용자는 사실상 서버 관리자 권한입니다. 이 계정(SSH 키)을 소중히 다루세요.

---

## 7. 코드 받기와 서버 설정 파일 만들기

### 7-1. 서버가 GitHub에서 코드를 읽을 수 있게 (읽기 전용 열쇠)
저장소는 **비공개**라서 서버가 코드를 받으려면 "배포 키"가 필요합니다.
```
ssh-keygen -t ed25519 -f ~/.ssh/github_deploy -C "stock-server-readonly" -N ""
cat ~/.ssh/github_deploy.pub
```
1. 출력된 한 줄(`ssh-ed25519 AAAA...`)을 복사합니다.
2. GitHub → 저장소 `stock-analyzer-kr` → **Settings → Deploy keys → Add deploy key**
   - Title: `oracle-server`, Key: 붙여넣기, **"Allow write access" 는 체크하지 않습니다(읽기 전용).**
3. 서버에서 이 키를 쓰도록 설정:
   ```
   cat >> ~/.ssh/config <<'EOF'
   Host github.com
     IdentityFile ~/.ssh/github_deploy
     IdentitiesOnly yes
   EOF
   chmod 600 ~/.ssh/config
   ssh -T git@github.com
   ```
   > **이렇게 보이면 성공**: `Hi jcs19752510-ui/stock-analyzer-kr! You've successfully authenticated...`

### 7-2. 운영 브랜치는 `PROD_SCH` 그대로 (DEC-062)
- **새 브랜치(`release`)를 만들지 않습니다.** 서버는 개발 브랜치 `PROD_SCH`를 그대로 따라갑니다.
- ⚠️ 그래서 **`PROD_SCH`에 푸시한 코드는 곧바로 운영에 반영**됩니다(11번). 미완성 코드를 올리기 전에는 서버에서 `./scripts/auto-deploy.sh --pause`로 자동 반영을 잠시 멈추세요.

### 7-3. 코드 받기
```
cd ~
git clone -b PROD_SCH git@github.com:jcs19752510-ui/stock-analyzer-kr.git stock-analyzer-kr
cd stock-analyzer-kr/deploy
ls
```
> **이렇게 보이면 성공**: `docker-compose.yml`, `Caddyfile`, `scripts` 등이 보인다.

### 7-4. 설정 파일 만들기
```
./scripts/init-env.sh
nano .env
```
`init-env.sh` 가 **DB 비밀번호 4개와 내부 토큰을 랜덤으로** 채웁니다(값은 화면에 출력하지 않음). `FILL_ME` 라고 적힌 줄만 직접 채웁니다.
| 항목 | 넣을 값 |
|---|---|
| `SITE_HOST` | 3번에서 만든 주소(예: `mystockkr.duckdns.org`, `https://` 없이) |
| `ACME_EMAIL` | 내 이메일(인증서 만료 알림용) |
| `GOV_DATA_PORTAL_SERVICE_KEY` | **새로 발급한** 공공데이터포털 서비스키 |
| `DART_API_KEY` | **새로 발급한** DART 키 |
| `DATA_FRESHNESS_WEBHOOK_URL` | (선택) Slack/Discord 웹훅. 데이터가 늦을 때 알림. 없으면 비워 둠 |
| `AUTO_DEPLOY_WEBHOOK_URL` | (선택) 자동 배포 성공·실패 알림용 Slack/Discord 웹훅. 없으면 비워 둠 |
| `PRICE_EXPOSURE_ENABLED` | `false` 유지 권장(1번 3항, **사용자 결정**) |
| `BACKUP_AGE_RECIPIENT` | 2-1에서 메모한 `age1...` **공개키** |
| `R2_BUCKET` / `R2_ENDPOINT` / `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` | 2-2에서 메모한 값 |
- nano 저장: `Ctrl+O` → Enter → `Ctrl+X`.
- 확인: `grep -cE '=(FILL_ME|CHANGE_ME)$' .env` 결과가 **0** 이면 다 채운 것입니다(처음에는 9가 나옵니다). 권한 확인: `ls -l .env` → `-rw-------` .
- **`.env`는 서버에만 있고 GitHub에는 절대 올라가지 않습니다**(`.gitignore` 처리됨).

---

## 8. 첫 실행과 데이터 채우기

### 8-1. 첫 배포 (처음엔 직접 실행)
```
cd ~/stock-analyzer-kr/deploy
./scripts/deploy.sh PROD_SCH
```
- 처음에는 **이미지를 만드느라 10~25분** 걸립니다(ARM). 중간에 멈춘 것처럼 보여도 기다립니다.
- 흐름: 코드 갱신 → (DB가 아직 없어 백업은 건너뜀) → 이미지 빌드 → DB 시작 → **DB 계정 3개 자동 생성** → 마이그레이션 → 서비스 시작 → 건강 상태 확인.
> **이렇게 보이면 성공**: 마지막 줄에 `[OK] deployed <12자리 버전>`.
```
docker compose ps
```
→ `db`, `api`, `web`, `caddy` 가 모두 `running` (db/api/web은 `healthy`).

### 8-2. 접속 확인 (HTTPS 인증서는 1~2분 걸릴 수 있음)
```
curl -s https://<SITE_HOST>/api/v1/health
```
> **이렇게 보이면 성공**: `"status":"ok","db":"ok"` 가 들어 있는 JSON.
- 브라우저에서 `https://<SITE_HOST>/` 접속 → 화면이 열리고 주소창에 자물쇠가 보입니다.
- 인증서 오류가 나면: ① DuckDNS IP가 서버 IP와 같은지 ② 4-4 (가)(나) 방화벽 80/443 ③ `docker compose logs caddy --tail 50` 을 확인합니다. (Let's Encrypt는 짧은 시간에 실패를 반복하면 잠시 제한을 겁니다. 원인을 고친 뒤 몇 분 후 재시도.)

### 8-3. 데이터 채우기 — 방법 A(권장, 빠름): 내 PC의 DB를 그대로 옮기기
내 PC DB에는 이미 시세·재무·실적이 있어서, **전 종목을 다시 수집(수 시간, 호출 수천 회)하지 않고** 옮길 수 있습니다.

**① 내 PC(PowerShell)에서 덤프 만들기**
```
docker exec stock-screener-pg pg_dump -U postgres -d stock_screener -Fc --no-owner -f /tmp/stock.dump
docker cp stock-screener-pg:/tmp/stock.dump .\stock.dump
```
- 접속 계정이 `postgres`가 아니면 `-U` 값을 본인 환경에 맞게 바꿉니다.

**② 서버로 복사 (PC PowerShell)**
```
scp -i $HOME\.ssh\oracle_server .\stock.dump ubuntu@<서버 퍼블릭 IP>:~/stock.dump
```

**③ 서버에서 복원** (복원 중에는 화면을 잠시 멈춥니다)
```
cd ~/stock-analyzer-kr/deploy
docker compose stop caddy web api
docker compose exec -T db pg_restore -U stock_admin -d stock_screener --clean --if-exists --no-owner --role=migrator < ~/stock.dump
docker compose up -d --wait
shred -u ~/stock.dump
```
- `pg_restore`가 몇 가지 경고를 출력해도 마지막에 오류 요약이 크지 않으면 정상입니다. 안 되면 출력을 알려 주세요.
- 이 방식은 서버 DB 계정(migrator/batch_worker/api_service)의 권한이 그대로 유지됨을 **임시 DB로 시험했습니다**(시험 결과: 데이터·마이그레이션 버전·권한 보존).
> **이렇게 보이면 성공**: 브라우저에서 종목 상세에 데이터가 보이고, `docker compose exec db psql -U stock_admin -d stock_screener -c "select max(trade_date) from public_serving.daily_prices"` 가 PC의 최신일과 같다.

### 8-3-B. 방법 B: 서버에서 처음부터 수집 (PC DB를 못 옮길 때)
```
cd ~/stock-analyzer-kr/deploy
./scripts/bootstrap-data.sh calendar          # 휴장일 달력
./scripts/bootstrap-data.sh master            # 종목 목록
./scripts/bootstrap-data.sh backfill --dry-run   # 호출 수만 미리 보기(호출 한도 확인!)
./scripts/bootstrap-data.sh backfill --days 130 --sleep 0.3   # 과거 시세(한도 확인 후 실행)
./scripts/bootstrap-data.sh batch             # 최신일 수집·지표 계산
./scripts/bootstrap-data.sh corpfin           # PER/PBR 재무(30~60분)
./scripts/bootstrap-data.sh earnings          # 연간 실적(약 30분)
```
- 긴 작업(corpfin, earnings)은 **끊겨도 재실행하면 이어서 합니다.** SSH 연결이 끊기는 것을 막으려면 `tmux` 안에서 실행하세요(`sudo apt install -y tmux`, `tmux new -s job`, 끊겨도 `tmux attach -t job`).
- 공공데이터 일일 호출 한도는 마이페이지에서 확인한 뒤 `backfill`을 실행하세요(이 문서 작성 시 한도 수치를 직접 확인하지 못했습니다).

---

## 9. 자동 실행(cron) — 배치와 백업

### 9-1. 등록
```
mkdir -p ~/stock-logs
cd ~/stock-analyzer-kr
nano deploy/crontab.example     # 경로가 /home/ubuntu 가 맞는지 확인(다르면 수정)
crontab deploy/crontab.example
crontab -l
sudo cp deploy/logrotate.stock-analyzer /etc/logrotate.d/stock-analyzer
```
| 시각(한국시간) | 작업 |
|---|---|
| 매일 14:30, 18:30 | 일일 배치(수집 → 지표 계산, 놓친 날 따라잡기) |
| 매일 09:10 | 데이터 신선도 점검(늦으면 웹훅 알림) |
| 매일 03:20 | DB 백업 → 암호화 → R2 |
| **2분마다** | **자동 배포 확인**: `PROD_SCH`에 코드가 바뀐 새 커밋이 있으면 배포(없으면 아무 일도 안 함) |

### 9-2. 지금 한 번 직접 돌려 보기
```
cd ~/stock-analyzer-kr/deploy
docker compose --profile tools run --rm -T batch python scripts/run_daily_batch.py
```
- 종료 코드 `0` 정상, `2` 는 "대상 거래일 데이터가 아직 공개 전"(주말·공휴일 직후에 정상).

---

## 10. 백업이 진짜 되는지 확인 (꼭 해 보세요)

### 10-1. 백업 1회 실행
```
cd ~/stock-analyzer-kr/deploy
docker compose --profile tools run --rm -T backup
```
> **이렇게 보이면 성공**: `[backup] uploaded daily/stock_screener-...dump.age (N bytes)` 그리고 `[backup] done`.
- Cloudflare R2 화면의 버킷에서 `daily/` 폴더에 파일이 생겼는지도 확인합니다.

### 10-2. 복구 시험 (진짜 DB는 건드리지 않음)
1. 내 PC에 있는 `age-private-key.txt` 를 서버로 **임시 복사**: `scp -i $HOME\.ssh\oracle_server .\age-private-key.txt ubuntu@<IP>:~/age-private-key.txt`
2. 서버에서(파일 이름은 R2에서 확인한 이름으로):
   ```
   cd ~/stock-analyzer-kr/deploy
   ./scripts/restore-run.sh --test daily/stock_screener-XXXXXXXXTXXXXXXZ.dump.age ~/age-private-key.txt
   ```
3. 끝나면 **개인키를 서버에서 즉시 삭제**: `shred -u ~/age-private-key.txt`
> **이렇게 보이면 성공**: `[restore] TEST OK — the backup is restorable.` (임시 DB `restore_test`는 자동 삭제)
- **한 달에 한 번** 이 시험을 반복하세요. "백업은 복구해 봐야 백업"입니다.

### 10-3. 진짜 복구가 필요할 때 (서버 새로 만든 경우 포함)
`./scripts/restore-run.sh --real <백업 파일> <개인키 파일>` → 확인 문구 `RESTORE` 를 직접 입력해야 진행됩니다. 현재 DB를 **통째로 덮어씁니다.**
새 서버라면: 4~8-2를 다시 한 뒤 위 명령으로 복구합니다.

---

## 11. 자동 배포 (`PROD_SCH` 푸시 → 서버가 자동 반영, DEC-062)

### 11-1. 어떻게 동작하나요?
```
내 PC / 클라우드 / PC의 Claude ──git push──▶ GitHub의 PROD_SCH
                                                  │  (서버가 2분마다 "새 커밋 있나?" 하고 읽어 감)
                                                  ▼
                 서버의 auto-deploy.sh ── 바뀐 파일이 코드인가? ──아니오(문서·시험·결과서만)──▶ 건너뜀
                                                  │예
                                                  ▼
                          배포 전 DB 백업 ─▶ 이미지 빌드 ─▶ DB 구조 갱신 ─▶ 재시작 ─▶ 상태 확인
                                                  │실패하면
                                                  ▼
                          이전 버전으로 자동 복귀 + (선택) 알림, 같은 커밋은 다시 시도하지 않음
```
- **서버가 GitHub를 "읽기만"** 합니다. 그래서 서버의 SSH(22번)를 **내 IP만 허용한 상태 그대로** 두어도 됩니다. GitHub에 비밀값(Secrets)을 등록할 필요도 없습니다.
- 푸시하고 **최대 약 2분 뒤** 서버가 알아차리고, 이미지 빌드(보통 몇 분~십여 분)가 끝나면 반영됩니다.
- 이전의 승인 버튼, `release` 브랜치, GitHub Actions 검사는 **없앴습니다.**

### 11-2. 무엇이 배포되고, 무엇은 배포되지 않나요?
| 배포됨(서버에서 다시 빌드) | 배포 안 됨(건너뜀) |
|---|---|
| `services/`, `shared/`, `db/`(마이그레이션 포함), `scripts/*.py`, `data/` | `docs/`(문서·QA 결과서·캡처) |
| `frontend/`(화면 코드, 설정, 패키지) | `tests/`, `frontend/scripts/qa/`, `frontend/scripts/check-*.mjs`(시험 코드) |
| `requirements.txt`, `alembic.ini`, `.dockerignore` | `*.md`, 이미지 파일(`.png` 등), `.github/`, `automation/` |
| `deploy/docker-compose.yml`, `Caddyfile`, `*.Dockerfile`, `deploy/db/init/`, `deploy/scripts/backup.sh`·`restore.sh` | `deploy/scripts/`의 나머지(배포·설정 스크립트), `crontab.example`, `scripts/*.ps1`(Windows 전용) |
- **판단 기준**: 서버 안에서 돌아가는 프로그램에 영향을 주는 파일이 하나라도 바뀌었으면 배포합니다. **목록에 없는 새 파일은 배포 쪽으로 처리**합니다(놓치는 것보다 한 번 더 배포하는 쪽이 안전).
- 문서만 올린 푸시는 건너뛰지만, 그 뒤에 코드가 바뀐 푸시가 오면 **그 사이 바뀐 것 전부**가 함께 반영됩니다.

### 11-3. 처음 한 번 확인하기 (서버에서)
`9-1`에서 cron을 등록했다면(2분 줄 포함) 이미 켜져 있습니다. 아래로 상태를 봅니다.
```
cd ~/stock-analyzer-kr/deploy
./scripts/auto-deploy.sh --status
```
> **이렇게 보이면 성공**: `branch : PROD_SCH`, `auto deploy : on`, `running (deployed)`에 12자리 값, `remote head`에 12자리 값.
- 처음 배포(8-1)를 한 뒤에는 `running`과 `remote head`가 같아야 합니다(같으면 할 일 없음).
- 로그 보기: `tail -n 30 ~/stock-logs/auto_deploy.log` (아무 일도 없으면 이 파일은 비어 있습니다. 정상입니다.)

**동작 시험(권장, 한 번만)**
1. 문서만 푸시: 로그에 `skip ...: docs/tests/QA only, no redeploy`가 찍히고 서버는 그대로입니다.
2. 눈에 안 띄는 작은 코드 변경을 푸시: 2분 안에 `new commit ... -> deploying` → `[OK] deployed`가 찍힙니다.

### 11-4. 자주 쓰는 명령 (서버에서, `~/stock-analyzer-kr/deploy` 폴더)
| 하고 싶은 일 | 명령 |
|---|---|
| 상태 보기 | `./scripts/auto-deploy.sh --status` |
| **자동 반영 잠시 멈추기**(위험한 작업 전) | `./scripts/auto-deploy.sh --pause` |
| 다시 켜기 | `./scripts/auto-deploy.sh --resume` |
| 실패한 커밋 다시 시도 | `./scripts/auto-deploy.sh --retry` (원인을 고친 뒤) |
| 지금 당장 직접 배포 | `./scripts/deploy.sh PROD_SCH` |
| 사용 설명 | `./scripts/auto-deploy.sh --help` |
- 멈춰 있던 동안 쌓인 변경은 **다시 켜면 한꺼번에** 반영됩니다.

### 11-5. 배포가 실패하면
- 서버가 **이전 버전으로 자동 복귀**를 시도하고, 로그에 `[FAIL] deployment of ... failed`가 남습니다. (`AUTO_DEPLOY_WEBHOOK_URL`을 설정했다면 알림도 갑니다.)
- **같은 커밋은 다시 시도하지 않습니다**(2분마다 계속 실패하는 것을 막기 위함). 고치려면 ① 코드를 고쳐 새로 푸시하거나 ② 원인(예: 백업 설정)을 고친 뒤 `--retry`.
- **백업이 실패하면 배포 자체를 취소**하고 서버를 건드리지 않습니다(안전장치).
- ⚠️ 자동 복귀는 **프로그램만** 되돌립니다. **DB 구조 변경(마이그레이션)은 되돌리지 않습니다.** DB가 문제면 10-3 복구를 하세요.

### 11-6. 반드시 알아 둘 위험 (상시 승인으로 선택하신 내용)
1. **`PROD_SCH`에 푸시된 코드는 사람의 확인 없이 운영에 반영됩니다.** 개발 중인 코드, 실수로 올린 코드도 같습니다.
2. **GitHub 쓰기 권한 = 운영 서버에서 코드를 실행할 수 있는 권한**입니다. GitHub 계정에 **2단계 인증**을 켜고, 저장소에 쓰기 권한이 있는 사람·도구(이 클라우드 세션, PC의 Claude 등)를 최소로 유지하세요.
3. 사전 검사(린트·테스트)가 없어서, **고장 난 코드도 빌드만 되면 올라갑니다.** 마지막 방어선은 "새 버전이 정상 상태(health)가 아니면 이전 버전으로 복귀"입니다.
4. **DB 구조를 바꾸는 큰 작업**(마이그레이션)을 푸시하기 전에는 `--pause`로 멈추고 직접 `deploy.sh`로 지켜보며 배포하는 것을 권합니다.
5. 빌드하는 몇 분 동안 서버가 느려질 수 있습니다.
6. 배포를 완전히 끄고 싶으면 `./scripts/auto-deploy.sh --pause`(임시) 또는 `crontab -e`에서 2분 줄을 지웁니다(영구).

---

## 12. 장애·롤백 대응

| 상황 | 할 일 |
|---|---|
| 화면이 안 열림 | 서버에서 `cd ~/stock-analyzer-kr/deploy && docker compose ps` → 멈춘 컨테이너 확인 → `docker compose logs --tail 80 <이름>` |
| 방금 배포 후 이상 | 먼저 `./scripts/auto-deploy.sh --pause`로 자동 반영을 멈춥니다. 자동 롤백이 안 됐다면: `cat .previous_tag` 로 이전 버전 확인 → `APP_TAG=<이전 버전> docker compose up -d --wait`. 코드를 고치거나 `git revert`를 푸시한 뒤 `--resume` |
| 자동 배포가 안 되는 것 같음 | `./scripts/auto-deploy.sh --status`(PAUSED인지, failed 커밋이 있는지), `tail -n 50 ~/stock-logs/auto_deploy.log`, `crontab -l`에 2분 줄이 있는지, `ssh -T git@github.com`이 되는지 |
| DB가 이상함 | 10-3 복구(최신 백업) |
| 서버 자체가 사라짐/정지 | 4~8-2를 새 서버에서 반복 → 10-3으로 DB 복구 |
| 데이터가 오래됨 | `tail -50 ~/stock-logs/daily_batch.log`. 종료코드 `2` 는 공개 전(정상), 그 외는 오류 메시지 확인 |
| 인증서 오류 | `docker compose logs caddy --tail 80`, DuckDNS IP·방화벽 확인 |
| 디스크 부족 | `df -h`, `docker system df`, `docker image prune -a`(사용 중이 아닌 이미지 삭제) |

---

## 13. 보안 점검표 (배포 전·후)
- [ ] 노출됐던 키(KIS/공공데이터/DART)를 **모두 재발급**했다.
- [ ] 서버 `.env` 권한이 600이고 GitHub에 올라가 있지 않다.
- [ ] 서버에 `KIS_APP_KEY`, `KIS_APP_SECRET`, `LOCAL_INTRADAY_ENABLED` 가 **없다**: `grep -E "KIS_|LOCAL_INTRADAY" ~/stock-analyzer-kr/deploy/.env` 결과가 비어 있다.
- [ ] 열린 포트는 80/443(전체)과 22(**내 IP만**, 자동 배포는 서버가 GitHub를 읽는 방식이라 22번을 열 필요가 없다). `sudo ss -tlnp` 에서 5432가 외부에 열려 있지 않다(Docker 내부 전용).
- [ ] SSH는 키 로그인만(5-4).
- [ ] `https://<SITE_HOST>/docs` 가 열리지 않는다(API 문서 비공개).
- [ ] HTTP로 접속하면 HTTPS로 자동 이동한다.
- [ ] 개인키(`age-private-key.txt`)는 2곳 이상에 보관, 서버에는 없다.
- [ ] GitHub 계정에 **2단계 인증**이 켜져 있고, 저장소 쓰기 권한이 필요한 사람·도구만 있다(푸시 = 운영 반영).
- [ ] 서버의 GitHub 배포 키는 **읽기 전용**(Allow write access 체크 안 함)이다.
- [ ] 약관·법률 확인(1번 3항) 후에만 `PRICE_EXPOSURE_ENABLED=true` 를 검토한다.

---

## 14. 정기 운영 작업
| 주기 | 작업 |
|---|---|
| 매주 | `docker compose ps`, `tail ~/stock-logs/*.log`, `df -h` 한 번 보기 |
| 매월 | 복구 시험(10-2), 서버 패키지 업데이트(`sudo apt-get update && sudo apt-get -y upgrade` 후 필요하면 재부팅), Oracle 콘솔에 로그인해 계정이 살아 있는지 확인(오래 방치하면 회수될 수 있음) |
| 분기 | `./scripts/bootstrap-data.sh corpfin` (PER/PBR 재무 갱신) |
| 매년 4월 초순 이후 | `./scripts/bootstrap-data.sh earnings` (연간 실적) |
| 매년 말 | **다음 해 휴장일 달력** 파일(`data/calendar/2027.yaml`)을 만들어 코드에 반영한 뒤 `./scripts/bootstrap-data.sh calendar data/calendar/2027.yaml` |
| 서버 서비스 이미지 갱신 | `PROD_SCH` 자동 배포 때 코드가 새로 빌드됩니다. DB·Caddy 이미지는 `docker compose pull && docker compose up -d --wait` |
| 매주(자동 배포) | `./scripts/auto-deploy.sh --status`와 `~/stock-logs/auto_deploy.log`에 실패 기록이 없는지 |

---

## 15. 자주 나는 문제
| 증상 | 원인·해결 |
|---|---|
| `docker: permission denied` | 6번의 로그아웃/재접속을 안 함 |
| `[STOP] deploy/.env is missing` | 7-4를 먼저 수행 |
| 빌드가 중간에 죽음(메모리) | 5-5 스왑 추가, `docker compose build` 재시도 |
| api가 `unhealthy` | `docker compose logs api --tail 80`. `.env`의 DB 비밀번호를 **나중에 바꿨다면** DB 볼륨은 처음 만들 때의 비밀번호를 유지하므로, 바꾼 값과 맞지 않아 접속이 실패합니다(아래 참고) |
| 접속은 되는데 데이터가 없음 | 8-3을 아직 안 함, 또는 복원 후 API 재시작을 안 함 |
| 화면에서 호출 오류 | 브라우저 개발자도구 Network 탭의 요청 주소가 `https://<SITE_HOST>/api/...` 인지 확인(주소를 바꿨다면 웹 이미지를 **다시 빌드**해야 함: `./scripts/deploy.sh PROD_SCH`) |
| 배치가 `exit=2` | 대상 거래일 데이터가 아직 공개 전(주말/휴일 직후 정상) |

> **DB 비밀번호를 바꾸고 싶을 때**: `.env` 만 고치면 안 됩니다. DB 안의 비밀번호도 `ALTER ROLE ... PASSWORD`로 바꿔야 합니다. 모르면 질문해 주세요.

---

## 16. 이 문서·구성에서 **확인하지 못한 것** (솔직한 한계)
- **Docker 이미지 실제 빌드와 서버 기동은 클라우드 개발 환경에 Docker 엔진이 없어 시험하지 못했습니다.** 대신 아래를 시험했습니다.
  - ✅ `docker compose config` 문법 검증, 서버에 KIS 관련 변수가 전달되지 않음 확인
  - ✅ DB 계정 3개 생성 스크립트 → 마이그레이션 0001~0014 적용 → **권한 분리**(api_service는 원본 스키마 접근·쓰기 거부, batch_worker는 허용) 실측
  - ✅ 이 DB 구성으로 API 기동·`/api/v1/health`·CORS·보안 헤더 확인
  - ✅ 백업(`pg_dump -Fc`) → 복원(`--no-owner --role=migrator`) → 데이터·소유자·권한 보존 확인, PC DB 덤프를 새 서버 DB에 복원하는 절차 확인
  - ✅ 배포 스크립트의 정상 배포 / 실패 시 롤백 / 동시 실행 차단을 가짜 docker로 시험
  - ✅ **자동 배포(`auto-deploy.sh`)**: 가짜 docker·임시 git 저장소로 78개 항목 시험(새 커밋 감지, 문서만 바뀐 푸시 건너뜀, 코드 푸시 배포, 실패 시 롤백과 재시도 방지, 백업 실패 시 취소, 일시 정지·재개, 다른 배포 중 대기, GitHub 접속 불가, 알림 JSON). 시험이 실제로 결함을 잡는지 변이 시험으로도 확인(`bash deploy/tests/test-auto-deploy.sh`)
  - ❌ **미확인**: ARM(aarch64)에서의 이미지 빌드, `age`·`rclone` 실제 R2 업로드, Caddy 인증서 발급, **서버에서 실제 cron으로 도는 자동 배포**, `read_only` 컨테이너에서 Next.js 동작. **첫 배포 때 이 단계에서 오류가 나면 출력을 그대로 알려 주세요.** 한 번에 고치겠습니다.
- Oracle·R2·DuckDNS의 **2026-10 현재 무료 한도·약관은 공식 페이지에서 직접 확인하지 못했습니다**(블로그·비교 사이트 검색 결과 기준). Oracle 무료 한도는 2026-06에 예고 없이 줄어든 전례가 있습니다.
- 자동 배포는 **서버에서 cron으로 직접 실행한 적이 없습니다**(가짜 환경 시험만). 서버의 GitHub 읽기 접속(배포 키), cron 환경(PATH·HOME), 실제 Docker 빌드 시간 중의 동작은 첫 배포 후 11-3의 동작 시험으로 확인하세요.
- 서버 한 대 구성이라 **그 서버가 멈추면 전체가 멈춥니다**(고가용성 아님). 백업이 유일한 안전망이므로 10번을 꼭 수행하세요.
