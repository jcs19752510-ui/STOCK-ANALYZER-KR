# 내부 테스트 결과서 — 마무리 점검(부분 구멍 검사·배너 문구·의존성 취약점·보안·전체 회귀)

- 작성일: 2026-10-06 / 지시: "에이전트가 테스트하고 마무리할 수 있는 모든 작업을 진행" (`CLAUDE.MD` 상시 규칙 5·6)
- 환경: Linux, Python 3.12, PostgreSQL 16 임시 DB, Node 22, Playwright(Chromium), PowerShell 7.4.5(`pwsh`). 실제 증권사·사용자 PC·개발 DB에는 접속하지 않음.

## 1. 이번에 한 일
| # | 작업 | 내용 | 파일 |
|---|---|---|---|
| 1 | **부분 구멍 검사**(DEC-095) | 직전 거래일에 종목이 **일부만** 있어도(그 앞 거래일 종목 수의 50% 미만, 수집이 중간에 끊긴 날) 그다음 날 가공을 보류(`GAP_BLOCKED`). 정확히 50%는 막지 않음(경계). 기존 "전체 구멍" 검사는 그대로 | `services/derivation_batch/{run_derivation,repository}.py` |
| 2 | **배너 문구 정리** | 제외된 종목과 증권사 종가 불일치 종목을 두 문장으로 따로 보이던 것을 "N종목은 증권사 일봉을 쓸 수 없어 결과에서 제외됨 · 그중 M종목은 종가가 달라 뺌(수정주가 불일치 등)" 한 문장으로(서버: 제외 ⊇ 불일치) | `frontend/src/components/LiveScreenPanel.tsx`, `copy.ko.json`, `scripts/qa/live-screen.mjs` |
| 3 | **의존성 취약점 해소** | `npm audit`: `next` 16.3.5에 **치명 1**(next/og ImageResponse 원격 코드 실행, GHSA-vcvr-r3jv-pc5j)·`source-map-js` 높음 1(GHSA-68fv-2mgg-jv7q). 이 앱은 `next/og`를 쓰지 않아(검색 결과 0건) 실제 노출은 없었지만 `next` 16.3.8로 올려 **0건**. 윈도우용 SWC 바이너리 항목도 잠금 파일에 그대로 유지(6개) | `frontend/package-lock.json` |
| 4 | 보안 점검 | §3 | — |
| 5 | CLAUDE.MD 상시 규칙 5·6, 시험 환경 만들기 절차 기록 | 새 컨테이너에서 에이전트가 스스로 환경을 만들 수 있게 | `CLAUDE.MD` |

## 2. 시험 결과
| 구분 | 명령/파일 | 결과 |
|---|---|---|
| 부분 구멍 검사(실제 DB) | `tests/integration/test_gap_guard_db.py` | 4/4 통과(경계 50%·30% 포함) |
| 배치·가공 회귀 | `test_daily_batch_e2e`, `test_pattern_derivation_db` | 통과 |
| 장중 기준 화면 — 개발 서버 | `node scripts/qa/live-screen.mjs dev` | **160/160** |
| — 운영 빌드 | `... prod` | **17/17** |
| — 로그인 켠 로컬 대행 | `... auth` | **26/26** |
| 장중 기준 종단(실제 API·모의 증권사·DB) 개발 / 운영 | `python tests/e2e/live_screen_stack.py [--prod]` | **29/29** / **6/6** |
| 로그인 켠 로컬 종단 / 끈 로컬 종단 | `local_mode_stack.py --mode on / off` | **61/61** / **9/9** |
| 갱신 화면(API 꺼짐 안내) 재현 | `renew-dev-check.mjs` | 안내 문구 0.7초 만에 표시(성공) |
| PowerShell 실행 시험 | `tests/e2e/ps1_scripts_check.py` | **22/22** |
| 프런트 정적 | `tsc --noEmit`, `eslint`, `lint:copy`(164파일), `check-*.mjs` 16개 | 통과 |
| 전체 회귀 | `pytest tests` | **1,469 passed, 1 skipped, 0 failed**(336초) |
| 정적 검사 | `ruff check services scripts shared tests` | 통과 |

## 3. 보안 점검 (20년차 보안담당자 기준, 이번에 추가·변경한 코드 중심)
| 항목 | 방법 | 결과 |
|---|---|---|
| 의존성(프런트 운영 의존성) | `npm audit --omit=dev` | 치명 1·높음 1 → **0건**(`next` 16.3.8) |
| 의존성(파이썬) | `pip-audit -r requirements.txt` | 알려진 취약점 없음 |
| 정적 분석 | `bandit -ll`(새 서비스·API·배치·도구) | 중간 이상 지적 0건 |
| 비밀값 하드코딩 | 키·토큰·비밀번호 패턴 검색 | 0건 |
| SQL 인젝션 | 새 코드의 문자열 결합 SQL 검색 / 가상 테이블 | 결합 없음, 값은 바인드 파라미터 1개로만(시험: 따옴표·SQL 조각이 든 값이 구조를 못 바꿈) |
| 접근 통제 | `/local/screen*` 의존성 | 소유자 전용(`require_owner`) — 로컬 모드 꺼짐 시 404, 일반 사용자 403(종단 시험으로 확인) |
| 입력 검증 | `snapshot_id` | 32자리 16진수만, 그 밖 400/422 |
| 정보 노출 | 응답·화면 | 원본 시세 필드·증권사 응답 필드·토큰·앱키 없음(종단 시험) |
| 서비스 거부 | 계산 폭주 | 최소 계산 간격 재사용·단일 비행 잠금·우선 순환 상한 200·호출 한도(로컬 분당 600) |

## 4. 확인하지 못한 것·남은 위험
| # | 내용 |
|---|---|
| 1 | 실제 증권사 응답(일봉·실시간·조건검색·수급 필드/단위) — 앱키 없음 |
| 2 | 사용자 PC의 Windows PowerShell 5.1·실제 작업 스케줄러 — 대역으로만 확인 |
| 3 | 2027 휴장일의 KRX 공식 확정 — 공고 미발표(추정 초안) |
| 4 | 부분 구멍 기준 50%는 경험값이다. 시장 전체 거래정지 같은 드문 날에는 오탐으로 가공이 보류될 수 있으며 `--allow-gap`으로 해소한다. 실제 종목 수 추이로 보정 가능 |
| 5 | `docs/pattern-screening/prototype/pattern_rules_reference.py`의 ruff 지적 18건은 이번 작업 이전부터 있던 참고용 프로토타입(제품 코드 아님) |
