# 운영 배포 구성(Oracle VM + R2) 내부테스트 결과서 (DEC-060)

> **갱신(DEC-062)**: 이 결과서의 GitHub Actions 워크플로·승인 환경·`release` 브랜치 관련 항목은 **폐기**되었다(워크플로 삭제). 자동 배포는 서버 폴링 방식으로 대체되었고 시험은 `docs/qa/2026-10-03-auto-deploy-test-result.md`를 본다. DB 계정·백업·복구·PC DB 이전 시험(2~8번)은 그대로 유효하다.

- 작성일: 2026-10-03 (KST) / 브랜치 `PROD_SCH`
- 범위: `deploy/*`, `.github/workflows/deploy-production.yml`, `.dockerignore`, `docs/ops/oracle-deploy-guide.md`
- **중요: 클라우드 개발 환경에는 Docker 엔진이 없어 이미지 빌드·컨테이너 기동은 시험하지 못했다.** 아래 "시험함"은 같은 SQL·스크립트·명령을 임시 PostgreSQL 16과 가짜 docker로 실행한 결과다.

## 1. 시험함 (결과)
| # | 점검 | 방법 | 결과 |
|---|---|---|---|
| 1 | compose 문법·변수 치환 | `docker compose config -q` (더미 env) | 통과. 서버로 전달되는 변수에 `LOCAL_INTRADAY`·`KIS_*` 없음 |
| 2 | DB 계정 생성 스크립트 `01-roles.sh` | 임시 PG16에서 실행 | 역할 3개 생성, DB 소유자 migrator |
| 3 | 마이그레이션 | migrator로 `alembic upgrade head` | 0001→0014 적용 |
| 4 | 권한 분리 | api_service / batch_worker로 접속 | api_service: `raw_internal` 접근·쓰기·`public` 생성 모두 거부, 읽기 허용. batch_worker: `raw_internal` 허용, `public` 생성 거부 |
| 5 | API 기동 | api_service 계정, 공식 기동 스크립트 | `/api/v1/health` ok/db ok, CORS·HSTS·nosniff 헤더 확인, `/docs`는 API 자체에는 있으나 Caddy 설정이 `/api/*`만 전달 |
| 6 | 데이터 적재 | `load_calendar.py`를 batch_worker로 실행 | 730건 반영 |
| 7 | 백업·복구 | `pg_dump -Fc --no-owner` → `pg_restore --no-owner --role=migrator` | 데이터 730건, 소유자 migrator, 권한(api_service 읽기 허용·원본 거부) 보존 |
| 8 | PC DB 이전 절차 | 덤프를 새로 마이그레이션한 DB에 `--clean --if-exists` 복원 | 데이터·버전 0014·권한 보존 |
| 9 | 배포 스크립트 | 가짜 docker + 임시 git 저장소 | 정상 배포, 헬스 실패 시 이전 버전 롤백(`.current_tag` 유지), 백업 호출, **동시 실행 차단** |
| 10 | 설정 생성 `init-env.sh` | 임시 폴더 | 권한 600, 랜덤 비밀 5개 채움, 값 미출력, 기존 파일 덮어쓰기 거부, 미채움 9개 확인 |
| 11 | 워크플로 | YAML 파싱, 로컬에서 같은 단계 실행 | `ruff check services shared scripts tests db` 통과, `pytest` 663 통과·206 건너뜀(DB 필요) |
| 12 | 쉘 스크립트 문법 | `bash -n` | 통과 |

## 2. 시험 중 발견·수정한 문제
1. **CI 게이트 결함**: `tests/integration/test_pattern_derivation_db.py`의 한 테스트가 DB가 없을 때 건너뛰지 않고 실패했다(CI에서 모든 배포를 막았을 것). 다른 통합 테스트와 같은 방식(`TempDbUnavailable` → skip)으로 수정.
2. 워크플로의 `ruff check .`가 `docs/` 프로토타입의 줄 길이 오류 18건으로 실패 → 코드 디렉터리(`services shared scripts tests db`)로 한정.
3. 배포 스크립트가 실행 중에 자기 파일이 `git reset`으로 바뀌는 위험 → 코드 갱신 후 새 파일로 자기 자신을 다시 실행(`DEPLOY_REEXEC`)하도록 변경, 잠금은 상속.
4. 가이드의 "미채움 점검" 명령이 주석까지 세는 문제 → `grep -cE '=(FILL_ME|CHANGE_ME)$'`로 수정.
5. 사용하지 않는 UDP 443 공개 제거.

## 3. 시험하지 못함 (첫 배포에서 확인 필요)
- ARM(aarch64) 이미지 빌드(Python·Node·Alpine 패키지), `npm ci`/`next build` 컨테이너 빌드
- `age`·`rclone`의 실제 R2 업로드·삭제, R2 토큰 권한
- Caddy 인증서 발급(DuckDNS, 80/443, Oracle 보안 목록·iptables)
- `read_only` 컨테이너에서의 Next.js·API 동작(`/tmp`, `/app/.next/cache`만 쓰기 허용)
- GitHub Actions 실제 실행, 환경 승인(production), 강제 명령 SSH 키
- 서버 컨테이너 간 이름 해석(Caddy 별칭으로 웹→API) 및 신뢰 프록시 IP(172.28.0.10) 동작
- 공공데이터·DART 호출이 서버(서울 리전)에서 되는지
- 2026-10 현재 Oracle·R2·DuckDNS의 무료 한도·약관(공식 페이지 미확인)

## 4. 결정 대기·사용자 해야 할 일
- 도메인: DuckDNS 무료 서브도메인 또는 본인 도메인(미정)
- `PRICE_EXPOSURE_ENABLED` 켤지(법률 확인 후, 기본 false)
- 키 재발급(KIS·공공데이터·DART), age 개인키 보관, 계정·서버 생성, GitHub 환경 승인자·Secrets 설정
- 운영 배포 실행 승인(하네스 규칙)
