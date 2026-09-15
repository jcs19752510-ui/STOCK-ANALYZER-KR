from datetime import date, time, timedelta

from fastapi.testclient import TestClient

from services.public_api.api.calendar import get_calendar_repository
from services.public_api.api.stocks import get_stock_search_repository
from services.public_api.db.session import get_db
from services.public_api.db.stock_repository import StockSearchResultRow
from services.public_api.main import app
from shared.calendar_service.types import CalendarRow


class FakeRepository:
    def __init__(self, rows: dict[tuple[date, str], CalendarRow]):
        self._rows = rows

    def get(self, trade_date, market):
        return self._rows.get((trade_date, market))


class FakeDbSession:
    def execute(self, *args, **kwargs):
        return None


class FailingFakeDbSession:
    def execute(self, *args, **kwargs):
        raise RuntimeError("DB 연결 실패(테스트용)")


def _override_repository(rows):
    def _factory():
        return FakeRepository(rows)

    return _factory


def test_last_trading_day_success():
    trading_day = date(2026, 9, 11)
    rows = {
        (trading_day, "KRX"): CalendarRow(
            trade_date=trading_day,
            market="KRX",
            is_trading_day=True,
            # as_of(10:00)이 이 마감 시각(09:00) 이후이므로 "이미 마감"으로 판정된다
            # (v4, 03-system-design.md §3-3 — 마감 시각 기준 판단).
            session_close_at=time(9, 0),
            holiday_name=None,
            source="test",
        )
    }
    app.dependency_overrides[get_calendar_repository] = _override_repository(rows)
    client = TestClient(app)

    resp = client.get(
        "/api/v1/calendar/last-trading-day",
        params={"market": "KRX", "as_of": "2026-09-11T10:00:00+09:00"},
    )

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["trade_date"] == "2026-09-11"
    assert body["error"] is None
    assert "투자 조언" in body["meta"]["disclaimer"]


def test_last_trading_day_calendar_gap_returns_424():
    app.dependency_overrides[get_calendar_repository] = _override_repository({})
    client = TestClient(app)

    resp = client.get(
        "/api/v1/calendar/last-trading-day",
        params={"market": "KRX", "as_of": "2026-09-11T10:00:00+09:00"},
    )

    app.dependency_overrides.clear()
    assert resp.status_code == 424
    body = resp.json()
    assert body["error"]["code"] == "CALENDAR_NOT_CONFIRMED"
    assert body["data"] is None


def test_last_trading_day_invalid_market_returns_400():
    app.dependency_overrides[get_calendar_repository] = _override_repository({})
    client = TestClient(app)

    resp = client.get(
        "/api/v1/calendar/last-trading-day",
        params={"market": "NASDAQ"},
    )

    app.dependency_overrides.clear()
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_PARAMETER"


def test_health_ok():
    def _override_db():
        yield FakeDbSession()

    app.dependency_overrides[get_db] = _override_db
    client = TestClient(app)

    resp = client.get("/api/v1/health")

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["data"] == {"status": "ok", "db": "ok"}


def test_health_degraded_when_db_check_fails():
    # DEF-002(6단계) 회귀 테스트: DB 예외를 삼키지 않고 "degraded"로 응답해야 한다.
    def _override_db():
        yield FailingFakeDbSession()

    app.dependency_overrides[get_db] = _override_db
    client = TestClient(app)

    resp = client.get("/api/v1/health")

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["data"] == {"status": "ok", "db": "degraded"}


def test_last_trading_day_scan_limit_exceeded_returns_503():
    # DEF-002(6단계) 회귀 테스트: CalendarScanLimitExceeded는 424가 아니라 503으로 매핑돼야 한다.
    start = date(2026, 1, 1)
    rows = {
        (start - timedelta(days=i), "KRX"): CalendarRow(
            trade_date=start - timedelta(days=i),
            market="KRX",
            is_trading_day=False,
            session_close_at=None,
            holiday_name="휴장",
            source="test",
        )
        for i in range(-2, 500)
    }
    app.dependency_overrides[get_calendar_repository] = _override_repository(rows)
    client = TestClient(app)

    resp = client.get(
        "/api/v1/calendar/last-trading-day",
        params={"market": "KRX", "as_of": "2026-01-01T12:00:00+09:00"},
    )

    app.dependency_overrides.clear()
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "SERVICE_UNAVAILABLE"


# --- GET /api/v1/stocks (UNIT-03, REQ-001) ---


class FakeStockSearchRepository:
    def __init__(self, rows: list[StockSearchResultRow]):
        self._rows = rows
        self.calls: list[tuple[str, str]] = []

    def search(self, *, query: str, market: str) -> list[StockSearchResultRow]:
        self.calls.append((query, market))
        return self._rows


def _override_stock_repository(repository: FakeStockSearchRepository):
    def _factory():
        return repository

    return _factory


def test_search_stocks_success():
    repo = FakeStockSearchRepository(
        [StockSearchResultRow(stock_code="005930", name="삼성전자", market="KOSPI")]
    )
    app.dependency_overrides[get_stock_search_repository] = _override_stock_repository(repo)
    client = TestClient(app)

    resp = client.get("/api/v1/stocks", params={"query": "삼성"})

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"] == [{"stock_code": "005930", "name": "삼성전자", "market": "KOSPI"}]
    assert body["error"] is None
    assert repo.calls == [("삼성", "ALL")]  # market 생략 시 기본값 ALL


def test_search_stocks_no_results_returns_empty_list():
    repo = FakeStockSearchRepository([])
    app.dependency_overrides[get_stock_search_repository] = _override_stock_repository(repo)
    client = TestClient(app)

    resp = client.get("/api/v1/stocks", params={"query": "존재하지않는종목"})

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["data"] == []


def test_search_stocks_passes_market_filter():
    repo = FakeStockSearchRepository([])
    app.dependency_overrides[get_stock_search_repository] = _override_stock_repository(repo)
    client = TestClient(app)

    resp = client.get("/api/v1/stocks", params={"query": "005930", "market": "KOSDAQ"})

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert repo.calls == [("005930", "KOSDAQ")]


def test_search_stocks_empty_query_returns_400():
    repo = FakeStockSearchRepository([])
    app.dependency_overrides[get_stock_search_repository] = _override_stock_repository(repo)
    client = TestClient(app)

    resp = client.get("/api/v1/stocks", params={"query": "   "})

    app.dependency_overrides.clear()
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_PARAMETER"
    assert repo.calls == []  # 리포지토리까지 도달하지 않아야 함


def test_search_stocks_missing_query_returns_400():
    # query는 필수 파라미터라 FastAPI가 RequestValidationError를 던지고,
    # main.py의 공통 핸들러가 이를 400 INVALID_PARAMETER로 변환한다. 실제
    # get_stock_search_repository(→get_db)까지는 도달하지 않지만, FastAPI가
    # 라우트 함수 실행 전에 의존성 트리 전체를 먼저 resolve하므로 이 테스트도
    # 다른 테스트와 동일하게 오버라이드가 필요하다(실 DB 환경변수 요구 회피).
    repo = FakeStockSearchRepository([])
    app.dependency_overrides[get_stock_search_repository] = _override_stock_repository(repo)
    client = TestClient(app)

    resp = client.get("/api/v1/stocks")

    app.dependency_overrides.clear()
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_PARAMETER"
    assert repo.calls == []


def test_search_stocks_invalid_market_returns_400():
    repo = FakeStockSearchRepository([])
    app.dependency_overrides[get_stock_search_repository] = _override_stock_repository(repo)
    client = TestClient(app)

    resp = client.get("/api/v1/stocks", params={"query": "삼성", "market": "NASDAQ"})

    app.dependency_overrides.clear()
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_PARAMETER"
    assert repo.calls == []
