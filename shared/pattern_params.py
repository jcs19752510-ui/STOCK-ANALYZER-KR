"""패턴 스크리닝 "급등 전 압축주" 계산 파라미터 (REQ-030, 02-system-design.md §3-2).

**고정 상수다 — 바꾸면 `derived_metrics_daily`의 패턴 지표를 재계산해야 한다**(판정 임계값과 다름:
판정 임계값은 조회 시점에 적용되는 설정값으로 `PATTERN_*` 환경변수, 설계서 §3-3). 배치
(`services/derivation_batch`)와 API(응답 `definition.calc` 노출)가 같은 값을 공유하도록
`shared/`에 둔다.

값은 실행 가능한 기준 구현(`docs/pattern-screening/prototype/pattern_rules_reference.py`)과 1:1이다
(`tests/unit/test_pattern_compute.py::test_params_match_design_and_oracle`이 드리프트를 막는다).
"""

from __future__ import annotations

from decimal import Decimal

# ── 횡보(c1) ────────────────────────────────────────────────────────────────────
PATTERN_LOOKBACK_DAYS = 80  # L: 횡보 판정 구간(거래일, 약 4개월). "최소 수개월"의 제안 해석
PATTERN_MIN_ROWS = 80  # 이보다 적으면 INSUFFICIENT_HISTORY
PATTERN_WINDOW_ROWS = 100  # 종목당 일봉 조회 행 수(여유 20). 기존 OHLCV_WINDOW_SIZE(41) 대체

# ── 60일선(c3·c4) ───────────────────────────────────────────────────────────────
MA60_WINDOW = 60
MA60_SLOPE_DAYS = 10  # 기울기: MA60(T)와 MA60(T−10) 비교(표시 전용)
CROSS_LOOKBACK_DAYS = 10  # 상향 돌파 관찰창

# ── 이평선 수렴(c2) ─────────────────────────────────────────────────────────────
# 수렴 폭은 MA5·MA10·MA20의 (최대−최소)/MA20. (설계서 §3-1 `ma_convergence_pct`의 이동평균 일수)
CONVERGENCE_MA_WINDOWS = (5, 10, 20)
VOL_SHORT = 10  # 변동성 수축비: 최근 10일 일수익률 표준편차 ÷
VOL_LONG = 60  # 최근 60일 표준편차(모표준편차)

# ── 거래량(c5) ──────────────────────────────────────────────────────────────────
VR_SHORT = 5  # 최근 5일 평균 거래량 ÷
VR_LONG = 60  # 최근 60일 평균 거래량

# ── 급등 이력(c9, 뉴스 반영 대리 지표) ──────────────────────────────────────────
SURGE_LOOKBACK_DAYS = 20  # 최근 20거래일 관찰
SURGE_BASELINE_DAYS = 20  # 거래량 기준: 해당 일 직전 20일 평균
SURGE_RETURN_PCT = Decimal("10.0")  # 일 등락률 ≥ +10%
SURGE_VOLUME_MULT = Decimal("3.0")  # 그리고 거래량 ≥ 직전 20일 평균 × 3

# ── 수정주가 미반영 의심(R3) ────────────────────────────────────────────────────
PRICE_JUMP_LIMIT_PCT = Decimal("31.0")  # 일 변동 ±30% 초과 단절 = 의심(상·하한가 한도 + 여유 1%)

# ── pattern_metrics_status 값(설계서 §3-1, 0011 CHECK 제약과 동일) ─────────────
PATTERN_STATUS_OK = "OK"
PATTERN_STATUS_INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
PATTERN_STATUS_SUSPECT_PRICE_JUMP = "SUSPECT_PRICE_JUMP"
PATTERN_STATUSES = (
    PATTERN_STATUS_OK,
    PATTERN_STATUS_INSUFFICIENT_HISTORY,
    PATTERN_STATUS_SUSPECT_PRICE_JUMP,
)
