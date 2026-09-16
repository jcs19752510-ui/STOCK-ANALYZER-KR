from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

import services.public_api.api.metrics as metrics_module
from services.public_api.api.calendar import get_calendar_repository
from services.public_api.api.metrics import (
    get_calendar_repository as get_metrics_calendar_repository,
)
from services.public_api.api.metrics import get_stock_metrics_repository
from services.public_api.api.stocks import get_stock_search_repository
from services.public_api.db.metrics_repository import DerivedMetricsRow, StockRow
from services.public_api.db.session import get_db
from services.public_api.db.stock_repository import StockSearchResultRow
from services.public_api.main import app
from shared.calendar_service.types import CalendarRow

KST = ZoneInfo("Asia/Seoul")


def _patch_now(monkeypatch, fixed: datetime) -> None:
    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed

    monkeypatch.setattr(metrics_module, "datetime", _FixedDatetime)


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


# --- GET /api/v1/stocks/{code}/metrics (UNIT-06, REQ-002) ---


class FakeMetricsRepository:
    def __init__(
        self,
        *,
        stock: StockRow | None,
        published_trade_date: date | None,
        metrics_by_date: dict[date, DerivedMetricsRow],
    ):
        self._stock = stock
        self._published_trade_date = published_trade_date
        self._metrics_by_date = metrics_by_date

    def get_stock(self, stock_code: str) -> StockRow | None:
        return self._stock

    def get_current_published_trade_date(self, market: str) -> date | None:
        return self._published_trade_date

    def get_metrics(self, stock_code: str, trade_date: date) -> DerivedMetricsRow | None:
        return self._metrics_by_date.get(trade_date)


def _override_metrics_repository(repository: FakeMetricsRepository):
    def _factory():
        return repository

    return _factory


_FULL_METRICS_ROW = DerivedMetricsRow(
    return_pct=3.2,
    return_rank_pct=5.0,
    ma5_gap_pct=1.1,
    ma20_gap_pct=-0.5,
    volume_anomaly_score=2.3,
    per_percentile=20.0,
    pbr_percentile=30.0,
    market_cap_percentile=10.0,
)


def test_get_stock_metrics_latest_success(monkeypatch):
    trading_day = date(2026, 9, 11)
    _patch_now(monkeypatch, datetime(2026, 9, 11, 20, 0, tzinfo=KST))
    calendar_rows = {
        (trading_day, "KRX"): CalendarRow(
            trade_date=trading_day,
            market="KRX",
            is_trading_day=True,
            session_close_at=time(15, 30),
            holiday_name=None,
            source="test",
        )
    }
    repo = FakeMetricsRepository(
        stock=StockRow(stock_code="005930", name="삼성전자", market="KOSPI"),
        published_trade_date=trading_day,
        metrics_by_date={trading_day: _FULL_METRICS_ROW},
    )
    app.dependency_overrides[get_stock_metrics_repository] = _override_metrics_repository(repo)
    app.dependency_overrides[get_metrics_calendar_repository] = _override_repository(
        calendar_rows
    )
    client = TestClient(app)

    resp = client.get("/api/v1/stocks/005930/metrics")

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["stock_code"] == "005930"
    assert body["data"]["return_rank_pct"] == 5.0
    assert body["meta"]["data_freshness"]["trade_date"] == "2026-09-11"
    assert body["meta"]["data_freshness"]["is_latest_trading_day"] is True


def test_get_stock_metrics_stock_not_found_returns_404():
    repo = FakeMetricsRepository(stock=None, published_trade_date=None, metrics_by_date={})
    app.dependency_overrides[get_stock_metrics_repository] = _override_metrics_repository(repo)
    app.dependency_overrides[get_metrics_calendar_repository] = _override_repository({})
    client = TestClient(app)

    resp = client.get("/api/v1/stocks/999999/metrics")

    app.dependency_overrides.clear()
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "STOCK_NOT_FOUND"


def test_get_stock_metrics_no_published_data_returns_503_data_pipeline_stale(monkeypatch):
    trading_day = date(2026, 9, 11)
    _patch_now(monkeypatch, datetime(2026, 9, 11, 20, 0, tzinfo=KST))
    calendar_rows = {
        (trading_day, "KRX"): CalendarRow(
            trade_date=trading_day,
            market="KRX",
            is_trading_day=True,
            session_close_at=time(15, 30),
            holiday_name=None,
            source="test",
        )
    }
    repo = FakeMetricsRepository(
        stock=StockRow(stock_code="005930", name="삼성전자", market="KOSPI"),
        published_trade_date=None,  # Derivation Batch가 아직 한 번도 발행하지 않음
        metrics_by_date={},
    )
    app.dependency_overrides[get_stock_metrics_repository] = _override_metrics_repository(repo)
    app.dependency_overrides[get_metrics_calendar_repository] = _override_repository(
        calendar_rows
    )
    client = TestClient(app)

    resp = client.get("/api/v1/stocks/005930/metrics")

    app.dependency_overrides.clear()
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "DATA_PIPELINE_STALE"


def test_get_stock_metrics_calendar_not_confirmed_returns_424():
    repo = FakeMetricsRepository(
        stock=StockRow(stock_code="005930", name="삼성전자", market="KOSPI"),
        published_trade_date=date(2026, 9, 11),
        metrics_by_date={},
    )
    app.dependency_overrides[get_stock_metrics_repository] = _override_metrics_repository(repo)
    app.dependency_overrides[get_metrics_calendar_repository] = _override_repository({})
    client = TestClient(app)

    resp = client.get("/api/v1/stocks/005930/metrics")

    app.dependency_overrides.clear()
    assert resp.status_code == 424
    assert resp.json()["error"]["code"] == "CALENDAR_NOT_CONFIRMED"


def test_get_stock_metrics_missing_row_for_date_returns_null_fields(monkeypatch):
    """종목은 존재하나 그 거래일의 파생 지표 행이 없으면(휴장/거래정지 등)
    전 지표 필드가 null인 200 응답을 반환한다(§3-2 결측치 처리 원칙의 확장 —
    unit-06-note.md §2 참조)."""
    trading_day = date(2026, 9, 11)
    _patch_now(monkeypatch, datetime(2026, 9, 11, 20, 0, tzinfo=KST))
    calendar_rows = {
        (trading_day, "KRX"): CalendarRow(
            trade_date=trading_day,
            market="KRX",
            is_trading_day=True,
            session_close_at=time(15, 30),
            holiday_name=None,
            source="test",
        )
    }
    repo = FakeMetricsRepository(
        stock=StockRow(stock_code="005930", name="삼성전자", market="KOSPI"),
        published_trade_date=trading_day,
        metrics_by_date={},  # 그 날짜의 파생 지표 행이 없음
    )
    app.dependency_overrides[get_stock_metrics_repository] = _override_metrics_repository(repo)
    app.dependency_overrides[get_metrics_calendar_repository] = _override_repository(
        calendar_rows
    )
    client = TestClient(app)

    resp = client.get("/api/v1/stocks/005930/metrics")

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["stock_code"] == "005930"
    assert data["return_pct"] is None
    assert data["return_rank_pct"] is None
    assert data["market_cap_percentile"] is None


def test_get_stock_metrics_explicit_date_bypasses_published_pointer(monkeypatch):
    requested_day = date(2026, 9, 10)
    expected_latest = date(2026, 9, 11)
    _patch_now(monkeypatch, datetime(2026, 9, 11, 20, 0, tzinfo=KST))
    calendar_rows = {
        (requested_day, "KRX"): CalendarRow(
            trade_date=requested_day,
            market="KRX",
            is_trading_day=True,
            session_close_at=time(15, 30),
            holiday_name=None,
            source="test",
        ),
        (expected_latest, "KRX"): CalendarRow(
            trade_date=expected_latest,
            market="KRX",
            is_trading_day=True,
            session_close_at=time(15, 30),
            holiday_name=None,
            source="test",
        ),
    }
    repo = FakeMetricsRepository(
        stock=StockRow(stock_code="005930", name="삼성전자", market="KOSPI"),
        published_trade_date=expected_latest,
        metrics_by_date={requested_day: _FULL_METRICS_ROW},
    )
    app.dependency_overrides[get_stock_metrics_repository] = _override_metrics_repository(repo)
    app.dependency_overrides[get_metrics_calendar_repository] = _override_repository(
        calendar_rows
    )
    client = TestClient(app)

    resp = client.get("/api/v1/stocks/005930/metrics", params={"date": "2026-09-10"})

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["return_rank_pct"] == 5.0
    assert body["meta"]["data_freshness"]["trade_date"] == "2026-09-10"
    assert body["meta"]["data_freshness"]["is_latest_trading_day"] is False
    assert "지연" in body["meta"]["data_freshness"]["staleness_note"]


def test_get_stock_metrics_invalid_date_format_returns_400():
    repo = FakeMetricsRepository(stock=None, published_trade_date=None, metrics_by_date={})
    app.dependency_overrides[get_stock_metrics_repository] = _override_metrics_repository(repo)
    app.dependency_overrides[get_metrics_calendar_repository] = _override_repository({})
    client = TestClient(app)

    resp = client.get("/api/v1/stocks/005930/metrics", params={"date": "not-a-date"})

    app.dependency_overrides.clear()
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_PARAMETER"
