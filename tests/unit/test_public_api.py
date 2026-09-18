from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

import services.public_api.api.metrics as metrics_module
from services.public_api.api.calendar import get_calendar_repository
from services.public_api.api.metrics import (
    get_calendar_repository as get_metrics_calendar_repository,
)
from services.public_api.api.metrics import get_stock_metrics_repository
from services.public_api.api.stocks import get_stock_search_repository
from services.public_api.core.config import get_cors_allowed_origins
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


# --- GET /api/v1/screen (UNIT-07, REQ-003) ---

import services.public_api.api.screen as screen_module  # noqa: E402
from services.public_api.api.screen import (  # noqa: E402
    get_calendar_repository as get_screen_calendar_repository,
)
from services.public_api.api.screen import get_screen_repository  # noqa: E402
from services.public_api.db.screen_repository import (  # noqa: E402
    ScreenFilters,
    ScreenQueryResult,
    ScreenRow,
)


def _patch_screen_now(monkeypatch, fixed: datetime) -> None:
    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed

    monkeypatch.setattr(screen_module, "datetime", _FixedDatetime)


_TRADING_DAY = date(2026, 9, 11)
_CALENDAR_ROWS = {
    (_TRADING_DAY, "KRX"): CalendarRow(
        trade_date=_TRADING_DAY,
        market="KRX",
        is_trading_day=True,
        session_close_at=time(15, 30),
        holiday_name=None,
        source="test",
    )
}

_SCREEN_ROW = ScreenRow(
    stock_code="005930",
    name="삼성전자",
    market="KOSPI",
    return_pct=Decimal("3.2"),
    per_percentile=Decimal("20.0"),
    pbr_percentile=Decimal("30.0"),
    market_cap_percentile=Decimal("10.0"),
    volume_anomaly_score=Decimal("2.3"),
)


class FakeScreenRepository:
    def __init__(
        self,
        *,
        published_trade_date: date | None,
        result: ScreenQueryResult,
    ):
        self._published_trade_date = published_trade_date
        self._result = result
        self.captured_filters: ScreenFilters | None = None

    def get_current_published_trade_date(self, market: str) -> date | None:
        return self._published_trade_date

    def search(self, filters: ScreenFilters) -> ScreenQueryResult:
        self.captured_filters = filters
        return self._result


def _override_screen_repository(repository: FakeScreenRepository):
    def _factory():
        return repository

    return _factory


def _setup_screen_overrides(
    monkeypatch, *, repository: FakeScreenRepository, calendar_rows=None
) -> None:
    _patch_screen_now(monkeypatch, datetime(2026, 9, 11, 20, 0, tzinfo=KST))
    app.dependency_overrides[get_screen_repository] = _override_screen_repository(repository)
    app.dependency_overrides[get_screen_calendar_repository] = _override_repository(
        _CALENDAR_ROWS if calendar_rows is None else calendar_rows
    )


def test_screen_default_params_success(monkeypatch):
    repo = FakeScreenRepository(
        published_trade_date=_TRADING_DAY,
        result=ScreenQueryResult(items=[_SCREEN_ROW], total_count=1),
    )
    _setup_screen_overrides(monkeypatch, repository=repo)
    client = TestClient(app)

    resp = client.get("/api/v1/screen")

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["total_count"] == 1
    assert body["data"]["page"] == 1
    item = body["data"]["items"][0]
    assert item["stock_code"] == "005930"
    # sort_by 기본값(return_pct)만 matched_metrics에 포함되어야 한다(필터 값 없음).
    assert item["matched_metrics"] == {"return_pct": 3.2}
    assert body["meta"]["data_freshness"]["is_latest_trading_day"] is True
    assert repo.captured_filters.market == "ALL"
    assert repo.captured_filters.sort_by == "return_pct"
    assert repo.captured_filters.sort_dir == "desc"
    assert repo.captured_filters.page == 1
    assert repo.captured_filters.page_size == 50


def test_screen_market_cap_filter_included_in_matched_metrics(monkeypatch):
    repo = FakeScreenRepository(
        published_trade_date=_TRADING_DAY,
        result=ScreenQueryResult(items=[_SCREEN_ROW], total_count=1),
    )
    _setup_screen_overrides(monkeypatch, repository=repo)
    client = TestClient(app)

    resp = client.get("/api/v1/screen", params={"market_cap_min": 100_000_000_000})

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    item = resp.json()["data"]["items"][0]
    # 필터 조건(market_cap) ∪ sort_by 기본값(return_pct) — 둘 다 포함되어야 한다(DEC-013).
    assert item["matched_metrics"] == {"market_cap": 10.0, "return_pct": 3.2}
    assert repo.captured_filters.market_cap_min == 100_000_000_000


def test_screen_volume_min_filters_but_excluded_from_matched_metrics(monkeypatch):
    """§4-3(원본 거래량 노출 금지)에 따라 volume_min은 필터로는 동작하되
    matched_metrics에는 노출되지 않는다(unit-07-note.md §2 참조)."""
    repo = FakeScreenRepository(
        published_trade_date=_TRADING_DAY,
        result=ScreenQueryResult(items=[_SCREEN_ROW], total_count=1),
    )
    _setup_screen_overrides(monkeypatch, repository=repo)
    client = TestClient(app)

    resp = client.get("/api/v1/screen", params={"volume_min": 10_000})

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    item = resp.json()["data"]["items"][0]
    assert item["matched_metrics"] == {"return_pct": 3.2}
    assert repo.captured_filters.volume_min == 10_000


def test_screen_per_pbr_sort_by_matched_metrics(monkeypatch):
    repo = FakeScreenRepository(
        published_trade_date=_TRADING_DAY,
        result=ScreenQueryResult(items=[_SCREEN_ROW], total_count=1),
    )
    _setup_screen_overrides(monkeypatch, repository=repo)
    client = TestClient(app)

    resp = client.get(
        "/api/v1/screen", params={"pbr_max": 1.5, "sort_by": "per", "sort_dir": "asc"}
    )

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    item = resp.json()["data"]["items"][0]
    assert item["matched_metrics"] == {"pbr": 30.0, "per": 20.0}


def test_screen_zero_results_returns_empty_list(monkeypatch):
    repo = FakeScreenRepository(
        published_trade_date=_TRADING_DAY,
        result=ScreenQueryResult(items=[], total_count=0),
    )
    _setup_screen_overrides(monkeypatch, repository=repo)
    client = TestClient(app)

    resp = client.get("/api/v1/screen", params={"market": "KOSDAQ"})

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["items"] == []
    assert body["data"]["total_count"] == 0
    assert repo.captured_filters.market == "KOSDAQ"


def test_screen_invalid_market_returns_400(monkeypatch):
    repo = FakeScreenRepository(published_trade_date=None, result=ScreenQueryResult([], 0))
    _setup_screen_overrides(monkeypatch, repository=repo)
    client = TestClient(app)

    resp = client.get("/api/v1/screen", params={"market": "NASDAQ"})

    app.dependency_overrides.clear()
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_PARAMETER"
    assert repo.captured_filters is None


def test_screen_invalid_sort_by_returns_400(monkeypatch):
    repo = FakeScreenRepository(published_trade_date=None, result=ScreenQueryResult([], 0))
    _setup_screen_overrides(monkeypatch, repository=repo)
    client = TestClient(app)

    resp = client.get("/api/v1/screen", params={"sort_by": "volume"})

    app.dependency_overrides.clear()
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_PARAMETER"


def test_screen_invalid_sort_dir_returns_400(monkeypatch):
    repo = FakeScreenRepository(published_trade_date=None, result=ScreenQueryResult([], 0))
    _setup_screen_overrides(monkeypatch, repository=repo)
    client = TestClient(app)

    resp = client.get("/api/v1/screen", params={"sort_dir": "descending"})

    app.dependency_overrides.clear()
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_PARAMETER"


def test_screen_page_size_exceeds_max_returns_400(monkeypatch):
    repo = FakeScreenRepository(published_trade_date=None, result=ScreenQueryResult([], 0))
    _setup_screen_overrides(monkeypatch, repository=repo)
    client = TestClient(app)

    resp = client.get("/api/v1/screen", params={"page_size": 201})

    app.dependency_overrides.clear()
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_PARAMETER"


def test_screen_market_cap_min_greater_than_max_returns_400(monkeypatch):
    repo = FakeScreenRepository(published_trade_date=None, result=ScreenQueryResult([], 0))
    _setup_screen_overrides(monkeypatch, repository=repo)
    client = TestClient(app)

    resp = client.get(
        "/api/v1/screen", params={"market_cap_min": 2_000, "market_cap_max": 1_000}
    )

    app.dependency_overrides.clear()
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_PARAMETER"
    assert repo.captured_filters is None


def test_screen_return_pct_min_greater_than_max_returns_400(monkeypatch):
    repo = FakeScreenRepository(published_trade_date=None, result=ScreenQueryResult([], 0))
    _setup_screen_overrides(monkeypatch, repository=repo)
    client = TestClient(app)

    resp = client.get(
        "/api/v1/screen", params={"return_pct_min": 5, "return_pct_max": -5}
    )

    app.dependency_overrides.clear()
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_PARAMETER"


def test_screen_calendar_not_confirmed_returns_424(monkeypatch):
    repo = FakeScreenRepository(published_trade_date=_TRADING_DAY, result=ScreenQueryResult([], 0))
    _setup_screen_overrides(monkeypatch, repository=repo, calendar_rows={})
    client = TestClient(app)

    resp = client.get("/api/v1/screen")

    app.dependency_overrides.clear()
    assert resp.status_code == 424
    assert resp.json()["error"]["code"] == "CALENDAR_NOT_CONFIRMED"


def test_screen_no_published_data_returns_503_data_pipeline_stale(monkeypatch):
    repo = FakeScreenRepository(published_trade_date=None, result=ScreenQueryResult([], 0))
    _setup_screen_overrides(monkeypatch, repository=repo)
    client = TestClient(app)

    resp = client.get("/api/v1/screen")

    app.dependency_overrides.clear()
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "DATA_PIPELINE_STALE"


def test_screen_pagination_params_passed_through(monkeypatch):
    repo = FakeScreenRepository(
        published_trade_date=_TRADING_DAY,
        result=ScreenQueryResult(items=[_SCREEN_ROW], total_count=120),
    )
    _setup_screen_overrides(monkeypatch, repository=repo)
    client = TestClient(app)

    resp = client.get("/api/v1/screen", params={"page": 3, "page_size": 20})

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["page"] == 3
    assert body["data"]["total_count"] == 120
    assert repo.captured_filters.page == 3
    assert repo.captured_filters.page_size == 20


# --- GET /api/v1/market-summary (UNIT-08, REQ-004) ---

import services.public_api.api.market_summary as market_summary_module  # noqa: E402
from services.public_api.api.market_summary import (  # noqa: E402
    get_calendar_repository as get_market_summary_calendar_repository,
)
from services.public_api.api.market_summary import (  # noqa: E402
    get_market_summary_repository,
)
from services.public_api.db.market_summary_repository import (  # noqa: E402
    MarketSummaryRow,
    SectorSummaryRow,
)


def _patch_market_summary_now(monkeypatch, fixed: datetime) -> None:
    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed

    monkeypatch.setattr(market_summary_module, "datetime", _FixedDatetime)


_MS_TRADING_DAY = date(2026, 9, 14)
_MS_CALENDAR_ROWS = {
    (_MS_TRADING_DAY, "KRX"): CalendarRow(
        trade_date=_MS_TRADING_DAY,
        market="KRX",
        is_trading_day=True,
        session_close_at=time(15, 30),
        holiday_name=None,
        source="test",
    )
}


def _ms_row(
    market: str, *, advancers: int = 1, decliners: int = 1, unchanged: int = 0
) -> MarketSummaryRow:
    return MarketSummaryRow(
        market=market,
        advancers_count=advancers,
        decliners_count=decliners,
        unchanged_count=unchanged,
        top_sectors_by_value=[SectorSummaryRow(sector="반도체", trading_value_krw=1_000_000)],
        total_trading_value_krw=5_418_400_000_000,
    )


class FakeMarketSummaryRepository:
    """AC-2 검증용 Fake — `get_summary`는 (trade_date, market) 키가 없으면
    `None`을 반환해 `_require_summary()`의 503 SERVICE_UNAVAILABLE 경로를
    재현할 수 있게 한다(unit-08-note.md §2 편차3)."""

    def __init__(
        self,
        *,
        published_trade_date: date | None,
        rows: dict[tuple[date, str], MarketSummaryRow],
    ):
        self._published_trade_date = published_trade_date
        self._rows = rows
        self.requested_markets: list[str] = []

    def get_current_published_trade_date(self, market: str) -> date | None:
        return self._published_trade_date

    def get_summary(self, trade_date: date, market: str) -> MarketSummaryRow | None:
        self.requested_markets.append(market)
        return self._rows.get((trade_date, market))


def _override_market_summary_repository(repository: FakeMarketSummaryRepository):
    def _factory():
        return repository

    return _factory


def _setup_market_summary_overrides(
    monkeypatch, *, repository: FakeMarketSummaryRepository, calendar_rows=None
) -> None:
    _patch_market_summary_now(monkeypatch, datetime(2026, 9, 14, 20, 0, tzinfo=KST))
    app.dependency_overrides[get_market_summary_repository] = (
        _override_market_summary_repository(repository)
    )
    app.dependency_overrides[get_market_summary_calendar_repository] = _override_repository(
        _MS_CALENDAR_ROWS if calendar_rows is None else calendar_rows
    )


_FULL_MS_ROWS = {
    (_MS_TRADING_DAY, "ALL"): _ms_row("ALL", advancers=2, decliners=2),
    (_MS_TRADING_DAY, "KOSPI"): _ms_row("KOSPI"),
    (_MS_TRADING_DAY, "KOSDAQ"): _ms_row("KOSDAQ", advancers=1, decliners=1),
}


def test_market_summary_default_returns_all_with_by_market(monkeypatch):
    repo = FakeMarketSummaryRepository(published_trade_date=_MS_TRADING_DAY, rows=_FULL_MS_ROWS)
    _setup_market_summary_overrides(monkeypatch, repository=repo)
    client = TestClient(app)

    resp = client.get("/api/v1/market-summary")

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    body = resp.json()
    data = body["data"]
    assert data["market"] == "ALL"
    assert data["advancers_count"] == 2
    assert data["decliners_count"] == 2
    assert data["by_market"] is not None
    assert {item["market"] for item in data["by_market"]} == {"KOSPI", "KOSDAQ"}
    assert body["meta"]["data_freshness"]["is_latest_trading_day"] is True
    # market 파라미터 생략 시 fetch되는 대상은 ALL + by_market 세부 2건(KOSPI/KOSDAQ) 총 3회.
    assert repo.requested_markets == ["ALL", "KOSPI", "KOSDAQ"]


def test_market_summary_explicit_kospi_by_market_is_null(monkeypatch):
    repo = FakeMarketSummaryRepository(published_trade_date=_MS_TRADING_DAY, rows=_FULL_MS_ROWS)
    _setup_market_summary_overrides(monkeypatch, repository=repo)
    client = TestClient(app)

    resp = client.get("/api/v1/market-summary", params={"market": "KOSPI"})

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["market"] == "KOSPI"
    # 필드 자체는 존재하되 값이 null (§2 편차2 — 필드 생략이 아니라 null 표현).
    assert "by_market" in data
    assert data["by_market"] is None
    assert repo.requested_markets == ["KOSPI"]  # KOSDAQ/ALL 조회 안 함(불필요한 조회 없음)


def test_market_summary_explicit_kosdaq_success(monkeypatch):
    repo = FakeMarketSummaryRepository(published_trade_date=_MS_TRADING_DAY, rows=_FULL_MS_ROWS)
    _setup_market_summary_overrides(monkeypatch, repository=repo)
    client = TestClient(app)

    resp = client.get("/api/v1/market-summary", params={"market": "KOSDAQ"})

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["market"] == "KOSDAQ"
    assert data["by_market"] is None


def test_market_summary_invalid_market_returns_400(monkeypatch):
    repo = FakeMarketSummaryRepository(published_trade_date=None, rows={})
    _setup_market_summary_overrides(monkeypatch, repository=repo)
    client = TestClient(app)

    resp = client.get("/api/v1/market-summary", params={"market": "NASDAQ"})

    app.dependency_overrides.clear()
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_PARAMETER"
    assert repo.requested_markets == []  # 리포지토리까지 도달하지 않음


def test_market_summary_calendar_not_confirmed_returns_424(monkeypatch):
    repo = FakeMarketSummaryRepository(published_trade_date=_MS_TRADING_DAY, rows=_FULL_MS_ROWS)
    _setup_market_summary_overrides(monkeypatch, repository=repo, calendar_rows={})
    client = TestClient(app)

    resp = client.get("/api/v1/market-summary")

    app.dependency_overrides.clear()
    assert resp.status_code == 424
    assert resp.json()["error"]["code"] == "CALENDAR_NOT_CONFIRMED"


def test_market_summary_no_published_data_returns_503_data_pipeline_stale(monkeypatch):
    repo = FakeMarketSummaryRepository(published_trade_date=None, rows={})
    _setup_market_summary_overrides(monkeypatch, repository=repo)
    client = TestClient(app)

    resp = client.get("/api/v1/market-summary")

    app.dependency_overrides.clear()
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "DATA_PIPELINE_STALE"


def test_market_summary_published_pointer_but_missing_row_returns_503_service_unavailable(
    monkeypatch,
):
    """AC-2 5번째 불릿 — 발행 포인터는 있는데 (trade_date, market) 요약 행이
    없으면 0으로 채우지 않고 503 SERVICE_UNAVAILABLE을 반환해야 한다
    (unit-08-note.md §2 편차3)."""
    repo = FakeMarketSummaryRepository(
        published_trade_date=_MS_TRADING_DAY, rows={}
    )  # 포인터는 있으나 summary 행이 전혀 없음
    _setup_market_summary_overrides(monkeypatch, repository=repo)
    client = TestClient(app)

    resp = client.get("/api/v1/market-summary")

    app.dependency_overrides.clear()
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "SERVICE_UNAVAILABLE"


def test_market_summary_by_market_partial_missing_also_returns_503(monkeypatch):
    """ALL 행은 있으나 by_market 세부(KOSPI/KOSDAQ) 중 하나가 없는 배치
    정합성 이상 케이스도 0으로 채우지 않고 503이어야 한다."""
    rows = {(_MS_TRADING_DAY, "ALL"): _ms_row("ALL")}  # KOSPI/KOSDAQ 행 누락
    repo = FakeMarketSummaryRepository(published_trade_date=_MS_TRADING_DAY, rows=rows)
    _setup_market_summary_overrides(monkeypatch, repository=repo)
    client = TestClient(app)

    resp = client.get("/api/v1/market-summary")

    app.dependency_overrides.clear()
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "SERVICE_UNAVAILABLE"


def test_market_summary_no_raw_price_fields_in_response(monkeypatch):
    """§4-3 — 원본 시세(open/high/low/close/volume)나 원본 거래대금
    (trading_value)이 응답 어디에도 존재하지 않는다."""
    repo = FakeMarketSummaryRepository(published_trade_date=_MS_TRADING_DAY, rows=_FULL_MS_ROWS)
    _setup_market_summary_overrides(monkeypatch, repository=repo)
    client = TestClient(app)

    resp = client.get("/api/v1/market-summary")

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    body_text = resp.text
    forbidden_fields = (
        '"open"', '"high"', '"low"', '"close"', '"volume"', '"trading_value"'
    )
    for forbidden_field in forbidden_fields:
        assert forbidden_field not in body_text
    # 노출되는 금액 필드는 KRW 단위임을 필드명으로 자기서술(DEC-015)해야 한다.
    assert "total_trading_value_krw" in body_text
    assert "trading_value_krw" in body_text


def test_market_summary_explicit_date_param(monkeypatch):
    other_day = date(2026, 9, 11)
    rows = {
        (other_day, "ALL"): _ms_row("ALL"),
        (other_day, "KOSPI"): _ms_row("KOSPI"),
        (other_day, "KOSDAQ"): _ms_row("KOSDAQ"),
    }
    calendar_rows = dict(_MS_CALENDAR_ROWS)
    calendar_rows[(other_day, "KRX")] = CalendarRow(
        trade_date=other_day,
        market="KRX",
        is_trading_day=True,
        session_close_at=time(15, 30),
        holiday_name=None,
        source="test",
    )
    repo = FakeMarketSummaryRepository(published_trade_date=_MS_TRADING_DAY, rows=rows)
    _setup_market_summary_overrides(monkeypatch, repository=repo, calendar_rows=calendar_rows)
    client = TestClient(app)

    resp = client.get("/api/v1/market-summary", params={"date": "2026-09-11"})

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["data_freshness"]["trade_date"] == "2026-09-11"
    assert body["meta"]["data_freshness"]["is_latest_trading_day"] is False


def test_market_summary_invalid_date_format_returns_400(monkeypatch):
    repo = FakeMarketSummaryRepository(published_trade_date=None, rows={})
    _setup_market_summary_overrides(monkeypatch, repository=repo)
    client = TestClient(app)

    resp = client.get("/api/v1/market-summary", params={"date": "not-a-date"})

    app.dependency_overrides.clear()
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_PARAMETER"


def test_market_summary_req009_blackbox_headers_and_cookies_do_not_change_response(monkeypatch):
    """REQ-009 — 사용자 식별 파라미터가 없고, 동일 쿼리에 다른 Authorization/
    쿠키를 붙여도 응답이 완전히 동일해야 한다(UNIT-04가 확립한 블랙박스
    패턴, unit-08-note.md §1-2)."""
    repo = FakeMarketSummaryRepository(published_trade_date=_MS_TRADING_DAY, rows=_FULL_MS_ROWS)
    _setup_market_summary_overrides(monkeypatch, repository=repo)
    client = TestClient(app)

    resp_plain = client.get("/api/v1/market-summary")
    resp_with_auth = client.get(
        "/api/v1/market-summary",
        headers={"Authorization": "Bearer some-fake-token"},
        cookies={"session_id": "abc123", "user_id": "999"},
    )
    resp_with_unknown_param = client.get(
        "/api/v1/market-summary", params={"user_id": "999"}
    )

    app.dependency_overrides.clear()
    assert resp_plain.status_code == resp_with_auth.status_code == 200
    assert resp_plain.json()["data"] == resp_with_auth.json()["data"]
    assert resp_plain.json()["data"] == resp_with_unknown_param.json()["data"]


# --- 회귀 수정: DEF-U09-01(Critical) — CORS 미들웨어 부재 -------------------------
# 03-system-design.md §6-3 "CORS는 자사 프론트엔드 오리진으로만 제한". 6단계
# (unit-09-test.md TC-031)가 프론트엔드/백엔드 두 오리진 브라우저 fetch가
# 100% 차단됨을 발견해 규칙 F 피드백 루프로 main.py에 CORSMiddleware를 추가했다.


def test_cors_allows_default_localhost_frontend_origin():
    def _override_db():
        yield FakeDbSession()

    app.dependency_overrides[get_db] = _override_db
    client = TestClient(app)

    resp = client.get(
        "/api/v1/health", headers={"Origin": "http://localhost:3000"}
    )

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_cors_blocks_unlisted_origin():
    def _override_db():
        yield FakeDbSession()

    app.dependency_overrides[get_db] = _override_db
    client = TestClient(app)

    resp = client.get(
        "/api/v1/health", headers={"Origin": "http://evil.example.com"}
    )

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert "access-control-allow-origin" not in resp.headers


def test_get_cors_allowed_origins_reads_comma_separated_env_var(monkeypatch):
    monkeypatch.setenv(
        "PUBLIC_API_CORS_ALLOWED_ORIGINS",
        " https://stock-screener.example.com , https://www.stock-screener.example.com ",
    )

    origins = get_cors_allowed_origins()

    assert origins == [
        "https://stock-screener.example.com",
        "https://www.stock-screener.example.com",
    ]


def test_get_cors_allowed_origins_falls_back_to_default_when_unset(monkeypatch):
    monkeypatch.delenv("PUBLIC_API_CORS_ALLOWED_ORIGINS", raising=False)

    origins = get_cors_allowed_origins()

    assert origins == ["http://localhost:3000"]
