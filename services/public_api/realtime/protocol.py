"""한국투자증권 실시간(웹소켓) 프로토콜 — 순수 함수, 네트워크 없음 (DEC-084).

근거: 공식 샘플 저장소 `koreainvestment/open-trading-api`의 `kis_auth.py`·`domestic_stock_functions_ws.py`(2026-10-06 열람).
- 접속키: `POST {base}/oauth2/Approval` (`grant_type`, `appkey`, `secretkey`) → `approval_key`
- 구독: 헤더 `approval_key`·`custtype=P`·`tr_type`(1 구독, 2 해지), 본문 `{"input": {"tr_id", "tr_key"(종목코드)}}`
- 수신: 데이터는 `0|TR_ID|건수|필드^필드^…`(여러 건이면 필드가 이어 붙음), 제어는 JSON(`PINGPONG`·구독 응답)
- 통합시세 TR: 체결가 `H0UNCNT0`, 호가 `H0UNASP0` (KRX 정규장 + NXT 08:00~20:00)
- 한 연결의 구독 한도는 샘플 코드가 40건으로 막는다(종목 × TR 합계).
컬럼 순서는 샘플 코드의 정의를 그대로 옮겼다. 필드 수가 다른 건은 버린다(어긋난 값을 쓰지 않는다).
"""

# ruff: noqa: E501
from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from services.public_api.intraday.normalize import (
    hhmmss,
    normalize_orderbook,
    signed,
    to_float,
    to_int,
)
from services.public_api.schemas.intraday import OrderBookData, TickItem

WS_REAL_URL = "ws://ops.koreainvestment.com:21000"
TR_TRADE = "H0UNCNT0"  # 통합 실시간 체결가
TR_BOOK = "H0UNASP0"  # 통합 실시간 호가
SUBSCRIBE_LIMIT = 40  # 한 연결 구독 합계 한도(공식 샘플)
TRS_PER_CODE = 2  # 종목당 체결 + 호가
MAX_CODES = SUBSCRIBE_LIMIT // TRS_PER_CODE

TRADE_FIELDS: tuple[str, ...] = tuple(
    name.lower()
    for name in (
        "MKSC_SHRN_ISCD", "STCK_CNTG_HOUR", "STCK_PRPR", "PRDY_VRSS_SIGN", "PRDY_VRSS", "PRDY_CTRT",
        "WGHN_AVRG_STCK_PRC", "STCK_OPRC", "STCK_HGPR", "STCK_LWPR", "ASKP1", "BIDP1", "CNTG_VOL",
        "ACML_VOL", "ACML_TR_PBMN", "SELN_CNTG_CSNU", "SHNU_CNTG_CSNU", "NTBY_CNTG_CSNU", "CTTR",
        "SELN_CNTG_SMTN", "SHNU_CNTG_SMTN", "CNTG_CLS_CODE", "SHNU_RATE", "PRDY_VOL_VRSS_ACML_VOL_RATE",
        "OPRC_HOUR", "OPRC_VRSS_PRPR_SIGN", "OPRC_VRSS_PRPR", "HGPR_HOUR", "HGPR_VRSS_PRPR_SIGN",
        "HGPR_VRSS_PRPR", "LWPR_HOUR", "LWPR_VRSS_PRPR_SIGN", "LWPR_VRSS_PRPR", "BSOP_DATE",
        "NEW_MKOP_CLS_CODE", "TRHT_YN", "ASKP_RSQN1", "BIDP_RSQN1", "TOTAL_ASKP_RSQN", "TOTAL_BIDP_RSQN",
        "VOL_TNRT", "PRDY_SMNS_HOUR_ACML_VOL", "PRDY_SMNS_HOUR_ACML_VOL_RATE", "HOUR_CLS_CODE",
        "MRKT_TRTM_CLS_CODE", "VI_STND_PRC", "MARKET_CLS_CODE",
    )
)

BOOK_FIELDS: tuple[str, ...] = (
    ("mksc_shrn_iscd", "bsop_hour", "hour_cls_code")
    + tuple(f"askp{i}" for i in range(1, 11))
    + tuple(f"bidp{i}" for i in range(1, 11))
    + tuple(f"askp_rsqn{i}" for i in range(1, 11))
    + tuple(f"bidp_rsqn{i}" for i in range(1, 11))
    + (
        "total_askp_rsqn", "total_bidp_rsqn", "ovtm_total_askp_rsqn", "ovtm_total_bidp_rsqn",
        "antc_cnpr", "antc_cnqn", "antc_vol", "antc_cntg_vrss", "antc_cntg_vrss_sign", "antc_cntg_prdy_ctrt",
        "acml_vol", "total_askp_rsqn_icdc", "total_bidp_rsqn_icdc", "ovtm_total_askp_icdc", "ovtm_total_bidp_icdc",
        "stck_deal_cls_code", "kmid_prc", "kmid_total_rsqn", "kmid_cls_code", "nmid_prc", "nmid_total_rsqn",
        "nmid_cls_code", "antc_exch_cls_code",
    )
)

FIELDS_BY_TR: dict[str, tuple[str, ...]] = {TR_TRADE: TRADE_FIELDS, TR_BOOK: BOOK_FIELDS}


def build_subscribe(approval_key: str, tr_id: str, code: str, *, subscribe: bool = True) -> str:
    """구독(또는 해지) 요청 JSON 문자열."""
    return json.dumps(
        {
            "header": {
                "approval_key": approval_key,
                "custtype": "P",
                "tr_type": "1" if subscribe else "2",
                "content-type": "utf-8",
            },
            "body": {"input": {"tr_id": tr_id, "tr_key": code}},
        },
        ensure_ascii=False,
    )


@dataclass(frozen=True)
class DataFrame:
    tr_id: str
    records: tuple[dict[str, str], ...]


@dataclass(frozen=True)
class ControlFrame:
    kind: str  # "pingpong" | "subscribe_ok" | "subscribe_error" | "other"
    tr_id: str | None = None
    tr_key: str | None = None
    rt_cd: str | None = None
    msg_cd: str | None = None
    msg: str | None = None


# 이미 구독 중이라는 응답은 성공으로 본다(재연결·중복 요청에서 흔함).
_OK_MSG_CODES = frozenset({"OPSP0000", "OPSP0002"})


def parse_message(raw: str | bytes) -> DataFrame | ControlFrame | None:
    """수신 한 건을 해석한다. 해석할 수 없거나 쓰지 않는 데이터(암호화·모르는 TR)는 None."""
    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
    if not text:
        return None
    if text[0] in "01":
        parts = text.split("|", 3)
        if len(parts) != 4 or parts[0] != "0":  # 암호화(1)는 체결통보 전용 — 이 서비스는 구독하지 않는다
            return None
        _, tr_id, count_raw, payload = parts
        fields = FIELDS_BY_TR.get(tr_id)
        if fields is None or not count_raw.isdigit():
            return None
        values = payload.split("^")
        n = len(fields)
        count = min(int(count_raw), len(values) // n)
        records = tuple(dict(zip(fields, values[i * n : (i + 1) * n], strict=True)) for i in range(count))
        return DataFrame(tr_id=tr_id, records=records) if records else None
    try:
        body = json.loads(text)
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    header = body.get("header") if isinstance(body.get("header"), dict) else {}
    out = body.get("body") if isinstance(body.get("body"), dict) else {}
    tr_id = str(header.get("tr_id") or "") or None
    if tr_id == "PINGPONG":
        return ControlFrame(kind="pingpong", tr_id=tr_id)
    rt_cd = str(out.get("rt_cd")) if out.get("rt_cd") is not None else None
    msg_cd = str(out.get("msg_cd")) if out.get("msg_cd") is not None else None
    msg = " ".join(str(out.get("msg1") or "").split())[:120] or None
    if rt_cd is None:
        return ControlFrame(kind="other", tr_id=tr_id)
    ok = rt_cd == "0" or msg_cd in _OK_MSG_CODES
    return ControlFrame(
        kind="subscribe_ok" if ok else "subscribe_error",
        tr_id=tr_id,
        tr_key=str(header.get("tr_key") or "") or None,
        rt_cd=rt_cd,
        msg_cd=msg_cd,
        msg=msg,
    )


# ── 정규화 ───────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Trade:
    """체결 한 건(통합 체결가). 값이 없으면 None — 0으로 채우지 않는다."""

    code: str
    time: str  # HH:MM:SS
    price: float
    change: float | None
    change_pct: float | None
    open: float | None
    high: float | None
    low: float | None
    ask1: float | None
    bid1: float | None
    volume: int  # 이번 체결량
    acml_volume: int | None  # 당일 누적 거래량
    acml_value: int | None  # 당일 누적 거래대금(원)
    strength: float | None  # 체결강도
    side: str | None  # 체결구분 코드(증권사 정의 그대로)
    business_date: str | None  # YYYYMMDD
    halted: bool
    vi_price: float | None


def parse_trade(rec: Mapping[str, Any]) -> Trade | None:
    """체결 레코드 → `Trade`. 종목·시각·체결가·체결량이 올바르지 않으면 None(어긋난 값은 쓰지 않는다)."""
    code = str(rec.get("mksc_shrn_iscd") or "").strip()
    time = hhmmss(rec.get("stck_cntg_hour"))
    price = to_float(rec.get("stck_prpr"))
    volume = to_int(rec.get("cntg_vol"))
    if len(code) != 6 or time is None or price is None or price <= 0 or volume is None or volume < 0:
        return None
    sign = rec.get("prdy_vrss_sign")
    return Trade(
        code=code,
        time=time,
        price=price,
        change=signed(to_float(rec.get("prdy_vrss")), sign),
        change_pct=signed(to_float(rec.get("prdy_ctrt")), sign),
        open=to_float(rec.get("stck_oprc")),
        high=to_float(rec.get("stck_hgpr")),
        low=to_float(rec.get("stck_lwpr")),
        ask1=to_float(rec.get("askp1")),
        bid1=to_float(rec.get("bidp1")),
        volume=volume,
        acml_volume=to_int(rec.get("acml_vol")),
        acml_value=to_int(rec.get("acml_tr_pbmn")),
        strength=to_float(rec.get("cttr")),
        side=(str(rec.get("cntg_cls_code") or "").strip() or None),
        business_date=(str(rec.get("bsop_date") or "").strip() or None),
        halted=str(rec.get("trht_yn") or "").strip().upper() == "Y",
        vi_price=to_float(rec.get("vi_stnd_prc")),
    )


def trade_tick(trade: Trade) -> TickItem:
    """체결 탭 한 줄(REST 체결과 같은 모양)."""
    return TickItem(
        time=trade.time,
        price=trade.price,
        change=trade.change,
        change_pct=trade.change_pct,
        volume=trade.volume,
        strength=trade.strength,
    )


def parse_book(rec: Mapping[str, Any]) -> OrderBookData | None:
    """호가 레코드 → REST 호가와 같은 모양. 종목코드가 올바르지 않으면 None."""
    code = str(rec.get("mksc_shrn_iscd") or "").strip()
    if len(code) != 6:
        return None
    out1 = dict(rec)
    out1["aspr_acpt_hour"] = rec.get("bsop_hour")  # REST 정규화 함수가 쓰는 이름에 맞춘다
    return normalize_orderbook(code, out1, rec)
