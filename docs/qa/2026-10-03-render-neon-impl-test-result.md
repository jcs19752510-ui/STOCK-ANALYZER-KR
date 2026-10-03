# Render + Neon 무료 베타 구현 내부시험 결과서 (DEC-063)

- 작성일: 2026-10-03 / 시험 환경: 샌드박스(Linux), Python 3.12, PostgreSQL 16(로컬 임시 인스턴스), Node 22, Chromium(Playwright)
- 범위: 사용자가 선택한 4가지 결정(배치 PC 주+Actions 보조 / 정리 안 함 / 깨우는 중 안내 / 프록시 대역 확인 전 공개 보류)의 구현.
- **실제 Render·Neon·GitHub Actions·R2에는 접속하지 않았습니다.** 그 부분은 §6 "미확인"에 따로 적었습니다. 운영 배포는 수행하지 않았습니다.

## 1. 결론

| 구분 | 결과 |
|---|---|
| 코드·스크립트 시험 | **전부 통과** (아래 §3) |
| 기존 기능 회귀 | 없음 — 전체 893건 통과(단위+통합), 기존 기본 동작(시간 제한 3초/3초/4.5초, 프록시 신뢰 기본 꺼짐) 불변 |
| 외부 서비스 실동작 | **미확인** (Render/Neon/Actions는 사용자 계정에서 첫 실행으로만 확인 가능). 공개 전 점검표(절차서 §9)로 확인 |
| 공개 가능 여부 | **아직 아님** — Render 프록시 대역 확인(§7)과 점검표 10항목 통과 후 |

## 2. 변경 내역

| 구분 | 파일 | 내용 |
|---|---|---|
| 백엔드 | `services/public_api/api/health.py` | `GET /api/v1/live` — DB 미사용(Neon을 깨우지 않는 헬스체크용) |
| | `services/public_api/core/config.py`, `db/session.py`, `main.py` | DB 연결/쿼리/요청 시간 제한을 환경변수로 조정(기본값 불변, 범위 밖/비숫자는 `ConfigError`) |
| | `services/public_api/middleware.py`, `main.py` | `PeerDiagnosticsMiddleware`: `PUBLIC_API_LOG_PEER_IPS=1`일 때만, 처음 20건의 peer·X-Forwarded-For 기록(헬스체크 제외) |
| | `scripts/run_public_api.py` | `PUBLIC_API_REQUIRE_TRUSTED_PROXY=true`인데 `PUBLIC_API_TRUSTED_PROXY_IPS`가 비면 **기동 거부**(종료코드 1) |
| 배치 | `shared/batch_lock.py`, `scripts/run_daily_batch.py` | PostgreSQL 세션 advisory lock으로 PC/Actions 중복 실행 방지. 이미 실행 중이면 양보(종료코드 0). 락 확인 실패는 경고 후 계속. `--dry-run`/`--no-lock`은 락 생략 |
| DB | `deploy/render/neon-setup.sql` | `batch_worker`/`api_service` 생성(재실행 안전) — Neon 소유자가 마이그레이터 역할 대행 |
| 배포 | `deploy/render/pre-deploy.sh` | 백업(기존 `backup.sh` 재사용) → `alembic upgrade head`. 풀러 주소 거부, 백업 설정 일부만 있으면 중단, `--backup-only` |
| | `.github/workflows/render-deploy.yml` | PROD_SCH 푸시(문서/테스트 제외) → pre-deploy → Render Deploy Hook. Secrets 없으면 "건너뜀" |
| | `.github/workflows/scheduled-batch.yml` | 보조 스케줄(배치 2회, 신선도, 백업) + 수동 실행(dry-run 포함), 종료코드 2(공공데이터 미배포)는 성공 처리 |
| | `render.yaml` | Blueprint: 싱가포르·무료·docker, 자동배포 끔, 헬스체크 `/api/v1/live`, 비밀값 `sync:false` |
| 프런트 | `src/lib/apiWake.ts`, `components/ApiWakeNotice.tsx`, `layout.tsx`, `globals.css`, `copy.ko.json` | API 요청이 4.5초 넘게 걸리면 `role="status"` 안내 배너 |
| | `src/instrumentation.ts` | 운영 서버 시작 시 API `/api/v1/live`를 1회 호출(웹·API 동시 기상) |
| 문서 | `docs/ops/render-neon-guide.md`, `docs/harness/decisions.md`(DEC-063) | 절차서·결정 기록 |

## 3. 시험 결과

### 3-1. 자동 시험 요약

| 시험 | 건수 | 결과 |
|---|---|---|
| pytest 전체(단위 659 + 통합 + 신규) | 893 | **통과** (임시 PG 사용, 119초) |
| 신규 `tests/unit/test_render_neon_support.py` | 24 (실제 PG 락 1 포함) | **통과** |
| `deploy/tests/test-pre-deploy.sh` | 21 | **통과** |
| `deploy/tests/test-auto-deploy.sh`(회귀) | 78 | **통과** |
| 프런트 `node --test scripts/check-*.mjs` | 9개 파일 66건(신규 `check-api-wake.mjs` 6) | **통과** |
| Playwright `qa/wake-notice.mjs` | 26 | **통과** |
| `ruff check`(services scripts shared tests db), `tsc --noEmit`, `eslint src`, 금지표현 검사 | — | **오류 0** |
| `npm run build`(운영 빌드) | — | 성공 |

### 3-2. 항목별 시험 (핵심)

| # | 시험 | 기대 | 결과 |
|---|---|---|---|
| 1 | 시간 제한 기본값 | 3 / 3000 / 4.5 | 통과 |
| 2 | 환경변수 지정(10, 8000, 12.5) | 반영 | 통과 |
| 3 | 잘못된 값(문자, 0, 31, 100ms, -1, 999) | `ConfigError` | 6건 통과 |
| 4 | 빈 값(공백) | 기본값 | 통과 |
| 5 | `/api/v1/live` | DB 의존성을 "호출 시 실패"로 바꿔도 200 | 통과 |
| 6 | 프록시 진단 | 처음 20건만 기록, `/api/v1/live` 제외, 헤더 값 포함 | 통과 |
| 7 | `REQUIRE_TRUSTED_PROXY=true` + 대역 없음 | 서버 시작 안 함, 종료코드 1, 안내문 | 통과 |
| 8 | `REQUIRE=true` + `10.0.0.0/8` | 시작, `proxy_headers=True` | 통과 |
| 9 | 플래그 없음 | 기존 동작(`proxy_headers=False`) | 통과 |
| 10 | 배치 락(가짜 연결) | 획득→해제 / 다른 실행 보유→양보 / URL 없음·연결 오류→계속 진행 | 5건 통과 |
| 11 | 배치 `main()` | 락 보유 시 `_main_locked` 미호출·종료 0, `--dry-run`/`--no-lock`은 락 우회 | 3건 통과 |
| 12 | **실제 PostgreSQL 상호배제** | 첫 실행 ACQUIRED, 동시 두 번째 HELD, 해제 후 다시 ACQUIRED | 통과 |
| 13 | Neon 환경 모사(비슈퍼유저 `CREATEROLE` 소유자) `neon-setup.sql` 2회 실행 | 오류 없음(재실행 안전) | 통과 |
| 14 | 위 DB에서 `alembic upgrade head` | 0014까지 적용 | 통과 |
| 15 | 권한: `api_service`로 `raw_internal` 조회 / `public`에 테이블 생성 | 거부 | 거부 확인 |
| 16 | 권한: `batch_worker`로 `raw_internal.raw_ohlcv` 조회 | 허용 | 확인 |
| 17 | **덤프 복원 리허설**: 로컬 구성과 같은 소유자(migrator)의 DB를 `pg_dump -Fc` → Neon 모사 DB에 `pg_restore --no-owner --exit-on-error` | 오류 0, 데이터·권한 유지, `alembic current`=0014 | 통과 |
| 18 | pre-deploy: URL 없음/접두어 오류/풀러 주소 | 종료 2, 아무것도 실행 안 함 | 통과 |
| 19 | pre-deploy: 백업 변수 일부만 설정 | 종료 2, 아무것도 실행 안 함 | 통과 |
| 20 | pre-deploy: 백업 없음 | 경고 후 마이그레이션 진행 | 통과 |
| 21 | pre-deploy: 전부 설정 | 백업이 마이그레이션보다 먼저, URL 분해(호스트·포트·DB·사용자·SSL), 비밀번호 출력 없음 | 통과 |
| 22 | pre-deploy: 백업 실패 / 마이그레이션 실패 | 종료 1, 백업 실패 시 마이그레이션 미실행 | 통과 |
| 23 | pre-deploy `--backup-only`(성공/변수 없음/실패) | 마이그레이션 미실행, 변수 없으면 종료 2 | 통과 |
| 24 | 워크플로 YAML 구문 | 두 파일 파싱 | 통과 |
| 25 | 안내 로직: 임계 전 종료 / 초과 / 다중 요청 / 중복 종료 / 외부 요청 무시 / 오류 전파 / 복원 | 기대대로 | 6건 통과 |
| 26 | 화면: 6.5초 지연 → 4.5초 뒤 표시, 1초 시점엔 없음, 응답 후 사라짐(360·1280px) | 통과, 가로 넘침 없음, axe 위반 0 | 통과 |
| 27 | 화면: 느린 후 500 오류 | 안내는 사라지고 오류 화면 | 통과 |
| 28 | 화면: 0.3초 응답 | 안내 없음 | 통과 |
| 29 | 운영 빌드 후 `next start` | 시작 직후 API `/api/v1/live` 1회 호출 확인 | 통과 |

## 4. 구현 중 발견·수정한 문제

| # | 문제 | 조치 |
|---|---|---|
| 1 | 새 한글 주석이 줄 길이 제한(100자)을 넘음(린트 8건) | 줄 정리 |
| 2 | 기본 `python3`(3.11)로는 기존 테스트가 문법 오류 — 프로젝트는 3.12 이상 | 3.12 가상환경으로 시험(프로젝트 요구사항과 일치, 코드 문제 아님) |
| 3 | GitHub Actions의 `run` 기본 쉘이 `-e`라서 `cmd; rc=$?` 패턴이 실패 시 즉시 중단 → 종료코드 2 예외 처리가 무력 | 해당 단계에 `set +e` 추가 |
| 4 | `: "${VAR:?}" \|\| die` 패턴이 비대화형 쉘에서 의도한 종료코드를 내지 못함 | 명시적 검사로 교체, 시험 1번이 이를 보증 |
| 5 | 시험 중 `pkill -f`가 시험 쉘을 종료(종료코드 144) | 결과 확인 후 pid 기반 종료 사용 |

## 5. 설계상 주의(사실 그대로)

1. **세션 락의 한계**: Neon이 연결을 끊거나 컴퓨트가 정지하면 락이 풀립니다. 매우 긴 배치 중 이런 일이 생기면 드물게 중복 실행이 가능합니다. 데이터는 멱등 upsert라 깨지지 않고 API 호출량만 늘어납니다.
2. **서버 렌더링 대기 구간**: "깨우는 중" 안내는 브라우저에서 보내는 API 요청에만 뜹니다. 웹 서비스 자체가 잠든 첫 접속은 Render가 보여주는 대기 화면이며, 서버에서 API를 부르는 화면은 응답이 올 때까지 빈 화면일 수 있습니다. 웹 기동 시 API를 함께 깨우는 장치로 줄였지만 없애지는 못했습니다.
3. **스키마 먼저**: 마이그레이션이 새 코드 배포보다 먼저 적용되므로, 배포 사이 짧은 시간 구버전 코드가 새 스키마를 봅니다. 현재 14개 마이그레이션은 모두 추가형이며, 앞으로도 추가형 변경만 허용해야 합니다(절차서 §11).
4. **로그에 IP 기록**: `PUBLIC_API_LOG_PEER_IPS`는 방문자 IP를 로그에 남기므로 확인 후 반드시 끄도록 절차서에 명시했습니다.
5. **보조 스케줄 신뢰도**: GitHub 스케줄은 15~30분 지연될 수 있고, 60일간 활동이 없으면 꺼집니다. 그래서 PC를 주 실행으로 둡니다.

## 6. 미확인 목록 (사용자 환경에서 확인해야 함)

| # | 항목 | 확인 방법 |
|---|---|---|
| 1 | Render 프록시의 실제 IP 대역 | 절차서 §7 (`PEER-DIAG` 로그). **확인 전 공개 보류** |
| 2 | Render가 화면에서 입력한 `NEXT_PUBLIC_API_BASE_URL`을 Docker 빌드에 전달하는지 | 첫 배포 후 브라우저 개발자도구에서 API 호출 주소 확인. 안 되면 빌드 인자 방식으로 변경 |
| 3 | `render.yaml`의 `autoDeployTrigger: "off"` 키 이름·동작 | Blueprint 생성 시 오류/경고 확인 |
| 4 | 미국 GitHub 실행기에서 공공데이터포털·DART 접속 | Actions `dry-run` 수동 실행 |
| 5 | Neon 무료 한도(저장 용량 0.5GB/1GB, 컴퓨트 시간) 및 직접 주소에서의 `options`(statement_timeout) 처리 | Neon 콘솔 Usage, 첫 접속 확인 |
| 6 | Render 무료 사양(0.1 CPU)에서의 응답 속도 | 점검표 6번 |
| 7 | 잠든 Neon을 깨우는 실제 시간이 10초(설정값) 안인지 | 점검표 6번 후 필요하면 환경변수 조정 |
| 8 | 가격·한도 수치는 모두 검색 결과 기준(공식 페이지는 샌드박스에서 열 수 없음) | 가입 화면에서 직접 확인 |
| 9 | R2 백업 업로드·복원 실동작 | 점검표 5·10번 |

## 7. 사용자 몫(제가 대신할 수 없는 일)

키 재발급(KIS·공공데이터포털·DART), Neon·Render·Cloudflare 가입과 화면 입력, GitHub Secrets 등록, PC `.env` 전환, 월요일 장중 시간 확인, 법률·약관 검토(REQ-022/Q4), Oracle 지원 답변(~10/8) 후 VPS 전환 여부 결정. 단계별 방법은 `docs/ops/render-neon-guide.md`에 있습니다.
