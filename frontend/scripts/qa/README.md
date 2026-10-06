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
- live-stream.mjs : 실시간 스트림 화면(DEC-084). 모의 KIS REST(4413)·모의 KIS 웹소켓(4414, 스크립트가 직접 띄우고 끊었다 켬)·API(4411)·프런트(4412)로
  `dev`(갱신·폴링 0건·연결 1개·재연결·구독 해지·한도·폭·axe) / `prod`(운영 빌드에는 라이브 UI·스트림 요청 없음) 두 단계. DB 없이 열리도록
  `live-stream-harness.page.tsx`를 `src/app/qa-live/page.tsx`로 복사해 쓰고 끝나면 지운다(자세한 실행 방법은 스크립트 맨 위 주석).
- psearch-screen.mjs : 증권사 조건검색 화면(DEC-088). 계약서 모양의 **가짜 JSON 서버를 스크립트가 직접 띄우고**(4511), `next dev`(`dev` 단계, 로컬 플래그 켬)·`npm run build`+`next start`(`prod` 단계, 플래그 없음)도 직접 띄웠다 PID로 끝낸다(4512). 표·자동 갱신·신규 표지·간격·탭 가림·상태 안내·폭·axe·접근 불가 숨김(dev) / 전환 항목·화면 내용·`/psearch` 요청 0건(prod). 임시 파일은 `/tmp/claude-0/qa-psearch`에만 남긴다.
- live-screen.mjs : 장중 기준 재계산 화면(DEC-089). 계약서 모양의 **가짜 JSON 서버**(`live-screen-mock.mjs`, 4611)와 프런트(4612)를 스크립트가 직접 띄우고 PID로 끝낸다. `dev`(로컬 플래그: 전환·배너·자동 갱신·일시정지·410·오류·폭·axe·스크린샷), `prod`(운영 빌드: 전환·요청 0건 + 번들 문자열 검사), `auth`(로그인 켠 로컬 빌드: 웹 서버 대행 허용·관리자 전용·쿼리 길이·일반 회원 비노출). 결과는 `/tmp/claude-0/qa-live-screen/result-*.json`.

## 주의: API 요청 한도(429)
공개 API는 IP당 분당 60회로 제한된다(`PUBLIC_API_RATE_LIMIT_PER_MINUTE`). QA 스크립트를 연달아 돌리면 한도를 넘어 429가 나고, 화면이 오류 상태가 되어 `관심종목에 추가` 버튼을 못 찾는 등 **간헐적 실패**가 생긴다(2026-10-03 확인: 실패 시 로그에 429). QA용 API는 `PUBLIC_API_RATE_LIMIT_PER_MINUTE=100000`으로 기동한다(운영에는 적용하지 않는다).
