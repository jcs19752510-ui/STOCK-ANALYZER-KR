"""`GET /api/v1/stocks/{code}/prices` 단위 테스트 (UNIT-20, DEC-041) — 가짜 리포지토리, DB 없음."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from services.public_api.api.prices import get_price_calendar_repository, get_price_repository
from services.public_api.db.metrics_repository import StockRow
from services.public_api.db.price_repository import PriceRow
from services.public_api.main import app
from tests.unit.test_pattern_api import BrokenCalendar, GapCalendar, WeekdayCalendar

URL = "/api/v1/stocks/{code}/prices"


def _rows(n: int, *, start_close: int = 1000, last: date = date(2026, 9, 21)) -> list[PriceRow]:
    days: list[date] = []
    d = last
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    days.reverse()
    return [
        PriceRow(
            trade_date=day,
            open=Decimal(start_close + i),
            high=Decimal(start_close + i + 5),
            low=Decimal(start_close + i - 5),
            close=Decimal(start_close + i + 1),
            volume=1000 + i,
            trading_value=(start_close + i) * (1000 + i),
        )
        for i, day in enumerate(days)
    ]


class FakeRepo:
    def __init__(self, rows=None, stock=StockRow("T00001", "테스트전자", "KOSPI")):
        self.rows = rows if rows is not None else _rows(30)
        self.stock = stock
        self.calls: list[tuple] = []

    def get_stock(self, code):
        return self.stock if self.stock and code == self.stock.stock_code else None

    def get_prices(self, code, days):
        self.calls.append((code, days))
        return self.rows[-days:]


@pytest.fixture(autouse=True)
def _clear():
    yield
    app.dependency_overrides.clear()


def _client(repo=None, calendar=None):
    repo = repo or FakeRepo()
    app.dependency_overrides[get_price_repository] = lambda: repo
    app.dependency_overrides[get_price_calendar_repository] = lambda: calendar or WeekdayCalendar()
    return TestClient(app), repo


def test_route_registered_read_only():
    paths = app.openapi()["paths"]
    assert set(paths["/api/v1/stocks/{code}/prices"]) == {"get"}


def test_default_call_returns_ascending_prices_with_change_and_envelope():
    client, repo = _client()
    resp = client.get(URL.format(code="T00001"))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert repo.calls == [("T00001", 120)]  # 기본 120거래일
    assert set(body) == {"meta", "data", "error"} and body["error"] is None
    assert "disclaimer" in body["meta"]
    data = body["data"]
    assert (data["stock_code"], data["name"], data["market"]) == ("T00001", "테스트전자", "KOSPI")
    dates = [p["trade_date"] for p in data["prices"]]
    assert dates == sorted(dates) and len(dates) == 30
    first, second = data["prices"][0], data["prices"][1]
    assert first["change"] is None and first["change_pct"] is None  # 비교 대상 없음
    assert second["change"] == pytest.approx(second["close"] - first["close"])
    assert second["change_pct"] == pytest.approx(
        round((second["close"] - first["close"]) / first["close"] * 100, 2)
    )
    assert set(first) == {
        "trade_date", "open", "high", "low", "close", "volume", "trading_value",
        "change", "change_pct",
    }  # fmt: skip


def test_change_pct_is_null_when_previous_close_is_zero_not_a_division_error():
    rows = _rows(2)
    rows[0] = PriceRow(rows[0].trade_date, *(Decimal(0),) * 4, 0, 0)
    client, _ = _client(FakeRepo(rows))
    prices = client.get(URL.format(code="T00001")).json()["data"]["prices"]
    assert prices[1]["change_pct"] is None and prices[1]["change"] == prices[1]["close"]


@pytest.mark.parametrize("days", [20, 120, 260])
def test_days_boundaries_accepted_and_passed_to_repository(days):
    client, repo = _client(FakeRepo(_rows(260)))
    assert client.get(URL.format(code="T00001"), params={"days": days}).status_code == 200
    assert repo.calls[-1] == ("T00001", days)


@pytest.mark.parametrize("days", ["19", "261", "0", "-1", "abc", ""])
def test_days_out_of_range_is_rejected_before_touching_repository(days):
    client, repo = _client()
    resp = client.get(URL.format(code="T00001"), params={"days": days})
    assert resp.status_code in (400, 422), resp.text
    assert resp.json()["data"] is None and repo.calls == []


def test_unknown_stock_is_404_stock_not_found():
    client, _ = _client()
    resp = client.get(URL.format(code="ZZZZZZ"))
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "STOCK_NOT_FOUND"


def test_stock_without_prices_is_200_with_empty_list_and_no_freshness():
    client, _ = _client(FakeRepo(rows=[]))
    body = client.get(URL.format(code="T00001")).json()
    assert body["data"]["prices"] == [] and body["meta"]["data_freshness"] is None


def test_freshness_reports_stale_when_last_price_is_older_than_expected():
    client, _ = _client(FakeRepo(_rows(30, last=date(2026, 9, 21))))
    fresh = client.get(URL.format(code="T00001")).json()["meta"]["data_freshness"]
    assert fresh["trade_date"] == "2026-09-21" and fresh["is_latest_trading_day"] is False
    assert fresh["staleness_note"]


def test_calendar_not_confirmed_and_integrity_errors_map_to_documented_codes():
    client, _ = _client(calendar=GapCalendar())
    assert client.get(URL.format(code="T00001")).status_code == 424
    client, _ = _client(calendar=BrokenCalendar())
    resp = client.get(URL.format(code="T00001"))
    assert resp.status_code == 503 and resp.json()["error"]["code"] == "SERVICE_UNAVAILABLE"


def test_response_is_strict_json_numbers_and_no_raw_internal_field_names():
    client, _ = _client()
    text = client.get(URL.format(code="T00001")).text
    assert "NaN" not in text and "Infinity" not in text
    for forbidden in ("_raw", "market_cap", "per", "source_batch_id"):
        assert f'"{forbidden}' not in text


# ── 목록용 시세 요약: GET /api/v1/stocks/quotes?codes=... (DEC-041) ──────────────────────
from services.public_api.api.prices import get_quote_repository  # noqa: E402
from services.public_api.db.price_repository import QuoteRow  # noqa: E402

QUOTES_URL = "/api/v1/stocks/quotes"


class FakeQuoteRepo:
    def __init__(self, rows=None):
        self.rows = rows or {}
        self.calls: list[list[str]] = []

    def get_quotes(self, codes):
        self.calls.append(list(codes))
        return [self.rows[c] for c in codes if c in self.rows]


def _quote(code, close=1100, prev=1000):
    return QuoteRow(code, date(2026, 9, 21), Decimal(close), Decimal(prev))


def _qclient(repo):
    app.dependency_overrides[get_quote_repository] = lambda: repo
    return TestClient(app)


def test_quotes_returns_close_change_and_pct_and_skips_unknown_codes():
    repo = FakeQuoteRepo({"T00001": _quote("T00001"), "T00002": _quote("T00002", 900, 1000)})
    resp = _qclient(repo).get(QUOTES_URL, params={"codes": "T00001,ZZZZZZ,T00002"})
    assert resp.status_code == 200, resp.text
    q = resp.json()["data"]["quotes"]
    assert [x["stock_code"] for x in q] == ["T00001", "T00002"]  # 요청 순서, 없는 종목은 생략
    assert q[0]["close"] == 1100 and q[0]["change"] == 100 and q[0]["change_pct"] == 10.0
    assert q[1]["change"] == -100 and q[1]["change_pct"] == -10.0
    assert set(q[0]) == {"stock_code", "trade_date", "close", "change", "change_pct"}


def test_quotes_change_is_null_without_previous_and_pct_is_null_for_zero_previous():
    repo = FakeQuoteRepo(
        {"T00001": QuoteRow("T00001", date(2026, 9, 21), Decimal(5), None),
         "T00002": QuoteRow("T00002", date(2026, 9, 21), Decimal(5), Decimal(0))}
    )  # fmt: skip
    q = _qclient(repo).get(QUOTES_URL, params={"codes": "T00001,T00002"}).json()["data"]["quotes"]
    assert q[0]["change"] is None and q[0]["change_pct"] is None  # 비교 대상 없음
    assert q[1]["change"] == 5 and q[1]["change_pct"] is None  # 0으로 나누지 않는다


def test_quotes_dedupes_codes_and_caps_at_50():
    repo = FakeQuoteRepo({"T00001": _quote("T00001")})
    c = _qclient(repo)
    c.get(QUOTES_URL, params={"codes": "T00001,T00001"})
    assert repo.calls[-1] == ["T00001"]
    many = ",".join(f"A{i:05d}" for i in range(51))
    resp = c.get(QUOTES_URL, params={"codes": many})
    assert resp.status_code == 400 and resp.json()["error"]["code"] == "INVALID_PARAMETER"


@pytest.mark.parametrize(
    "codes", ["", ",", "ABC", "T0000 1", "T00001;DROP", "가나다라마바", "T00001,,T00002"]
)
def test_quotes_rejects_malformed_codes_without_touching_repository(codes):
    repo = FakeQuoteRepo()
    resp = _qclient(repo).get(QUOTES_URL, params={"codes": codes})
    assert resp.status_code == 400 and resp.json()["error"]["code"] == "INVALID_PARAMETER"
    assert repo.calls == []


def test_quotes_route_does_not_shadow_stock_search_or_prices():
    paths = app.openapi()["paths"]
    assert "/api/v1/stocks" in paths and "/api/v1/stocks/{code}/prices" in paths
    assert "/api/v1/stocks/quotes" in paths
