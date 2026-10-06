# 운영 자동 배포(B안) 내부 시험 결과서 (DEC-081)

- 일자: 2026-10-06 / 브랜치: `PROD_SCH`
- **배포 관련 안내**: 이 변경 자체가 "자동 배포 켜기"다. 푸시 후 Render가 블루프린트를 동기화해 설정이 바뀐다. 이 푸시가 곧바로 배포로 이어질지는 Render 동작에 달려 있어(§5), **몇 분 안에 Render → `stock-analyzer-web` → Events에 새 배포가 안 보이면 Deploy latest commit을 한 번만 눌러 주세요.** 그 뒤 푸시부터는 자동이다.
- 요청(사용자): "Deploy latest commit 작업을 자동으로 진행할 수 있는 방법" → A/B 제시 → "B로 진행".
- 결론: **설정 변경과 정적·단위 시험은 통과. 실제 Render 자동 배포 동작은 이 환경에서 확인할 수 없다(§5).**

## 1. 변경 요약
| 파일 | 내용 |
|---|---|
| `render.yaml` | `autoDeployTrigger: "off"` → `"commit"`(+ 주석). 나머지 설정(브랜치 `PROD_SCH`, `healthCheckPath: /healthz`, 플랜 `starter`, 환경변수) 불변 |
| `tests/unit/test_unified_deploy_files.py` | 블루프린트 기대값을 `off`→`commit`으로 갱신 |
| `docs/ops/unified-service-guide.md` §7, `docs/ops/render-neon-guide.md`, `docs/HANDOFF.md`, `docs/harness/decisions.md`(DEC-081) | 자동 배포 방식, 주의점, 끄는 법, 옛 Deploy Hook 절차가 더 이상 필요 없다는 안내 |

## 2. 시험 결과
| 항목 | 결과 |
|---|---|
| `render.yaml` YAML 구문·값(`autoDeployTrigger=commit`, `branch=PROD_SCH`, `healthCheckPath=/healthz`) | PASS |
| 배포 파일 정적 시험 `test_unified_deploy_files.py` | 11건 통과 |
| 전체 단위 시험(파이썬 3.12) | 791건 통과, 1건 건너뜀(기존과 동일) |
| `ruff check` | 이번 변경 파일 통과. 저장소 전체 18건은 `docs/pattern-screening/prototype/pattern_rules_reference.py`(문서 참고용 파일)이며 변경 전후 동일(기존 항목) |

## 3. 위험과 대응
| 위험 | 대응 |
|---|---|
| DB 구조(마이그레이션)가 자동 적용되지 않음. 컨테이너가 기동 때 alembic을 돌리지 않는다(`deploy/unified.Dockerfile`, `scripts/run_unified.py` 확인) | 문서화(§7). DB를 바꾸는 커밋은 푸시 전에 먼저 적용. 현재 코드는 마이그레이션 0018까지 필요하고 운영 DB에 이미 적용돼 있음(로그인 정상 동작으로 확인됨) |
| 잘못된 코드가 푸시되면 바로 운영에 배포됨 | `/healthz` 실패 시 기존 버전 유지, 빌드 실패 시 기존 버전 유지. 배포 전 시험은 푸시 전에 이 저장소의 시험으로 수행. 끄려면 `"off"`로 되돌림 |
| 이중 배포(GitHub Actions + Render) | Secrets `RENDER_DEPLOY_HOOK_WEB` 미등록 유지(현재 미등록이라 Actions는 "건너뜀"). 문서에 명시 |
| 문서만 바꿔도 재배포 | 허용(영향 작음). 줄이려면 `buildFilter.ignoredPaths`를 별도 결정으로 추가 |

## 4. 되돌리는 법
`render.yaml`의 `autoDeployTrigger`를 `"off"`로 바꿔 푸시.

## 5. 시험하지 못한 것 (숨기지 않고 적는다)
| 항목 | 이유 | 확인 방법 |
|---|---|---|
| Render가 푸시마다 실제로 자동 배포하는지 | 이 환경에서 Render를 조작·관찰할 수 없음 | 이 커밋 푸시 후 Render Events에 새 배포가 시작되는지. 안 보이면 Deploy latest commit 1회, 다음 푸시(문서 한 줄이라도)에서 자동 시작되는지 확인 |
| 블루프린트 동기화로 `commit` 값이 반영되는지 | 동일 | Render → 서비스 Settings → Build & Deploy → Auto-Deploy가 "On Commit"인지 |
| 이 푸시 자체가 배포를 일으키는지 | 설정 반영 시점과 푸시 이벤트의 선후를 Render 쪽에서만 알 수 있음 | 위와 같음 |
