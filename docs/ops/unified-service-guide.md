# 통합 서비스(웹+API 1개) 전환 절차서 (DEC-078)

> 목적: Render 서비스 2개(`stock-analyzer-web`, `stock-analyzer-api`)를 **1개**(`stock-analyzer-web`)로 줄여 비용을 낮춘다. 주소는 그대로(`stock-analyzer-web-q7cx.onrender.com`).
> 코드·이미지·블루프린트는 준비가 끝났고 내부 시험을 마쳤다(결과: `docs/qa/2026-10-06-unified-service-test-result.md`). **Render 사이트에서 직접 해 봐야만 알 수 있는 것**(첫 이미지 빌드, 메모리 실측)은 §5에 따로 적었다.

## 1. 구조

```
브라우저 ─▶ Render 서비스 1개(컨테이너 1개)
              ├ 웹(Next.js)  : 공개 포트(PORT)        ← 외부에 열린 것은 이것 하나
              └ API(FastAPI) : 127.0.0.1:8000(내부)   ← 같은 컨테이너 안에서 웹 서버만 호출(내부 토큰)
                              └▶ Neon DB
배치(내 PC·GitHub Actions) ─▶ Neon DB 직접 (API를 거치지 않으므로 영향 없음)
```

- 진입점: `scripts/run_unified.py` — API를 먼저 띄우고 `/api/v1/live`가 응답한 뒤 웹을 띄운다. 한쪽이 죽으면 전체를 종료해 Render가 재시작한다.
- 이미지: `deploy/unified.Dockerfile`. 블루프린트: `render.yaml`(2026-10-06 통합 구성으로 교체됨. 이전 2개 서비스 구성은 `deploy/render/render.two-services.yaml`).

## 2. 전환 절차 (사용자 작업은 ①②④ 세 가지)

| 순서 | 누가 | 할 일 |
|---|---|---|
| ① | 사용자 | Render → `stock-analyzer-api` → Environment 에서 **`PUBLIC_API_DATABASE_URL`, `PUBLIC_API_AUTH_DATABASE_URL`** 값을 복사해 → `stock-analyzer-web` → Environment 에 **같은 이름으로 추가**(Add) 후 저장. (저장하면 Render가 재배포를 시작할 수 있다. 아직 기존 이미지라 값이 추가될 뿐 동작은 바뀌지 않으니 그대로 두면 된다.) |
| ② | 사용자 | "①을 마쳤다"고 알려 준다. |
| ③ | 에이전트 | `render.yaml`을 통합 구성으로 교체해 `PROD_SCH`에 푸시한다(Render가 서비스 설정을 동기화한다). **완료(2026-10-06)** |
| ④ | 사용자 | `stock-analyzer-web` → **Manual Deploy → Deploy latest commit**. 빌드가 끝나면 알려 준다. |
| ⑤ | 에이전트 | 주소로 `/healthz`, `/auth/status`, 로그인, 스크리너 조회를 확인하고 결과를 보고한다. |
| ⑥ | 사용자 | 이상이 없으면 `stock-analyzer-api` 서비스를 삭제(또는 Suspend)한다. **확인 전에는 삭제하지 않는다.** |

기존 값(`AUTH_REQUIRED`, `SESSION_SECRET`, `PUBLIC_API_INTERNAL_TOKEN` 등)은 그대로 유지된다. `NEXT_PUBLIC_API_BASE_URL`은 블루프린트가 `http://127.0.0.1:8000`으로 바꾼다.

## 3. 롤백

- ⑥ 전까지는 기존 `stock-analyzer-api`가 살아 있다. 문제가 생기면 `deploy/render/render.two-services.yaml` 내용을 `render.yaml`로 되돌려 푸시하고 웹을 다시 배포하면 이전 구조(웹+API 2개)로 돌아간다(웹의 `NEXT_PUBLIC_API_BASE_URL`을 API 서비스 주소로 되돌려야 한다).
- ⑥ 이후에는 API 서비스를 새로 만들어야 하므로 롤백 비용이 크다. 그래서 검증 후에 삭제한다.

## 4. 동작 차이 (알아 둘 것)

- 잠든 뒤 첫 접속: 이전에는 웹이 깨어난 뒤 API가 또 깨어났다(이중 대기). 이제 컨테이너 하나가 깨어나는 시간만 기다린다(대략 1분 안팎, 같은 서비스에서 API 준비 후 웹이 뜨므로 그 사이는 Render가 기다리게 한다).
- 메모리: 무료 서비스 512MB. 실측값은 시험 결과서 §4. 웹의 힙은 256MB로 제한했다.
- 로그: 한 서비스 로그에 `[unified]`(기동기), API, 웹 로그가 함께 나온다.

## 5. 이 환경에서 확인하지 못한 것 (솔직한 한계)

- 시험 환경에는 Docker가 없어 **이미지를 실제로 빌드하지 못했다.** Dockerfile은 경로·명령을 정적으로 점검했고, 같은 프로세스 구성을 `run_unified.py`로 직접 실행해 E2E를 통과시켰다. Render의 **첫 빌드에서 Dockerfile 문제가 나올 수 있으며**, 그 경우 로그를 알려 주면 바로 고친다(운영에는 영향이 없다 — 빌드 실패 시 기존 버전이 유지된다).
- Render 무료 서비스의 실제 메모리 사용량(512MB 한도)은 Render에서만 확인할 수 있다.

## 6. 유료 전환 (2026-10-06)

- `render.yaml`의 `plan`을 `starter`로 맞췄다(Blueprint가 관리하는 서비스는 대시보드에서만 바꾸면 다음 동기화 때 되돌아갈 수 있다).
- 유료 인스턴스는 15분 유휴 후 잠들지 않으므로 콜드스타트(첫 접속 30초대)가 사라진다. 메모리 한도는 실측 약 245MB 대비 충분한지 Render Metrics로 확인한다.
- 프로젝트("My project")로의 이동은 유료 전환과 무관하다(분류용).
