"""실시간 프로토콜(순수 함수) 시험 — DEC-084."""

# ruff: noqa: E501
from __future__ import annotations

import json

from services.public_api.realtime import protocol as p


def _trade_frame(**over: str) -> str:
    vals = {name: "" for name in p.TRADE_FIELDS}
    vals.update(
        mksc_shrn_iscd="005930", stck_cntg_hour="093001", stck_prpr="70500", prdy_vrss_sign="2", prdy_vrss="500",
        prdy_ctrt="0.71", stck_oprc="70000", stck_hgpr="70600", stck_lwpr="69900", askp1="70600", bidp1="70500",
        cntg_vol="30", acml_vol="123456", acml_tr_pbmn="8700000000", cttr="101.5", cntg_cls_code="1",
        bsop_date="20261006", trht_yn="N", vi_stnd_prc="0",
    )
    vals.update(over)
    return "0|H0UNCNT0|001|" + "^".join(vals[n] for n in p.TRADE_FIELDS)


def test_필드_개수는_공식_샘플과_같다() -> None:
    assert len(p.TRADE_FIELDS) == 47 and len(p.BOOK_FIELDS) == 66
    # 공식 샘플의 앞쪽 순서(체결: 종목·시각·현재가·부호·전일대비·등락률 …, 호가: 종목·시각·시간구분 → 매도 10 → 매수 10)
    assert p.TRADE_FIELDS[:6] == ("mksc_shrn_iscd", "stck_cntg_hour", "stck_prpr", "prdy_vrss_sign", "prdy_vrss", "prdy_ctrt")
    assert p.TRADE_FIELDS[12:14] == ("cntg_vol", "acml_vol") and p.TRADE_FIELDS[33] == "bsop_date"
    assert p.BOOK_FIELDS[3] == "askp1" and p.BOOK_FIELDS[13] == "bidp1" and p.BOOK_FIELDS[23] == "askp_rsqn1" and p.BOOK_FIELDS[33] == "bidp_rsqn1"
    assert p.BOOK_FIELDS[43:45] == ("total_askp_rsqn", "total_bidp_rsqn")


def test_구독_요청_형식() -> None:
    body = json.loads(p.build_subscribe("KEY", p.TR_TRADE, "005930"))
    assert body["header"] == {"approval_key": "KEY", "custtype": "P", "tr_type": "1", "content-type": "utf-8"}
    assert body["body"]["input"] == {"tr_id": "H0UNCNT0", "tr_key": "005930"}
    assert json.loads(p.build_subscribe("KEY", p.TR_BOOK, "000660", subscribe=False))["header"]["tr_type"] == "2"


def test_통합시세_TR을_쓴다() -> None:
    assert (p.TR_TRADE, p.TR_BOOK) == ("H0UNCNT0", "H0UNASP0")
    assert p.MAX_CODES == 20 and p.SUBSCRIBE_LIMIT == 40


def test_제어_메시지_해석() -> None:
    ping = p.parse_message(json.dumps({"header": {"tr_id": "PINGPONG", "datetime": "20261006101010"}}))
    assert isinstance(ping, p.ControlFrame) and ping.kind == "pingpong"
    ok = p.parse_message(json.dumps({"header": {"tr_id": "H0UNCNT0", "tr_key": "005930", "encrypt": "N"}, "body": {"rt_cd": "0", "msg_cd": "OPSP0000", "msg1": "SUBSCRIBE SUCCESS"}}))
    assert isinstance(ok, p.ControlFrame) and ok.kind == "subscribe_ok" and ok.tr_key == "005930"
    already = p.parse_message(json.dumps({"header": {"tr_id": "H0UNCNT0", "tr_key": "005930"}, "body": {"rt_cd": "1", "msg_cd": "OPSP0002", "msg1": "ALREADY IN SUBSCRIBE"}}))
    assert isinstance(already, p.ControlFrame) and already.kind == "subscribe_ok"  # 이미 구독 중이면 성공으로 본다
    err = p.parse_message(json.dumps({"header": {"tr_id": "H0UNCNT0", "tr_key": "005930"}, "body": {"rt_cd": "1", "msg_cd": "OPSP0011", "msg1": "invalid approval : NOT FOUND"}}))
    assert isinstance(err, p.ControlFrame) and err.kind == "subscribe_error" and err.msg_cd == "OPSP0011"


def test_해석할_수_없는_메시지는_버린다() -> None:
    assert p.parse_message("") is None
    assert p.parse_message("not json") is None
    assert p.parse_message("[1,2]") is None
    assert p.parse_message("1|H0STCNI0|001|암호화된값") is None  # 암호화(체결통보)는 쓰지 않는다
    assert p.parse_message("0|H0XXXXX9|001|a^b") is None  # 모르는 TR
    assert p.parse_message("0|H0UNCNT0|abc|a^b") is None  # 건수가 숫자가 아님
    assert p.parse_message("0|H0UNCNT0|001|a^b^c") is None  # 필드 수 부족 → 어긋난 값은 쓰지 않는다


def test_체결_레코드_해석() -> None:
    frame = p.parse_message(_trade_frame())
    assert isinstance(frame, p.DataFrame) and frame.tr_id == p.TR_TRADE and len(frame.records) == 1
    trade = p.parse_trade(frame.records[0])
    assert trade is not None
    assert (trade.code, trade.time, trade.price, trade.volume, trade.acml_volume) == ("005930", "09:30:01", 70500.0, 30, 123456)
    assert trade.change == 500 and trade.change_pct == 0.71 and trade.business_date == "20261006" and trade.halted is False
    assert trade.strength == 101.5 and trade.open == 70000 and trade.high == 70600 and trade.low == 69900


def test_하락_부호는_음수가_된다() -> None:
    trade = p.parse_trade(p.parse_message(_trade_frame(prdy_vrss_sign="5", prdy_vrss="800", prdy_ctrt="1.12")).records[0])  # type: ignore[union-attr]
    assert trade is not None and trade.change == -800 and trade.change_pct == -1.12


def test_잘못된_체결은_버린다() -> None:
    for over in ({"stck_prpr": "0"}, {"stck_prpr": ""}, {"stck_cntg_hour": "99"}, {"cntg_vol": "-1"}, {"mksc_shrn_iscd": "5930"}):
        frame = p.parse_message(_trade_frame(**over))
        assert frame is not None and p.parse_trade(frame.records[0]) is None, over  # type: ignore[union-attr]


def test_여러_건이_이어진_프레임() -> None:
    one = _trade_frame().split("|", 3)[3]
    two = _trade_frame(stck_cntg_hour="093002", stck_prpr="70600").split("|", 3)[3]
    frame = p.parse_message(f"0|H0UNCNT0|002|{one}^{two}")
    assert isinstance(frame, p.DataFrame) and [r["stck_cntg_hour"] for r in frame.records] == ["093001", "093002"]
    # 건수가 실제보다 크면 온전한 레코드만 쓴다
    cut = p.parse_message(f"0|H0UNCNT0|003|{one}^{two}")
    assert isinstance(cut, p.DataFrame) and len(cut.records) == 2


def test_호가_해석은_REST_모양과_같다() -> None:
    vals = {name: "" for name in p.BOOK_FIELDS}
    vals.update(mksc_shrn_iscd="005930", bsop_hour="093001", total_askp_rsqn="1000", total_bidp_rsqn="2000")
    for i in range(1, 11):
        vals[f"askp{i}"], vals[f"bidp{i}"] = str(70500 + 100 * i), str(70500 - 100 * (i - 1))
        vals[f"askp_rsqn{i}"], vals[f"bidp_rsqn{i}"] = str(10 * i), str(20 * i)
    vals.update(antc_cnpr="70550", antc_cntg_vrss="50", antc_cntg_vrss_sign="2", antc_cntg_prdy_ctrt="0.07", antc_vol="123")
    frame = p.parse_message("0|H0UNASP0|001|" + "^".join(vals[n] for n in p.BOOK_FIELDS))
    assert isinstance(frame, p.DataFrame)
    book = p.parse_book(frame.records[0])
    assert book is not None and book.stock_code == "005930" and book.time == "09:30:01"
    assert [lv.price for lv in book.asks][:2] == [70600, 70700] and [lv.price for lv in book.bids][:2] == [70500, 70400]
    assert book.asks[0].quantity == 10 and book.bids[0].quantity == 20
    assert (book.total_ask_quantity, book.total_bid_quantity) == (1000, 2000)
    assert book.expected is not None and book.expected.price == 70550 and book.expected.change == 50
    assert p.parse_book({"mksc_shrn_iscd": "12"}) is None
