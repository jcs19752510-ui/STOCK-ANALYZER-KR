"""장중 재계산(DEC-089·090) 임시 DB 통합 시험 — 실제 PostgreSQL·실제 SQL·읽기 전용 `api_service` 계정.

픽스처(T00001~T00010, 130거래일, 기준 거래일 2026-09-30)를 배치로 산출·발행한 뒤:
1) 가상 테이블(`jsonb_to_recordset`) 저장소가 기존 저장소와 **같은 결과**를 내는지(동치),
2) 확정일을 "오늘 행"으로 넣어 재계산하면 배치가 만든 값과 같은지(골든),
3) 실제 API(`/api/v1/local/screen*`)가 기존 응답과 같고 `basis`·`meta.live`를 더하는지,
4) 일봉 보충(DEC-090)·스냅샷·편입 이탈·접근 통제·성능을 확인한다. 개발 DB에는 아무것도 쓰지 않는다.
"""

# ruff: noqa: E501
from __future__ import annotations

import itertools
import time
import types
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from services.public_api.api import local_screen
from services.public_api.api.local_realtime import require_owner
from services.public_api.core.pattern_config import load_pattern_thresholds
from services.public_api.db.pattern_repository import PatternFilters, SqlPatternScreenRepository
from services.public_api.db.screen_repository import ScreenFilters, SqlScreenRepository
from services.public_api.live_screen.fill import BaseFiller
from services.public_api.live_screen.rows import RECOMPUTED_COLUMNS, build_live_rows
from services.public_api.live_screen.service import LiveScreenService, QuoteState, ServiceDeps
from services.public_api.live_screen.types import DailyBar
from services.public_api.live_screen.virtual import build_virtual_source, dump_rows
from services.public_api.main import app
from services.public_api.realtime.market import MarketQuote, MarketSnapshotPoller
from shared.db_models.public_serving import DerivedMetricsDaily, KisDailyBar
from tests.integration.pattern_api_env import api_client, prepare_database, seed_calendar
from tests.integration.pattern_fixtures import TARGET_DATE, build_stocks
from tests.integration.pg_temp_db import TempDb, TempDbUnavailable, temp_database

KST = ZoneInfo("Asia/Seoul")
TH = load_pattern_thresholds()
CODES = sorted(build_stocks())


@pytest.fixture(scope="module")
def db() -> Iterator[TempDb]:
    try:
        with temp_database() as tdb:
            prepare_database(tdb)
            yield tdb
    except TempDbUnavailable as exc:
        pytest.skip(f"임시 DB를 만들 수 없어 건너뜀(통과로 세지 않음): {exc}")


@pytest.fixture(scope="module")
def api_session(db) -> Iterator[Session]:
    engine = create_engine(TempDb.render(db.api_url))
    session = Session(engine)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def published_rows(session: Session) -> list[dict]:
    rows = session.execute(select(DerivedMetricsDaily).where(DerivedMetricsDaily.trade_date == TARGET_DATE)).scalars()
    return [{c.key: getattr(r, c.key) for c in DerivedMetricsDaily.__table__.columns} for r in rows]


def virtual_repo(session: Session, rows: list[dict]):
    return build_virtual_source(dump_rows(rows, trade_date=TARGET_DATE))


# ───────────────────────── 1) 동치: 가상 테이블 = 기존 테이블 ─────────────────────────
SCREEN_COMBOS = [
    {},
    {"market": "KOSPI"},
    {"market": "KOSDAQ"},
    {"market_cap_min": 1},
    {"volume_min": 100000},
    {"return_pct_min": -1, "return_pct_max": 1},
    {"ma5_gap_pct_min": -5, "ma5_gap_pct_max": 5},
    {"ma20_gap_pct_min": -5, "ma20_gap_pct_max": 5},
    {"volume_anomaly_score_min": -3, "volume_anomaly_score_max": 3},
    {"per_max": 100},
    {"pbr_max": 100},
]
SORTS = ["return_pct", "market_cap", "per", "pbr", "volume_anomaly_score", "ma5_gap_pct", "ma20_gap_pct"]


def screen_filters(**kw) -> ScreenFilters:
    base = dict(
        trade_date=TARGET_DATE, market="ALL", market_cap_min=None, market_cap_max=None, volume_min=None,
        return_pct_min=None, return_pct_max=None, per_max=None, pbr_max=None, ma5_gap_pct_min=None,
        ma5_gap_pct_max=None, ma20_gap_pct_min=None, ma20_gap_pct_max=None, volume_anomaly_score_min=None,
        volume_anomaly_score_max=None, sort_by="return_pct", sort_dir="desc", page=1, page_size=50,
    )
    base.update(kw)
    return ScreenFilters(**base)


def test_virtual_screen_equals_real_for_all_filters_and_sorts(api_session):
    real = SqlScreenRepository(api_session)
    live = SqlScreenRepository(api_session, virtual_repo(api_session, published_rows(api_session)))
    checked = 0
    for combo, sort_by, sort_dir in itertools.product(SCREEN_COMBOS, SORTS, ("asc", "desc")):
        f = screen_filters(sort_by=sort_by, sort_dir=sort_dir, **combo)
        a, b = real.search(f), live.search(f)
        assert a == b, (combo, sort_by, sort_dir)
        assert real.matching_codes(f) == live.matching_codes(f)
        checked += 1
    assert checked == len(SCREEN_COMBOS) * len(SORTS) * 2
    # 페이지 경계
    f = screen_filters(page=2, page_size=3)
    assert real.search(f) == live.search(f)


def pattern_filters(**kw) -> PatternFilters:
    base = dict(
        trade_date=TARGET_DATE, market="ALL", required=("c1", "c2", "c3", "c4", "c5", "c9"), market_cap_min=None,
        volume_min=None, sort_by="market_cap", sort_dir="desc", page=1, page_size=50,
    )
    base.update(kw)
    return PatternFilters(**base)


def test_virtual_pattern_equals_real_for_conditions_sorts_and_readiness(api_session):
    real = SqlPatternScreenRepository(api_session)
    live = SqlPatternScreenRepository(api_session, virtual_repo(api_session, published_rows(api_session)))
    required_sets = [(), ("c1",), ("c2",), ("c3",), ("c4",), ("c5",), ("c9",), ("c1", "c2"), ("c1", "c2", "c3", "c4", "c5", "c9")]
    for req, sort_by, sort_dir, market in itertools.product(required_sets, ["market_cap", "ma60_gap_pct", "sideways_range_pct", "ma_convergence_pct"], ("asc", "desc"), ("ALL", "KOSPI", "KOSDAQ")):
        f = pattern_filters(required=req, sort_by=sort_by, sort_dir=sort_dir, market=market)
        assert real.search(f, TH) == live.search(f, TH), (req, sort_by, sort_dir, market)
        assert real.matching_codes(f, TH) == live.matching_codes(f, TH)
    assert real.readiness(TARGET_DATE, "ALL", TH) == live.readiness(TARGET_DATE, "ALL", TH)
    assert real.readiness(TARGET_DATE, "KOSPI", TH) == live.readiness(TARGET_DATE, "KOSPI", TH)
    f1 = pattern_filters(required=(), page_size=200, stock_code="T00001")
    assert real.search(f1, TH) == live.search(f1, TH)


def test_virtual_source_handles_null_decimal_precision_and_empty(api_session):
    rows = published_rows(api_session)
    rows[0] = {**rows[0], "return_pct": None, "ma60_cross_up_days": None, "recent_surge_flag": None}
    live = SqlScreenRepository(api_session, virtual_repo(api_session, rows))
    res = live.search(screen_filters(page_size=200))
    got = {i.stock_code: i for i in res.items}
    assert got[rows[0]["stock_code"]].return_pct is None
    # 소수 정밀도 보존: 실제 값과 같은 Decimal
    real = {i.stock_code: i for i in SqlScreenRepository(api_session).search(screen_filters(page_size=200)).items}
    other = rows[1]["stock_code"]
    assert got[other].ma20_gap_pct == real[other].ma20_gap_pct
    # 빈 목록
    empty = SqlScreenRepository(api_session, virtual_repo(api_session, []))
    assert empty.search(screen_filters()).items == [] and empty.search(screen_filters()).total_count == 0


def test_virtual_payload_is_bound_not_interpolated(api_session):
    """값은 바인드 파라미터로만 간다 — 따옴표·SQL 조각이 든 문자열 값이 있어도 쿼리가 깨지지 않고 그대로 읽힌다."""
    rows = published_rows(api_session)
    rows[0] = {**rows[0], "per_unavailable_reason": "LOSS"}
    payload = dump_rows(rows, trade_date=TARGET_DATE).replace('"LOSS"', "\"LOSS'); DROP TABLE x; --\"")
    src = build_virtual_source(payload)
    with pytest.raises(DBAPIError) as ei:  # 값은 데이터로만 읽힌다: 길이 제한(VARCHAR(12))에서 거부될 뿐 SQL 구조는 바뀌지 않는다
        api_session.execute(select(src.stock_code)).all()
    assert "too long" in str(ei.value).lower()
    api_session.rollback()
    assert api_session.execute(text("select count(*) from public_serving.stock_master")).scalar_one() == len(CODES)  # 테이블은 그대로


# ───────────────────────── 2) 골든: 확정일을 "오늘 행"으로 → 배치 값과 같다 ─────────────────────────
@pytest.fixture(scope="module")
def patched_factory(db):
    """`local_screen`이 읽는 DB 연결을 임시 DB의 읽기 전용 계정으로 바꾼다."""
    engine = create_engine(TempDb.render(db.api_url))
    mp = pytest.MonkeyPatch()
    mp.setattr(local_screen, "get_session_factory", lambda: sessionmaker(bind=engine, autoflush=False))
    yield
    mp.undo()
    engine.dispose()


def set_now(dt: datetime):
    local_screen.set_now_provider(lambda: dt)


def kst(y, m, d, hh=10, mm=0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=KST)


def test_history_loader_returns_100_rows_ascending(patched_factory):
    hist = local_screen.load_history(TARGET_DATE)
    assert sorted(hist) == CODES
    stocks = build_stocks()
    for code, bars in hist.items():
        assert len(bars) == min(100, len(stocks[code].closes))  # 이력이 짧은 픽스처 종목(T00008)은 그만큼만
        assert [b.trade_date for b in bars] == sorted(b.trade_date for b in bars)
        assert bars[-1].trade_date == TARGET_DATE


def prev_weekday(d: date) -> date:
    d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def test_golden_recompute_equals_batch_for_every_recomputed_column(api_session, patched_factory):
    """확정일(9/30)의 일봉을 오늘 진행 봉(시세)으로 넣고 9/29까지를 이력으로 주면, 배치가 만든 9/30 행과 모든 재계산 열이 같다."""
    hist_full = local_screen.load_history(TARGET_DATE)
    prev = prev_weekday(TARGET_DATE)
    history = {c: [b for b in bars if b.trade_date <= prev] for c, bars in hist_full.items()}
    published = published_rows(api_session)
    # 발행 행의 재계산 열을 일부러 엉뚱한 값으로 바꿔 둔다 → 같아지면 재계산이 실제로 덮어썼다는 증거
    tampered = []
    for r in published:
        t = dict(r)
        for col in RECOMPUTED_COLUMNS:
            if col in ("pattern_metrics_status",):
                t[col] = "INSUFFICIENT_HISTORY"
            elif col in ("recent_surge_flag",):
                t[col] = None
            elif col == "ma60_cross_up_days":
                t[col] = 9
            elif col == "volume_raw":
                t[col] = 1
            else:
                t[col] = Decimal("12345")
        tampered.append(t)
    now_ts = 1_000_000.0
    quotes = {}
    for c, bars in hist_full.items():
        last = bars[-1]
        assert last.trade_date == TARGET_DATE
        quotes[c] = MarketQuote(c, float(last.close), 0, 0, last.volume, 0, 0, 0, now_ts)
    res = build_live_rows(
        tampered, history, quotes, today=TARGET_DATE, basis_date=prev, expected_date=prev,
        trading_today=True, now_ts=now_ts,
    )
    assert res.excluded == [] and set(res.basis.values()) == {"live"}
    by = {r["stock_code"]: r for r in res.rows}
    for r in published:
        got = by[r["stock_code"]]
        for col in RECOMPUTED_COLUMNS:
            assert got[col] == r[col], (r["stock_code"], col, got[col], r[col])
        for col in ("per_raw", "pbr_raw", "market_cap_raw_krw", "per_percentile", "market_cap_percentile"):
            assert got[col] == r[col]  # 일봉 고정 열은 그대로
    # 소수점 배치 반올림 규칙까지 같은 순수 함수를 쓰므로 정확히 같다(허용오차 0).
    assert res.meta["return_rank_policy"] == "live" and res.meta["coverage_ratio"] == 1.0
    # 등락률 순위도 배치와 같다(모집단이 같으므로)
    for r in published:
        assert by[r["stock_code"]]["return_rank_pct"] == r["return_rank_pct"]


# ───────────────────────── 3) 실제 API(/api/v1/local/screen*) ─────────────────────────
class Env:
    """실제 앱 + 주입한 시세·증권사 일봉·시각. `min_interval=0`이면 요청마다 새로 계산한다."""

    def __init__(self, client, svc, runtime, quotes, clock):
        self.client, self.svc, self.runtime, self.quotes, self.clock = client, svc, runtime, quotes, clock

    def quote(self, code: str, price: float, volume: int, *, age: float = 0.0) -> None:
        self.quotes[code] = MarketQuote(code, price, 0.0, 0.0, volume, price, price, price, self.clock() - age)


def make_service(fetch, quotes, clock, *, min_interval=0.0, stale=False, workers=2):
    async def quote_state():
        return QuoteState(dict(quotes), stale, True, len(CODES))

    filler = BaseFiller(fetch, workers=workers, max_attempts=2, retry_delay=0.01)
    deps = ServiceDeps(
        load_context=local_screen.load_context, load_history=local_screen.load_history,
        quote_state=quote_state, filler=filler, clock=clock, min_interval=min_interval, refresh_seconds=10,
    )
    return LiveScreenService(deps)


@pytest.fixture()
def live_env(db, patched_factory, monkeypatch):
    """기본: 시세 없음, 보충 조회는 항상 빈 목록. 각 시험이 `env.quotes`·`fetch_impl`·시각을 채운다."""
    holder = types.SimpleNamespace(fetch=lambda code: [])
    quotes: dict[str, MarketQuote] = {}
    clock_box = [1_000_000.0]
    clock = lambda: clock_box[0]  # noqa: E731
    svc = make_service(lambda code: holder.fetch(code), quotes, clock)
    poller = MarketSnapshotPoller(lambda codes: {}, CODES)
    runtime = types.SimpleNamespace(poller=poller)
    monkeypatch.setattr(local_screen, "get_service", lambda settings: (svc, runtime))
    with api_client(db) as c:
        app.dependency_overrides[require_owner] = lambda: types.SimpleNamespace(configured=True)
        with c:  # 요청 사이에 이벤트 루프를 유지한다(백그라운드 보충 작업이 살아 있어야 함)
            env = Env(c, svc, runtime, quotes, clock)
            env.holder, env.clock_box = holder, clock_box
            yield env
    local_screen.set_now_provider(None)


def test_local_screen_after_close_equals_normal_screen_and_marks_daily(live_env):
    """장 마감 뒤(E=오늘, 발행=E): 시세와 무관하게 발행 값 그대로 — 기존 /screen과 같은 응답에 basis·meta.live만 더한다."""
    set_now(kst(2026, 9, 30, 17, 0))
    for params in ({}, {"market": "KOSPI", "sort_by": "per"}, {"return_pct_min": -2, "sort_by": "ma20_gap_pct", "sort_dir": "asc"},
                   {"volume_min": 90000, "page_size": 3, "page": 2}):
        a = live_env.client.get("/api/v1/screen", params=params)
        b = live_env.client.get("/api/v1/local/screen", params=params)
        assert a.status_code == 200 and b.status_code == 200, (a.text, b.text)
        da, db_ = a.json()["data"], b.json()["data"]
        assert db_["total_count"] == da["total_count"] and db_["page"] == da["page"]
        assert [i["stock_code"] for i in db_["items"]] == [i["stock_code"] for i in da["items"]]
        assert [i["matched_metrics"] for i in db_["items"]] == [i["matched_metrics"] for i in da["items"]]
        assert {i["basis"] for i in db_["items"]} <= {"daily"}
        live = b.json()["meta"]["live"]
        assert live["base_fill"]["state"] == "none" and live["volume_partial"] is True
        assert live["quotes_covered"] == 0 and live["basis_trade_date"] == live["expected_trade_date"] == "2026-09-30"
        assert b.headers["cache-control"] == "no-store"
        assert b.json()["meta"]["data_freshness"]["trade_date"] == "2026-09-30"


def test_local_pattern_after_close_equals_normal_pattern(live_env):
    set_now(kst(2026, 9, 30, 17, 0))
    for params in ({}, {"required": "c1,c2"}, {"required": "c4", "sort_by": "ma60_gap_pct", "sort_dir": "asc"}, {"market": "KOSDAQ"}):
        a = live_env.client.get("/api/v1/screen/pattern", params=params)
        b = live_env.client.get("/api/v1/local/screen/pattern", params=params)
        assert a.status_code == b.status_code, (a.text, b.text)
        if a.status_code != 200:
            continue
        da, db_ = a.json()["data"], b.json()["data"]
        for it in db_["items"]:
            assert it.pop("basis") == "daily"
        assert db_ == da


def test_local_screen_live_quotes_recompute_and_match_offline(live_env, api_session):
    """장중(P=E=9/30, 오늘=10/1 목요일): 시세를 받은 종목은 basis=live, 못 받은 종목은 발행 값 그대로(daily)."""
    set_now(kst(2026, 10, 1, 10, 0))
    hist = local_screen.load_history(TARGET_DATE)
    base = {c: hist[c][-1] for c in CODES}
    for c in CODES[:8]:  # 10종목 중 8종목만 시세(커버율 80% → 등락률 순위는 일봉 고정)
        live_env.quote(c, float(base[c].close) * 1.03, 5000)
    r = live_env.client.get("/api/v1/local/screen", params={"page_size": 200})
    assert r.status_code == 200, r.text
    body = r.json()
    meta = body["meta"]["live"]
    assert meta["quotes_covered"] == 8 and meta["quotes_total"] == 10 and meta["return_rank_policy"] == "daily"
    assert meta["expected_trade_date"] == "2026-09-30" and meta["today"] == "2026-10-01"
    by = {i["stock_code"]: i for i in body["data"]["items"]}
    assert {c for c, i in by.items() if i["basis"] == "live"} == set(CODES[:8])
    assert all(by[c]["basis"] == "daily" for c in CODES[8:] if c in by)
    # 오프라인 재계산과 일치: 재계산된 return_pct = (현재가 - 직전 종가) / 직전 종가
    for c in CODES[:8]:
        if c in by and by[c]["matched_metrics"].get("return_pct") is not None:
            assert by[c]["matched_metrics"]["return_pct"] == pytest.approx(3.0, abs=0.05), c
    assert "fetched_at" not in r.text and "inter2_" not in r.text  # 원본 시세·증권사 응답 필드는 응답에 없다
    # 보이는 종목은 우선 순환에 올라간다
    assert set(live_env.runtime.poller.priority_codes()) == {i["stock_code"] for i in body["data"]["items"]}
    assert meta["priority_codes"] == len(body["data"]["items"])


def test_local_screen_requires_quotes_when_live_applies(live_env):
    set_now(kst(2026, 10, 1, 10, 0))
    r = live_env.client.get("/api/v1/local/screen")
    assert r.status_code == 503 and r.json()["error"]["code"] == "LIVE_QUOTES_NOT_READY"


def test_stale_quotes_are_treated_as_missing(live_env):
    set_now(kst(2026, 10, 1, 10, 0))
    base = {c: local_screen.load_history(TARGET_DATE)[c][-1] for c in CODES}
    for c in CODES:
        live_env.quote(c, float(base[c].close) * 1.02, 5000, age=301)  # STALE_QUOTE_SECONDS(300)보다 오래됨
    r = live_env.client.get("/api/v1/local/screen", params={"page_size": 200})
    assert r.status_code == 200
    assert {i["basis"] for i in r.json()["data"]["items"]} == {"daily"} and r.json()["meta"]["live"]["quotes_covered"] == 0


# ───────────────────────── 4) 일봉 보충(DEC-090) ─────────────────────────
def kis_bars_for(code: str, anchor: DailyBar, days: list[date], *, close_shift=Decimal(0), skip: set[date] | None = None) -> list[DailyBar]:
    """모의 증권사 일봉: P(발행 마지막 거래일) + 필요한 날짜들. 보충일 종가는 직전 종가에서 +1%씩."""
    out = [DailyBar(anchor.trade_date, anchor.open, anchor.high, anchor.low, anchor.close + close_shift, anchor.volume)]
    price = anchor.close
    for d in days:
        price = (price * Decimal("1.01")).quantize(Decimal(1))
        if skip and d in skip:
            continue
        out.append(DailyBar(d, price, price, price, price, anchor.volume + 1000))
    return out


def wait_filled(env: Env, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = env.svc._d.filler.status()
        if st is not None and st.state == "ready":
            return st
        time.sleep(0.02)
    raise AssertionError("보충이 끝나지 않았습니다.")


def test_gap_fill_flow_progress_then_ready_with_cross_checks(live_env):
    """P=9/30, 오늘=금요일 10/2 → E=10/1(1거래일 뒤처짐). 처음엔 503 LIVE_BASE_FILLING(진행률), 끝나면 200."""
    set_now(kst(2026, 10, 2, 10, 0))
    hist = local_screen.load_history(TARGET_DATE)
    anchors = {c: hist[c][-1] for c in CODES}
    needed = [date(2026, 10, 1)]
    bad_close, no_day, boom = "T00002", "T00003", "T00004"
    gate = {"open": False}

    def fetch(code):
        while not gate["open"]:
            time.sleep(0.005)
        if code == boom:
            raise RuntimeError("upstream down")
        shift = Decimal(5) if code == bad_close else Decimal(0)  # 발행 일봉과 종가가 다름(교차검증 불일치)
        return kis_bars_for(code, anchors[code], needed, close_shift=shift, skip={needed[0]} if code == no_day else None)

    live_env.holder.fetch = fetch
    r = live_env.client.get("/api/v1/local/screen")
    assert r.status_code == 503 and r.json()["error"]["code"] == "LIVE_BASE_FILLING"
    d = r.json()["error"]["details"]
    assert d["total"] == 10 and d["gap_days"] == 1 and d["done"] < 9
    gate["open"] = True
    st = wait_filled(live_env)
    assert st.filled == 7 and st.mismatched == 1 and st.missing == 1 and st.failed == 1 and st.attempted == 10
    base = anchors["T00001"]
    live_env.quote("T00001", float(base.close) * 1.02, 7000)
    r = live_env.client.get("/api/v1/local/screen", params={"page_size": 200})
    assert r.status_code == 200, r.text
    body = r.json()
    bf = body["meta"]["live"]["base_fill"]
    assert bf["gap_days"] == 1 and bf["state"] == "ready" and bf["total"] == 10
    assert bf["filled"] == 7 and bf["mismatched"] == 1 and bf["excluded"] == 3 and bf["pending"] == 0
    assert bf["source"] == "kis_daily_price"
    got = {i["stock_code"]: i["basis"] for i in body["data"]["items"]}
    for c in (bad_close, no_day, boom):
        assert c not in got  # 보충에 실패·불일치한 종목은 결과에서 빠진다(숨기지 않고 meta에 수로 표시)
    assert got["T00001"] == "live"
    assert all(b == "daily" for c, b in got.items() if c != "T00001")
    assert body["meta"]["live"]["basis_trade_date"] == "2026-09-30" and body["meta"]["live"]["expected_trade_date"] == "2026-10-01"


def test_gap_fill_from_db_cache_needs_no_kis_calls(live_env, db):
    """kis_daily_bar(DEC-097)에 P·E 행이 있으면 증권사 조회 0회로 보충이 끝난다."""
    set_now(kst(2026, 10, 2, 10, 0))
    hist = local_screen.load_history(TARGET_DATE)
    anchors = {c: hist[c][-1] for c in CODES}
    needed = [date(2026, 10, 1)]
    calls: list[str] = []

    def fetch(code):
        calls.append(code)
        return []

    live_env.holder.fetch = fetch
    live_env.svc._d.filler = BaseFiller(fetch, workers=2, max_attempts=2, retry_delay=0.01, cache_loader=local_screen.load_kis_cache)
    engine = create_engine(TempDb.render(db.migrator_url))
    try:
        with Session(engine) as session:
            for c in CODES:
                for b in kis_bars_for(c, anchors[c], needed):
                    session.add(KisDailyBar(stock_code=c, trade_date=b.trade_date, open=b.open, high=b.high, low=b.low, close=b.close, volume=b.volume))
            session.commit()
    finally:
        engine.dispose()
    live_env.client.get("/api/v1/local/screen")  # 보충 시작(첫 응답은 503일 수 있다)
    st = wait_filled(live_env)
    assert st.filled == 10 and st.from_cache == 10 and calls == [] and live_env.svc._d.filler.fetch_calls == 0
    live_env.quote("T00001", float(anchors["T00001"].close) * 1.02, 7000)
    r = live_env.client.get("/api/v1/local/screen", params={"page_size": 200})
    assert r.status_code == 200, r.text
    bf = r.json()["meta"]["live"]["base_fill"]
    assert bf["filled"] == 10 and bf["from_cache"] == 10 and bf["excluded"] == 0 and bf["state"] == "ready"
    engine = create_engine(TempDb.render(db.migrator_url))
    try:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM public_serving.kis_daily_bar"))  # 모듈 공유 DB — 다른 시험에 남기지 않는다
    finally:
        engine.dispose()


def test_gap_beyond_limit_is_stale(live_env):
    set_now(kst(2026, 10, 9, 10, 0))  # P=9/30 → E=10/8: 거래일 6개(10/1,2,5,6,7,8)
    r = live_env.client.get("/api/v1/local/screen")
    assert r.status_code == 409 and r.json()["error"]["code"] == "LIVE_BASE_STALE"
    assert "5거래일" in r.json()["error"]["message"]


def test_gap_recompute_uses_history_through_E_for_daily_rows(live_env):
    """보충된 E까지의 이력으로 다시 계산한 값(daily)은 발행 P 값이 아니라 E 기준이다."""
    set_now(kst(2026, 10, 2, 10, 0))
    hist = local_screen.load_history(TARGET_DATE)
    anchors = {c: hist[c][-1] for c in CODES}
    live_env.holder.fetch = lambda code: kis_bars_for(code, anchors[code], [date(2026, 10, 1)])
    live_env.client.get("/api/v1/local/screen")  # 보충 시작
    wait_filled(live_env)
    live_env.quote("T00001", float(anchors["T00001"].close), 1)  # 시세 하나(=커버율 10% → 등락률 순위 daily)
    r = live_env.client.get("/api/v1/local/screen", params={"page_size": 200, "sort_by": "return_pct"})
    assert r.status_code == 200
    items = {i["stock_code"]: i for i in r.json()["data"]["items"]}
    # E(10/1) 종가는 P 종가의 +1% → return_pct == +1.0 (daily 행도 E 기준)
    for c in CODES:
        if c == "T00001" or c not in items:
            continue
        assert items[c]["basis"] == "daily"
        assert items[c]["matched_metrics"]["return_pct"] == pytest.approx(1.0, abs=0.01), c


# ───────────────────────── 5) 스냅샷·편입 이탈·접근 통제 ─────────────────────────
def live_codes_at(env: Env, **params):
    r = env.client.get("/api/v1/local/screen", params={"page_size": 200, **params})
    assert r.status_code == 200, r.text
    return r.json()


def test_snapshot_reuse_pinning_and_expiry(live_env):
    set_now(kst(2026, 10, 1, 10, 0))
    base = {c: local_screen.load_history(TARGET_DATE)[c][-1] for c in CODES}
    for c in CODES:
        live_env.quote(c, float(base[c].close) * 1.01, 100)
    live_env.svc._d.min_interval = 5.0
    first = live_codes_at(live_env)
    sid = first["meta"]["live"]["snapshot_id"]
    computes = live_env.svc.computes_total
    second = live_codes_at(live_env)  # 최소 간격 안: 재사용(계산 1번)
    assert second["meta"]["live"]["snapshot_id"] == sid and live_env.svc.computes_total == computes
    # 간격이 지나면 새로 계산
    live_env.clock_box[0] += 6
    third = live_codes_at(live_env)
    assert third["meta"]["live"]["snapshot_id"] != sid and live_env.svc.computes_total == computes + 1
    # 시세가 크게 바뀌어도 고정한 스냅샷은 같은 결과 집합(일시정지 중 페이지 이동)
    for c in CODES:
        live_env.quote(c, float(base[c].close) * 0.5, 100)
    pinned = live_codes_at(live_env, snapshot_id=third["meta"]["live"]["snapshot_id"], page_size=3, page=2)
    assert pinned["meta"]["live"]["snapshot_id"] == third["meta"]["live"]["snapshot_id"]
    again = live_codes_at(live_env, snapshot_id=third["meta"]["live"]["snapshot_id"], page_size=3, page=2)
    assert pinned["data"] == again["data"]
    # 모르는 snapshot_id → 410, 형식이 틀리면 422(입력 검증)
    r = live_env.client.get("/api/v1/local/screen", params={"snapshot_id": "0" * 32})
    assert r.status_code == 410 and r.json()["error"]["code"] == "SNAPSHOT_EXPIRED"
    assert live_env.client.get("/api/v1/local/screen", params={"snapshot_id": "x;DROP"}).status_code in (400, 422)
    # 보관은 최근 5개
    for _ in range(7):
        live_env.clock_box[0] += 6
        live_codes_at(live_env)
    assert len(live_env.svc.store) == 5
    assert live_env.client.get("/api/v1/local/screen", params={"snapshot_id": sid}).status_code == 410


def test_changes_entered_and_left_between_snapshots(live_env):
    set_now(kst(2026, 10, 1, 10, 0))
    base = {c: local_screen.load_history(TARGET_DATE)[c][-1] for c in CODES}
    for c in CODES:
        live_env.quote(c, float(base[c].close), 100)  # 등락률 0%
    q = {"return_pct_min": 1.0, "sort_by": "return_pct"}  # 등락률 +1% 이상만
    first = live_codes_at(live_env, **q)
    assert first["data"]["total_count"] == 0 and first["meta"]["live"]["changes"] is None  # 첫 계산: 비교 대상 없음
    live_env.clock_box[0] += 6
    live_env.quote("T00001", float(base["T00001"].close) * 1.05, 100)
    live_env.quote("T00002", float(base["T00002"].close) * 1.05, 100)
    second = live_codes_at(live_env, **q)
    assert second["meta"]["live"]["changes"] == {"entered": ["T00001", "T00002"], "left": []}
    live_env.clock_box[0] += 6
    live_env.quote("T00001", float(base["T00001"].close), 100)
    live_env.quote("T00003", float(base["T00003"].close) * 1.05, 100)
    third = live_codes_at(live_env, **q)
    assert third["meta"]["live"]["changes"] == {"entered": ["T00003"], "left": ["T00001"]}
    # 다른 조건은 비교 대상이 없어 changes=None
    other = live_codes_at(live_env, return_pct_min=-50)
    assert other["meta"]["live"]["changes"] is None


def test_access_control_not_owner_or_disabled(db, monkeypatch, patched_factory):
    """접근 통제 의존성을 덮어쓰지 않으면 로컬 모드가 꺼진 환경에서 404(존재를 드러내지 않음)."""
    monkeypatch.delenv("LOCAL_INTRADAY_ENABLED", raising=False)
    with api_client(db) as c:
        assert c.get("/api/v1/local/screen").status_code == 404
        assert c.get("/api/v1/local/screen/pattern").status_code == 404
        assert c.get("/api/v1/local/screen", params={"snapshot_id": "0" * 32}).status_code == 404


def test_not_configured_returns_503(db, monkeypatch, patched_factory):
    with api_client(db) as c:
        app.dependency_overrides[require_owner] = lambda: types.SimpleNamespace(configured=False)
        r = c.get("/api/v1/local/screen")
        assert r.status_code == 503 and r.json()["error"]["code"] == "LOCAL_INTRADAY_NOT_CONFIGURED"


# ───────────────────────── 6) 성능(2,800종목 × 100거래일) ─────────────────────────
N_PERF = 2800


def seed_perf(engine) -> None:
    """합성 데이터: 종목 2,800개, 일봉 100행씩(평일), 발행 지표 행 2,800개. 실제 값이 아니라 크기·시간 측정용이다."""
    batch_id = "00000000-0000-0000-0000-0000000000aa"
    with engine.begin() as c:
        for t in ("public_serving.current_published_batch", "public_serving.derived_metrics_daily", "public_serving.daily_prices", "public_serving.stock_master", "public_serving.batch_run"):
            c.execute(text(f"DELETE FROM {t}"))
        c.execute(text("INSERT INTO public_serving.batch_run(batch_run_id,run_type,status,validation_passed) VALUES (:i,'derive','SUCCESS',true)"), {"i": batch_id})
        c.execute(text(
            "INSERT INTO public_serving.stock_master(stock_code,name,market,is_active)"
            " SELECT 'P'||lpad(g::text,5,'0'), '합성'||g, CASE WHEN g%3=0 THEN 'KOSDAQ'::public_serving.listed_market ELSE 'KOSPI'::public_serving.listed_market END, true FROM generate_series(1,:n) g"
        ), {"n": N_PERF})
        c.execute(text("SELECT setseed(0.42)"))
        c.execute(text(
            "INSERT INTO public_serving.daily_prices(stock_code,trade_date,open,high,low,close,volume,trading_value)"
            " SELECT 'P'||lpad(s::text,5,'0'), d, p, p, p, p, 100000 + (random()*50000)::int, 1"
            " FROM generate_series(1,:n) s,"
            "  LATERAL (SELECT d::date AS d, row_number() OVER (ORDER BY d) AS rn FROM generate_series(date '2026-05-14', date '2026-09-30', interval '1 day') d WHERE extract(isodow FROM d) < 6) days,"
            "  LATERAL (SELECT (10000 + 50*days.rn + (random()-0.5)*200)::numeric AS p) price"
        ), {"n": N_PERF})
        c.execute(text(
            "INSERT INTO public_serving.derived_metrics_daily(stock_code,trade_date,market,return_pct,ma5_gap_pct,ma20_gap_pct,volume_anomaly_score,per_raw,pbr_raw,market_cap_raw_krw,volume_raw,"
            "per_percentile,pbr_percentile,market_cap_percentile,sideways_range_pct,sideways_net_change_pct,ma_convergence_pct,volatility_contraction_ratio,ma60_gap_pct,ma20_vs_ma60_gap_pct,ma60_slope_pct,ma60_cross_up_days,volume_ratio_5_60,recent_surge_flag,pattern_metrics_status,batch_run_id)"
            " SELECT stock_code, date '2026-09-30', market, 0.5, 0.5, 0.5, 0.5, 10, 1, 1000000+row_number() over (), 100000, 50, 50, 50, 5, 1, 1, 0.8, -1, 1, 0.5, NULL, 1.1, false, 'OK', :b"
            " FROM public_serving.stock_master"
        ), {"b": batch_id})
        c.execute(text("INSERT INTO public_serving.current_published_batch(market,trade_date,batch_run_id) VALUES ('KRX', date '2026-09-30', :b)"), {"b": batch_id})


def test_performance_2800_stocks(monkeypatch):
    """측정 시험: 이력 적재·재계산·페이로드 크기·가상 테이블 쿼리 시간. 결과 숫자는 결과서에 옮긴다(여기서는 넉넉한 상한만 단언)."""
    try:
        cm = temp_database()
        db = cm.__enter__()
    except TempDbUnavailable as exc:
        pytest.skip(f"임시 DB를 만들 수 없어 건너뜀(통과로 세지 않음): {exc}")
    mig = create_engine(TempDb.render(db.migrator_url))
    api = create_engine(TempDb.render(db.api_url))
    try:
        seed_calendar(mig)
        seed_perf(mig)
        monkeypatch.setattr(local_screen, "get_session_factory", lambda: sessionmaker(bind=api, autoflush=False))
        set_now(kst(2026, 10, 1, 10, 0))
        out: dict[str, float] = {}

        t0 = time.perf_counter()
        ctx = local_screen.load_context()
        out["load_context_ms"] = (time.perf_counter() - t0) * 1000
        assert len(ctx.rows) == N_PERF and ctx.published_date == TARGET_DATE and ctx.needed_dates == []

        t0 = time.perf_counter()
        hist = local_screen.load_history(TARGET_DATE)
        out["load_history_ms"] = (time.perf_counter() - t0) * 1000
        assert len(hist) == N_PERF and all(len(b) == 100 for b in hist.values())

        now_ts = time.time()
        quotes = {c: MarketQuote(c, float(b[-1].close) * 1.01, 5000, 0, 0, 0, 0, 0, now_ts) for c, b in hist.items()}
        t0 = time.perf_counter()
        res = build_live_rows(ctx.rows, hist, quotes, today=ctx.today, basis_date=ctx.published_date, expected_date=ctx.expected_date, trading_today=True, now_ts=now_ts)
        out["recompute_ms"] = (time.perf_counter() - t0) * 1000
        assert len(res.rows) == N_PERF and set(res.basis.values()) == {"live"}

        t0 = time.perf_counter()
        payload = dump_rows(res.rows, trade_date=TARGET_DATE)
        out["dump_ms"], out["payload_kb"] = (time.perf_counter() - t0) * 1000, len(payload.encode()) / 1024

        session = Session(api)
        try:
            src = build_virtual_source(payload)
            repo = SqlScreenRepository(session, src)
            t0 = time.perf_counter()
            r1 = repo.search(screen_filters(return_pct_min=0.0, page_size=200))
            out["screen_query_ms"] = (time.perf_counter() - t0) * 1000
            t0 = time.perf_counter()
            codes = repo.matching_codes(screen_filters(return_pct_min=0.0))
            out["matching_codes_ms"] = (time.perf_counter() - t0) * 1000
            prepo = SqlPatternScreenRepository(session, src)
            t0 = time.perf_counter()
            r2 = prepo.search(pattern_filters(required=("c1", "c3"), page_size=200), TH)
            out["pattern_query_ms"] = (time.perf_counter() - t0) * 1000
            t0 = time.perf_counter()
            prepo.readiness(TARGET_DATE, "ALL", TH)
            out["readiness_ms"] = (time.perf_counter() - t0) * 1000
        finally:
            session.close()
        assert r1.total_count == len(codes) and r2.total_count >= 0
        print("\nPERF " + " ".join(f"{k}={v:.1f}" for k, v in out.items()))
        # 넉넉한 상한(느린 CI 포함): 실제 측정값은 결과서에 기록
        assert out["recompute_ms"] < 15000 and out["screen_query_ms"] < 5000 and out["pattern_query_ms"] < 5000 and out["payload_kb"] < 5000
    finally:
        mig.dispose()
        api.dispose()
        cm.__exit__(None, None, None)
