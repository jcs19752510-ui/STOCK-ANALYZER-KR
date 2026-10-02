"""KIS 응답 → 이 서비스의 정규화 모델 변환(순수 함수, 네트워크 없음) — DEC-052.

공식 샘플 저장소의 필드명을 따른다(분봉 `stck_bsop_date/stck_cntg_hour/stck_oprc/stck_hgpr/stck_lwpr/stck_prpr/cntg_vol`,
체결 `stck_cntg_hour/stck_prpr/prdy_vrss/prdy_vrss_sign/cntg_vol/tday_rltv/prdy_ctrt`, 호가 `askp1~10/bidp1~10/
askp_rsqn1~10/bidp_rsqn1~10/total_askp_rsqn/total_bidp_rsqn/aspr_acpt_hour` 와 예상체결 `antc_*`).
값이 비었거나 숫자가 아니면 해당 행/필드를 버린다(0으로 채우지 않는다).
"""

# ruff: noqa: E501  (한글 설명 주석이 많아 줄 길이 제한은 이 파일에서만 완화)
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from services.public_api.schemas.intraday import (
    BookLevel,
    ExpectedExecution,
    MinuteBar,
    OrderBookData,
    TickItem,
)

OPEN_MINUTE_OF_DAY = 9 * 60  # 09:00


def to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return None


def to_int(value: Any) -> int | None:
    f = to_float(value)
    return None if f is None else int(f)


def hhmmss(value: Any) -> str | None:
    """'093005' → '09:30:05'. 6자리 숫자가 아니면 None."""
    s = str(value or "").strip()
    if len(s) != 6 or not s.isdigit():
        return None
    h, m, sec = int(s[:2]), int(s[2:4]), int(s[4:])
    if h > 23 or m > 59 or sec > 59:
        return None
    return f"{s[:2]}:{s[2:4]}:{s[4:]}"


def minus_one_minute(hhmmss_value: str) -> str:
    """'090500' → '090400'(하한 000000). 분봉 페이징에서 다음 조회 시각을 만든다."""
    total = int(hhmmss_value[:2]) * 60 + int(hhmmss_value[2:4]) - 1
    if total < 0:
        return "000000"
    return f"{total // 60:02d}{total % 60:02d}00"


def signed(value: float | None, sign: Any) -> float | None:
    """KIS는 전일대비 절대값 + 부호 코드(1상한 2상승 3보합 4하한 5하락)를 따로 준다."""
    if value is None:
        return None
    if str(sign) in ("4", "5"):
        return -abs(value)
    return abs(value) if str(sign) in ("1", "2") else value


def normalize_minute_rows(
    rows: Iterable[Mapping[str, Any]], date_yyyymmdd: str | None
) -> dict[str, MinuteBar]:
    """1분봉 행 → {'HHMMSS': 봉}. `date_yyyymmdd`가 주어지면 그 날짜 행만 남긴다."""
    out: dict[str, MinuteBar] = {}
    for r in rows:
        if date_yyyymmdd and str(r.get("stck_bsop_date") or date_yyyymmdd) != date_yyyymmdd:
            continue
        key = str(r.get("stck_cntg_hour") or "")
        label = hhmmss(key)
        o, h, lo, c = (to_float(r.get(k)) for k in ("stck_oprc", "stck_hgpr", "stck_lwpr", "stck_prpr"))
        v = to_int(r.get("cntg_vol"))
        if label is None or None in (o, h, lo, c) or v is None:
            continue
        out[key] = MinuteBar(
            time=label[:5], open=o, high=h, low=lo, close=c, volume=max(v, 0)  # type: ignore[arg-type]
        )
    return out


def aggregate_minutes(bars_by_time: Mapping[str, MinuteBar], interval: int) -> list[MinuteBar]:
    """1분봉을 N분봉으로 묶는다(09:00 기준 구간). 시간 오름차순."""
    ordered = [bars_by_time[k] for k in sorted(bars_by_time)]
    if interval <= 1:
        return ordered
    buckets: dict[int, list[MinuteBar]] = {}
    for b in ordered:
        minute = int(b.time[:2]) * 60 + int(b.time[3:5])
        buckets.setdefault((minute - OPEN_MINUTE_OF_DAY) // interval, []).append(b)
    out: list[MinuteBar] = []
    for idx in sorted(buckets):
        group = buckets[idx]
        start = OPEN_MINUTE_OF_DAY + idx * interval
        out.append(
            MinuteBar(
                time=f"{start // 60:02d}:{start % 60:02d}",
                open=group[0].open,
                high=max(g.high for g in group),
                low=min(g.low for g in group),
                close=group[-1].close,
                volume=sum(g.volume for g in group),
            )
        )
    return out


def normalize_ticks(rows: Iterable[Mapping[str, Any]]) -> list[TickItem]:
    """체결 행 → 틱 목록(입력 순서 유지). 가격·체결량·시각이 없는 행은 버린다."""
    out: list[TickItem] = []
    for r in rows:
        t = hhmmss(r.get("stck_cntg_hour"))
        price = to_float(r.get("stck_prpr"))
        vol = to_int(r.get("cntg_vol"))
        if t is None or price is None or vol is None:
            continue
        sign = r.get("prdy_vrss_sign")
        out.append(
            TickItem(
                time=t,
                price=price,
                change=signed(to_float(r.get("prdy_vrss")), sign),
                change_pct=signed(to_float(r.get("prdy_ctrt")), sign),
                volume=max(vol, 0),
                strength=to_float(r.get("tday_rltv")),
            )
        )
    return out


def normalize_orderbook(
    code: str, out1: Mapping[str, Any] | None, out2: Mapping[str, Any] | None
) -> OrderBookData:
    o1 = out1 or {}
    asks: list[BookLevel] = []
    bids: list[BookLevel] = []
    for i in range(1, 11):
        ap, aq = to_float(o1.get(f"askp{i}")), to_int(o1.get(f"askp_rsqn{i}"))
        bp, bq = to_float(o1.get(f"bidp{i}")), to_int(o1.get(f"bidp_rsqn{i}"))
        if ap and ap > 0 and aq is not None:
            asks.append(BookLevel(price=ap, quantity=max(aq, 0)))
        if bp and bp > 0 and bq is not None:
            bids.append(BookLevel(price=bp, quantity=max(bq, 0)))
    expected = None
    o2 = out2 or {}
    exp_price = to_float(o2.get("antc_cnpr"))
    if exp_price and exp_price > 0:
        sign = o2.get("antc_cntg_vrss_sign")
        expected = ExpectedExecution(
            price=exp_price,
            change=signed(to_float(o2.get("antc_cntg_vrss")), sign),
            change_pct=signed(to_float(o2.get("antc_cntg_prdy_ctrt")), sign),
            volume=to_int(o2.get("antc_vol")),
        )
    return OrderBookData(
        stock_code=code,
        time=hhmmss(o1.get("aspr_acpt_hour")),
        asks=asks,
        bids=bids,
        total_ask_quantity=to_int(o1.get("total_askp_rsqn")) or 0,
        total_bid_quantity=to_int(o1.get("total_bidp_rsqn")) or 0,
        expected=expected,
    )
