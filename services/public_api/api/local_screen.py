"""장중 재계산 스크리닝 API (DEC-089·090). **내 PC 전용**, 기본 꺼짐, 소유자(관리자)만.

- `GET /api/v1/local/screen`         — 기존 `GET /api/v1/screen`과 같은 파라미터·검증·응답 + `basis`·`meta.live`
- `GET /api/v1/local/screen/pattern` — 기존 `GET /api/v1/screen/pattern`과 같다 + `basis`·`meta.live`
판정은 기존 엔드포인트 함수를 **그대로** 호출한다(저장소만 가상 테이블로 바꿔 끼움) — 필터·정렬·패턴 조건식을 복제하지 않는다.
계약서: `docs/stock-detail/10-intraday-rescreen-contract.md`. 앱키·시세 원본은 응답에 나오지 않는다.
"""

# ruff: noqa: E501
from __future__ import annotations

import dataclasses
import inspect
import logging
import os
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from services.public_api.api import local_market, pattern, screen
from services.public_api.api.local_realtime import require_owner
from services.public_api.core.pattern_config import PatternThresholds
from services.public_api.db.calendar_repository import SqlCalendarRepository
from services.public_api.db.pattern_repository import SqlPatternScreenRepository
from services.public_api.db.screen_repository import SqlScreenRepository
from services.public_api.db.session import get_db, get_session_factory
from services.public_api.errors import ApiError
from services.public_api.intraday import config as cfg
from services.public_api.live_screen.fill import BaseFiller
from services.public_api.live_screen.history import HISTORY_ROWS_PER_STOCK
from services.public_api.live_screen.service import (
    LiveScreenError,
    LiveScreenService,
    PublishedContext,
    QuoteState,
    ServiceDeps,
)
from services.public_api.live_screen.snapshot import Snapshot
from services.public_api.live_screen.types import DailyBar
from services.public_api.live_screen.virtual import build_virtual_source, dump_rows
from services.public_api.schemas.live_screen import live_meta_from
from shared.calendar_service import get_last_trading_day
from shared.db_models.public_serving import CurrentPublishedBatch, DailyPrice, DerivedMetricsDaily

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/local", tags=["local-screen"])

KST = ZoneInfo("Asia/Seoul")
MARKET = "KRX"
PRIORITY_MAX_CODES = 200
MAX_CHANGES = 100


def _env_float(name: str, default: float, minimum: float) -> float:
    raw = os.environ.get(name, "").strip()
    try:
        return max(minimum, float(raw)) if raw else default
    except ValueError:
        return default


# ── DB 읽기(동기 — 스레드에서 실행) ─────────────────────────────────────────────────────
_now: Callable[[], datetime] = lambda: datetime.now(KST)  # noqa: E731 — 시험이 바꿀 수 있다


def set_now_provider(fn: Callable[[], datetime] | None) -> None:
    global _now
    _now = fn or (lambda: datetime.now(KST))


def load_context() -> PublishedContext:
    session = get_session_factory()()
    try:
        calendar = SqlCalendarRepository(session)
        now = _now()
        published = session.get(CurrentPublishedBatch, MARKET)
        if published is None:
            raise LiveScreenError(503, "DATA_PIPELINE_STALE", "표시할 데이터가 아직 없습니다. 서비스 데이터 준비 중입니다.")
        p_date: date = published.trade_date
        expected = get_last_trading_day(MARKET, now, calendar)
        if expected is None:
            raise LiveScreenError(424, "CALENDAR_NOT_CONFIRMED", "휴장일 캘린더가 아직 갱신되지 않아 직전 거래일을 계산할 수 없습니다.")
        today = now.date()
        today_row = calendar.get(today, MARKET)
        needed: list[date] = []
        day = p_date + timedelta(days=1)
        while day <= expected:
            row = calendar.get(day, MARKET)
            if row is not None and row.is_trading_day:
                needed.append(day)
            day += timedelta(days=1)
        rows = [
            {c.key: getattr(r, c.key) for c in DerivedMetricsDaily.__table__.columns}
            for r in session.execute(select(DerivedMetricsDaily).where(DerivedMetricsDaily.trade_date == p_date)).scalars()
        ]
        return PublishedContext(p_date, expected, today, bool(today_row and today_row.is_trading_day), needed, rows)
    finally:
        session.close()


HISTORY_CHUNK_STOCKS = 250  # 종목을 나눠 읽는다: 문장 하나가 DB 쿼리 제한 시간(기본 3초)을 넘지 않게(네트워크 DB 대비)


def load_history(published_date: date) -> dict[str, list[DailyBar]]:
    """종목당 발행일 이하 최근 100행 일봉(날짜 오름차순). 발행일에 일봉이 있는 종목만, 250종목씩 나눠 읽는다."""
    session = get_session_factory()()
    try:
        codes = [
            str(c)
            for c in session.execute(
                select(DailyPrice.stock_code).where(DailyPrice.trade_date == published_date).order_by(DailyPrice.stock_code)
            ).scalars()
        ]
        out: dict[str, list[DailyBar]] = {}
        for start in range(0, len(codes), HISTORY_CHUNK_STOCKS):
            chunk = codes[start : start + HISTORY_CHUNK_STOCKS]
            ranked = (
                select(
                    DailyPrice.stock_code, DailyPrice.trade_date, DailyPrice.open, DailyPrice.high, DailyPrice.low,
                    DailyPrice.close, DailyPrice.volume,
                    func.row_number().over(partition_by=DailyPrice.stock_code, order_by=DailyPrice.trade_date.desc()).label("rn"),
                )
                .where(DailyPrice.stock_code.in_(chunk), DailyPrice.trade_date <= published_date)
                .subquery()
            )
            stmt = (
                select(ranked.c.stock_code, ranked.c.trade_date, ranked.c.open, ranked.c.high, ranked.c.low, ranked.c.close, ranked.c.volume)
                .where(ranked.c.rn <= HISTORY_ROWS_PER_STOCK)
                .order_by(ranked.c.stock_code, ranked.c.trade_date)
            )
            for code, d, o, h, lo, c, v in session.execute(stmt):
                out.setdefault(code, []).append(DailyBar(d, o, h, lo, c, int(v)))
        return out
    finally:
        session.close()


# ── 서비스(프로세스당 하나) ─────────────────────────────────────────────────────────────
_service: tuple[local_market.MarketRuntime, LiveScreenService, BaseFiller] | None = None


def _make_service(runtime: local_market.MarketRuntime) -> tuple[LiveScreenService, BaseFiller]:
    from services.public_api.intraday.normalize import normalize_daily_price

    client = runtime.service.client

    def fetch(code: str) -> list[DailyBar]:
        body = client.daily_price(code)
        rows = body.get("output") if isinstance(body, dict) else None
        return normalize_daily_price([r for r in rows if isinstance(r, dict)]) if isinstance(rows, list) else []

    filler = BaseFiller(fetch)

    async def quote_state() -> QuoteState:
        await runtime.ensure_started()
        snapshot = runtime.poller.snapshot()
        meta = runtime.meta(snapshot)
        return QuoteState(snapshot, bool(meta["stale"]), runtime.poller.running, len(runtime.poller.codes))

    deps = ServiceDeps(
        load_context=load_context,
        load_history=load_history,
        quote_state=quote_state,
        filler=filler,
        min_interval=_env_float("LIVE_SCREEN_MIN_INTERVAL", 5.0, 0.0),
        refresh_seconds=_env_float("LIVE_SCREEN_REFRESH_SECONDS", 10.0, 1.0),
    )
    return LiveScreenService(deps), filler


def get_service(settings: cfg.IntradaySettings) -> tuple[LiveScreenService, local_market.MarketRuntime]:
    global _service
    runtime = local_market.get_runtime(settings)
    if _service is None or _service[0] is not runtime:
        old = _service
        svc, filler = _make_service(runtime)
        _service = (runtime, svc, filler)
        if old is not None:
            import asyncio

            asyncio.get_running_loop().create_task(old[2].close())
    return _service[1], runtime


async def shutdown_live_screen() -> None:
    global _service
    if _service is not None:
        svc, _service = _service, None
        await svc[2].close()


def reset_live_screen() -> None:
    """테스트 전용: 서비스를 버린다."""
    global _service
    _service = None


# ── 의존성 ────────────────────────────────────────────────────────────────────────────
class _Live:
    """요청 하나가 쓰는 스냅샷과 런타임."""

    def __init__(self, snapshot: Snapshot, service: LiveScreenService, runtime: local_market.MarketRuntime) -> None:
        self.snapshot = snapshot
        self.service = service
        self.runtime = runtime


async def live_context(
    snapshot_id: str | None = Query(None, min_length=1, max_length=64, pattern=r"^[0-9a-f]{32}$", description="고정할 스냅샷(없으면 최신)"),
    settings: cfg.IntradaySettings = Depends(require_owner),
) -> _Live:
    if not settings.configured:
        raise ApiError(503, "LOCAL_INTRADAY_NOT_CONFIGURED", "증권사 앱키가 설정되지 않았습니다. KIS_APP_KEY·KIS_APP_SECRET을 확인하세요.")
    svc, runtime = get_service(settings)
    try:
        snap = await svc.acquire(snapshot_id)
    except LiveScreenError as exc:
        raise ApiError(exc.status_code, exc.code, exc.message, exc.details) from exc
    return _Live(snap, svc, runtime)


class _LiveScreenRepo(SqlScreenRepository):
    def __init__(self, session: Session, source: Any, trade_key: date) -> None:
        super().__init__(session, source)
        self.trade_key = trade_key  # 가상 행의 trade_date 키(발행 거래일)
        self.filters: Any = None

    def get_current_published_trade_date(self, market: str) -> date | None:
        return self.trade_key

    def search(self, filters):  # type: ignore[no-untyped-def]
        self.filters = filters
        return super().search(filters)


class _LivePatternRepo(SqlPatternScreenRepository):
    def __init__(self, session: Session, source: Any, trade_key: date) -> None:
        super().__init__(session, source)
        self.trade_key = trade_key
        self.filters: Any = None
        self.thresholds: PatternThresholds | None = None

    def get_current_published_trade_date(self, market: str) -> date | None:
        return self.trade_key

    def search(self, filters, thresholds):  # type: ignore[no-untyped-def]
        self.filters, self.thresholds = filters, thresholds
        return super().search(filters, thresholds)


def _source_for(live: _Live) -> Any:
    snap = live.snapshot
    return build_virtual_source(snap.payload(lambda: dump_rows(snap.result.rows, trade_date=snap.trade_key)))


def get_live_screen_repository(live: _Live = Depends(live_context), db: Session = Depends(get_db)) -> _LiveScreenRepo:
    return _LiveScreenRepo(db, _source_for(live), live.snapshot.trade_key)


def get_live_pattern_repository(live: _Live = Depends(live_context), db: Session = Depends(get_db)) -> _LivePatternRepo:
    return _LivePatternRepo(db, _source_for(live), live.snapshot.trade_key)


# ── 응답 보강 ─────────────────────────────────────────────────────────────────────────
def _query_key(filters: Any) -> str:
    """편입·이탈 비교의 조회 조건 키 — 정렬·페이지·기준일은 뺀다(같은 조건이면 같은 결과 집합)."""
    d = dataclasses.asdict(filters)
    for k in ("sort_by", "sort_dir", "page", "page_size", "trade_date"):
        d.pop(k, None)
    return repr(sorted(d.items()))


def _changes(live: _Live, key: str, codes: set[str]) -> dict[str, list[str]] | None:
    snap = live.snapshot
    snap.matched[key] = frozenset(codes)
    prev = live.service.store.previous(snap.snapshot_id)
    if prev is None or key not in prev.matched:
        return None
    before = prev.matched[key]
    return {"entered": sorted(codes - before)[:MAX_CHANGES], "left": sorted(before - codes)[:MAX_CHANGES]}


def _finish(envelope: Any, live: _Live, repo: Any, matching: Callable[[], list[str]], response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    snap = live.snapshot
    data = envelope.data.model_dump(mode="json")
    codes = [it["stock_code"] for it in data["items"]]
    for it in data["items"]:
        it["basis"] = snap.result.basis.get(it["stock_code"], "daily")
    poller = live.runtime.poller
    prio = poller.set_priority(codes[:PRIORITY_MAX_CODES])  # 화면에 보이는 종목은 시세를 더 자주 갱신한다(화면이 닫히면 자동 해제)
    changes = _changes(live, _query_key(repo.filters), set(matching()))
    meta = envelope.meta.model_dump(mode="json")
    meta["live"] = live_meta_from(
        snap.info, snapshot_id=snap.snapshot_id, priority_codes=prio,
        priority_cycle_seconds=None if poller.priority_cycle_seconds is None else round(poller.priority_cycle_seconds, 3),
        changes=changes,
    )
    return {"meta": meta, "data": data, "error": None}


def _live_endpoint(orig: Callable[..., Any], repo_dep: Callable[..., Any], matching: Callable[[Any], list[str]]) -> Callable[..., Any]:
    """기존 엔드포인트 함수를 그대로 감싼다: 저장소 의존성만 가상 테이블 저장소로 바꾼다."""
    params = []
    for p in inspect.signature(orig).parameters.values():
        params.append(p.replace(default=Depends(repo_dep)) if p.name == "repository" else p)
    params.append(inspect.Parameter("live", inspect.Parameter.KEYWORD_ONLY, default=Depends(live_context), annotation=Any))
    params.append(inspect.Parameter("response", inspect.Parameter.KEYWORD_ONLY, annotation=Response))

    def endpoint(**kw: Any) -> dict[str, Any]:
        live: _Live = kw.pop("live")
        response: Response = kw.pop("response")
        envelope = orig(**kw)
        repo = kw["repository"]
        return _finish(envelope, live, repo, lambda: matching(repo), response)

    endpoint.__signature__ = inspect.Signature(params)  # type: ignore[attr-defined]
    endpoint.__name__ = f"live_{orig.__name__}"
    return endpoint


router.add_api_route(
    "/screen",
    _live_endpoint(screen.screen_stocks, get_live_screen_repository, lambda repo: repo.matching_codes(repo.filters)),
    methods=["GET"],
)
router.add_api_route(
    "/screen/pattern",
    _live_endpoint(
        pattern.screen_pattern, get_live_pattern_repository, lambda repo: repo.matching_codes(repo.filters, repo.thresholds)
    ),
    methods=["GET"],
)
