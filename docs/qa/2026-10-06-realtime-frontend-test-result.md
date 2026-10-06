# 내부 테스트 결과서 — 종목 상세 실시간 화면 (DEC-084 A3)

- 일자: 2026-10-06 / 대상: 로컬 모드(내 PC) 전용. 운영(Render) 빌드는 변경 없음(라이브 UI·스트림 요청 0건 확인).
- 배포 필요: 없음(운영에서 꺼진 기능). DB 변경 없음.

## 1. 변경 요약
- `frontend/src/lib/liveStream/*`: 스트림 상태 저장(100ms 묶음), 반영 규칙(중복 제거·순서 뒤바뀜·분봉 병합·거래일 변경), N분봉·N틱 묶기, EventSource 수명 관리(연결 1개, 거절 시 JSON 오류 확인, 3회 연속 실패 시 폴링 복귀).
- 현재가·호가·체결·분/틱 차트가 스트림 값으로 갱신되고 폴링하지 않음. 배지(연결됨/재연결 중/끊김), 값 변경 강조(reduced-motion 시 생략).
- 시험 보조: `frontend/scripts/check-live-stream.mjs`, `frontend/scripts/qa/live-stream.mjs`. 로컬 모드 종단 시험은 모의 웹소켓을 함께 띄우고 "폴링 없이 스트림 1건" 기대값으로 갱신(`tests/e2e/local_mode_stack.py`, `frontend/scripts/qa/local-login-e2e.mjs`).

## 2. 시험 결과
| 항목 | 결과 | 실행자 |
|---|---|---|
| `check-live-stream.mjs`(reducer·묶기·store·controller) | 42/42 | 에이전트 |
| 기존 `check-*.mjs` 전체 | 163/163 | 에이전트, 메인 재실행 통과 |
| eslint / tsc / lint:copy(145파일) | 통과 | 메인 재실행 |
| `npm run build` | 통과 | 메인 재실행 |
| 실제 스택 `live-stream.mjs dev`(갱신·폴링 0·연결 1·재연결·해지·한도·폭 320~1280·axe 위반 0) | 64/64 | 에이전트 |
| 실제 스택 `live-stream.mjs prod`(운영 빌드에 라이브 UI 없음) | 7/7 | 에이전트 |
| `tests/e2e/local_realtime_stack.py` | 18/18 | 메인 |
| `tests/e2e/login_stack.py` | 322/322 | 메인 |
| `tests/e2e/local_mode_stack.py --mode on`(실제 종목 상세 페이지·DB 포함) | 26/26 | 메인 |
| `tests/e2e/local_mode_stack.py --mode off` | 9/9 | 메인 |
| tests/unit 전체 | 952 passed, 1 skipped | 메인 |

## 3. 발견·수정한 결함
- 첫 snapshot 직후 오류 시 "재연결 중"이 "연결 중"으로 표시 → `store.hasSnapshot()` 추가.
- 현재가 강조 배경이 대비 위반(axe) → 숫자 둘레 고리 방식으로 변경.
- 차트 읽기 줄 `aria-live`가 초당 여러 번 낭독 → 봉 미선택 동안 `off`.
- 로컬 종단 시험 스택에 모의 웹소켓이 없어 호가 표가 비어 시험 실패 → 모의 웹소켓 추가, 폴링 전제 기대값을 스트림 전제로 갱신.

## 4. 확인하지 못한 것·한계
1. 실제 증권사 응답(접속 차단). 장중에 사용자가 `kis_ws_smoke_test.py`로 확인해야 함.
2. `frontend/scripts/qa/basis-wording.mjs`는 DB 스택에서 재실행·기대값 갱신 필요(스트림이 켜진 상태에서 "일 선택" 시 라이브 안내가 유지됨).
3. 증권사 웹소켓이 붙지 못하는 경우(키 오류 등) 화면이 "대기" 상태로 남을 수 있음(배지로 안내, 폴링 복귀는 서버 거절 404/403/503일 때). 장중 확인 시 관찰 필요.
4. 연결이 조용히 멈추는 경우 배지가 "연결됨"으로 남을 수 있음(마지막 수신 시각으로 판단).
5. 백엔드 개선 요청(미반영): 거래일 변경 시 새 snapshot 전송, 장 시작 전 이전 거래일 분봉 혼합 제거, snapshot의 `quote`를 REST 현재가로 채우기.
