from __future__ import annotations

from pydantic import BaseModel


class StockMetricsData(BaseModel):
    """`GET /api/v1/stocks/{code}/metrics` 응답(REQ-002, 03-system-design.md §4-2).

    원본 시세 필드(open/high/low/close/volume)와 PER/PBR/시가총액 원시값
    (`per_raw`/`pbr_raw`/`market_cap_raw_krw`)은 이 스키마에 **의도적으로
    선언하지 않는다** — §4-3 응답 화이트리스트 원칙(원본/원시값 필드가
    존재하지 않는 Pydantic 모델이므로 실수로 직렬화될 경로 자체가 없음).

    모든 지표 필드는 `null`을 허용한다 — 신규 상장(과거 이력 부족)이나
    당일 거래정지 등으로 계산 불가능한 경우 0/기본값으로 대체하지 않고
    `null`을 그대로 반환한다(§3-2 결측치 처리 원칙, 04-ux-design.md §2-4
    "데이터 부족" 표시로 연결).
    """

    stock_code: str
    name: str
    market: str
    return_pct: float | None
    return_rank_pct: float | None
    ma5_gap_pct: float | None
    ma20_gap_pct: float | None
    volume_anomaly_score: float | None
    per_percentile: float | None
    pbr_percentile: float | None
    market_cap_percentile: float | None
