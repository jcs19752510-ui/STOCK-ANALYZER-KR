# 화면 검수 자동 점검 스크립트 (QA)

저장소 의존성에 포함하지 않는다. 별도 디렉터리에 설치해서 사용한다.

```
mkdir -p /tmp/claude-0/pw && cd /tmp/claude-0/pw
npm i playwright-core axe-core --no-audit --no-fund
# 브라우저: /opt/pw-browsers/chromium-1194/chrome-linux/chrome (환경변수 CHROME 으로 변경 가능)
```

전제: API(4201)·프론트(4202) 기동, 시드 데이터(T00001...), 접속은 http://localhost:4202.
실행: `node frontend/scripts/qa/<script>.mjs` (설치 위치가 다르면 QA_PW_DIR=<경로>)

- matrix.mjs   : 페이지×뷰포트 가로 넘침/잘림/겹침/터치 대상/axe → out/matrix.json
- devices.mjs  : iPhone 13 / Pixel 7 에뮬레이션 상호작용
- keyboard.mjs : 키보드 접근성
- theme.mjs    : 다크·forced-colors·200% 줌·reduced-motion 캡처
- local.mjs    : 로컬 모드(NEXT_PUBLIC_LOCAL_INTRADAY_ENABLED=true 빌드) 화면
- accuracy.mjs : 화면 값 ↔ API 값
