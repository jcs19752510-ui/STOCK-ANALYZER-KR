"""scripts/backfill_ohlcv.py 임시 DB 통합 테스트 (REQ-031, 05-test-plan §4 TC-B01~B07).

실제 PostgreSQL(임시 DB, `pg_temp_db.py`)에서 `upsert_ohlcv`·`batch_run`·서킷브레이커·
`--dry-run` 종단 동작과 `batch_worker` 역할 권한을 검증한다. 외부 공공데이터 API는
`httpx.MockTransport`로 대체한다(실 호출 0회) — 실제 API 백필은 사용자 승인 후 별도 실행.

`pytest tests/unit`에는 포함되지 않는다: `pytest tests/integration/test_backfill_ohlcv_db.py`.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import date, datetime, time, timedelta

import httpx
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

import scripts.backfill_ohlcv as bf
from services.ingestion_batch import run_ingestion
from services.ingestion_batch.batch_run_repository import recent_ingest_statuses
from services.ingestion_batch.circuit_breaker import evaluate
from services.ingestion_batch.gov_data_client import GovDataPortalClient
from tests.integration.pg_temp_db import TempDb, TempDbUnavailable, temp_database

KEY = "SECRET/KEY+VALUE=="
ACTIVE_CODES = [f"{i:06d}" for i in range(1, 11)]  # 활성 10종목 → 90% 기준 = 9행
D1, D2, D3 = date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 3)  # 화·수·목 (모두 거래일로 시드)


@pytest.fixture(scope="module")
def db() -> Iterator[TempDb]:
    try:
        with temp_database() as tdb:
            yield tdb
    except TempDbUnavailable as exc:
        pytest.skip(f"임시 DB를 만들 수 없어 건너뜀(통과로 세지 않음): {exc}")


@pytest.fixture()
def clean(db: TempDb):
    """각 테스트 전: 시드 초기화(슈퍼유저 권한). 임시 DB 안에서만 동작한다."""
    eng = create_engine(TempDb.render(db.migrator_url))
    with eng.begin() as c:
        c.execute(text("TRUNCATE raw_internal.raw_ohlcv"))
        c.execute(text("DELETE FROM public_serving.batch_run"))
        c.execute(text("DELETE FROM public_serving.stock_master"))
        c.execute(text("DELETE FROM reference.market_calendar"))
        for code in ACTIVE_CODES:
            c.execute(
                text(
                    "INSERT INTO public_serving.stock_master(stock_code,name,market,is_active)"
                    " VALUES (:c,:n,'KOSPI',true)"
                ),
                {"c": code, "n": f"테스트{code}"},
            )
        d = date(2026, 8, 1)
        while d <= date(2026, 12, 31):
            trading = d.weekday() < 5
            c.execute(
                text(
                    "INSERT INTO reference.market_calendar"
                    "(trade_date,market,is_trading_day,session_close_at,holiday_name,source)"
                    " VALUES (:d,'KRX',:t,:close,:h,'test')"
                ),
                {
                    "d": d,
                    "t": trading,
                    "close": time(15, 30) if trading else None,
                    "h": None if trading else "휴장",
                },
            )
            d += timedelta(days=1)
    yield eng
    eng.dispose()


def _scalar(eng, sql: str, **params):
    with eng.connect() as c:
        return c.execute(text(sql), params).scalar()


def _raw_count(eng, trade_date: date | None = None) -> int:
    if trade_date is None:
        return _scalar(eng, "SELECT count(*) FROM raw_internal.raw_ohlcv")
    return _scalar(
        eng, "SELECT count(*) FROM raw_internal.raw_ohlcv WHERE trade_date=:d", d=trade_date
    )


def _backfill_run_count(eng) -> int:
    return _scalar(
        eng,
        "SELECT count(*) FROM public_serving.batch_run WHERE error_summary LIKE 'BACKFILL%'",
    )


def _seed_raw(eng, pairs: list[tuple[str, date]]) -> None:
    """raw_ohlcv 시드. `source_batch_id`는 batch_run 외래키라 선행 행이 필요하다."""
    batch_id = uuid.uuid4()
    with eng.begin() as c:
        c.execute(
            text(
                "INSERT INTO public_serving.batch_run(batch_run_id,run_type,status,error_summary)"
                " VALUES (:id,'ingest','SUCCESS','seed')"
            ),
            {"id": batch_id},
        )
        for code, d in pairs:
            c.execute(
                text(
                    "INSERT INTO raw_internal.raw_ohlcv"
                    " VALUES (:c,:d,'KRX',1,1,1,1,1,1,now(),:b)"
                ),
                {"c": code, "d": d, "b": batch_id},
            )


def _rows(eng, sql: str, **params):
    with eng.connect() as c:  # 연결을 반드시 닫는다(열린 트랜잭션이 다음 TRUNCATE를 막는다)
        return c.execute(text(sql), params).mappings().all()


class MockApi:
    """공공데이터포털 대역: 날짜별 행 수·장애를 제어하고 호출 기록을 남긴다."""

    def __init__(self, rows_per_date: dict[date, int]):
        self.rows_per_date = rows_per_date
        self.calls: list[tuple[str, int]] = []
        self.explode: Exception | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.explode is not None:
            raise self.explode
        bas_dt = request.url.params["basDt"]
        page = int(request.url.params["pageNo"])
        rows = int(request.url.params["numOfRows"])
        self.calls.append((bas_dt, page))
        d = datetime.strptime(bas_dt, "%Y%m%d").date()
        total = self.rows_per_date.get(d, 0)
        start = (page - 1) * rows
        n = max(0, min(rows, total - start))
        items = [
            {
                "basDt": bas_dt,
                "srtnCd": ACTIVE_CODES[(start + i) % len(ACTIVE_CODES)],
                "itmsNm": "x",
                "mrktCtg": "KOSPI",
                "mkp": "100",
                "hipr": "110",
                "lopr": "90",
                "clpr": str(100 + i),
                "trqu": "1000",
                "trPrc": "100000",
            }
            for i in range(n)
        ]
        body = {
            "response": {
                "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
                "body": {
                    "numOfRows": rows,
                    "pageNo": page,
                    "totalCount": total,
                    "items": {"item": items} if items else "",
                },
            }
        }
        return httpx.Response(200, json=body)


@pytest.fixture()
def env(db, monkeypatch):
    monkeypatch.setenv("BATCH_DATABASE_URL", TempDb.render(db.batch_url))
    monkeypatch.setenv("GOV_DATA_PORTAL_SERVICE_KEY", KEY)
    monkeypatch.setenv("GOV_DATA_PORTAL_BASE_URL", "https://example.invalid/getStockPriceInfo")
    monkeypatch.setattr(run_ingestion, "PAGE_SIZE", 4)  # 10행 → 3페이지(다중 페이지 경로 검증)


def _install_api(monkeypatch, api: MockApi) -> None:
    def factory(**kwargs):
        return GovDataPortalClient(
            **kwargs, sleep=lambda s: None, transport=httpx.MockTransport(api.handler)
        )

    monkeypatch.setattr(bf, "GovDataPortalClient", factory)


def _args(*extra: str) -> list[str]:
    return ["--from", "2026-09-01", "--to", "2026-09-03", "--sleep", "0", *extra]


# ── TC-B01: --dry-run ────────────────────────────────────────────────────────
def test_b01_dry_run_makes_no_external_call_and_writes_nothing(clean, env, monkeypatch, capsys):
    def must_not_construct(**kwargs):
        raise AssertionError("dry-run에서 외부 API 클라이언트가 생성되었습니다")

    monkeypatch.setattr(bf, "GovDataPortalClient", must_not_construct)
    monkeypatch.delenv("GOV_DATA_PORTAL_SERVICE_KEY")  # dry-run은 키 없이도 동작해야 한다

    assert bf.main(_args("--dry-run")) == 0
    out = capsys.readouterr().out
    assert "대상 거래일 3개" in out
    assert "예상 호출 수" in out and "9" in out  # 3일 × 3페이지
    assert "외부 호출 0회" in out
    assert _scalar(clean, "SELECT count(*) FROM raw_internal.raw_ohlcv") == 0
    assert _scalar(clean, "SELECT count(*) FROM public_serving.batch_run") == 0


# ── 정상 실행: 적재·batch_run 1행·역할 권한 ────────────────────────────────────
def test_run_persists_all_pages_and_records_exactly_one_backfill_batch_run(
    clean, env, monkeypatch, capsys
):
    api = MockApi({D1: 10, D2: 10, D3: 10})
    _install_api(monkeypatch, api)

    assert bf.main(_args()) == 0  # batch_worker 역할로 읽기/쓰기 모두 성공해야 한다

    assert _scalar(clean, "SELECT count(*) FROM raw_internal.raw_ohlcv") == 30
    runs = _rows(clean, "SELECT * FROM public_serving.batch_run")
    assert len(runs) == 1
    run = runs[0]
    assert run["run_type"] == "ingest"
    assert run["status"] == "SUCCESS" and run["validation_passed"] is True
    assert run["error_summary"].startswith("BACKFILL")
    assert run["trade_date_covered"] == D3
    ids = {
        r["source_batch_id"]
        for r in _rows(clean, "SELECT DISTINCT source_batch_id FROM raw_internal.raw_ohlcv")
    }
    assert ids == {run["batch_run_id"]}
    # 최신 → 과거 순서로 호출한다
    order = [c[0] for c in api.calls]
    assert order == sorted(order, reverse=True)
    assert len(api.calls) == 9
    out = capsys.readouterr().out
    assert KEY not in out


# ── TC-B02: 이미 충분한 날짜 건너뜀 ─────────────────────────────────────────────
def test_b02_skips_dates_already_filled(clean, env, monkeypatch, capsys):
    _seed_raw(clean, [(code, D2) for code in ACTIVE_CODES[:9]])  # 9/10 = 90% (경계 포함 → 충분)
    api = MockApi({D1: 10, D2: 10, D3: 10})
    _install_api(monkeypatch, api)

    assert bf.main(_args()) == 0
    assert "20260902" not in {c[0] for c in api.calls}
    assert "건너뜀" in capsys.readouterr().out
    assert _raw_count(clean, D2) == 9


# ── TC-B03: 거래일인데 0건 → 경고, 실패 아님 ──────────────────────────────────────
def test_b03_zero_rows_on_trading_day_warns_but_does_not_fail(clean, env, monkeypatch, capsys):
    api = MockApi({D1: 10, D2: 10})  # D3은 0건
    _install_api(monkeypatch, api)

    assert bf.main(_args()) == 0
    out = capsys.readouterr().out
    assert "경고" in out and "2026-09-03" in out
    assert _scalar(clean, "SELECT status FROM public_serving.batch_run") == "SUCCESS"


# ── TC-B04: 서킷브레이커 비오염 ─────────────────────────────────────────────────
def _seed_ingest_runs(eng, statuses_oldest_first: list[str], *, summary: str | None = "x"):
    base = datetime(2026, 8, 20, 7, 0).astimezone()
    with eng.begin() as c:
        for i, st in enumerate(statuses_oldest_first):
            c.execute(
                text(
                    "INSERT INTO public_serving.batch_run"
                    "(batch_run_id,run_type,started_at,finished_at,status,validation_passed,error_summary)"
                    " VALUES (:id,'ingest',:t,:t,:s,false,:e)"
                ),
                {"id": uuid.uuid4(), "t": base + timedelta(days=i), "s": st, "e": summary},
            )


def _breaker_view(db: TempDb):
    eng = create_engine(TempDb.render(db.batch_url))
    try:
        with Session(eng) as s:
            statuses = recent_ingest_statuses(s, 3)
        return statuses, evaluate(statuses, threshold=3)
    finally:
        eng.dispose()


def test_b04_successful_backfill_does_not_break_the_failure_streak(clean, env, db, monkeypatch):
    _seed_ingest_runs(clean, ["SUCCESS", "FAILED", "FAILED"])
    before = _breaker_view(db)
    assert before[0] == ["FAILED", "FAILED", "SUCCESS"] and before[1].consecutive_failures == 2

    _install_api(monkeypatch, MockApi({D1: 10, D2: 10, D3: 10}))
    assert bf.main(_args()) == 0

    after = _breaker_view(db)
    assert after == before  # 백필 SUCCESS 행이 연속 실패 집계를 끊지 않았다
    assert _backfill_run_count(clean) == 1


def test_b04_failed_backfill_does_not_trip_the_breaker(clean, env, db, monkeypatch):
    _seed_ingest_runs(clean, ["SUCCESS", "FAILED", "FAILED"])
    api = MockApi({D1: 10, D2: 10, D3: 10})
    api.explode = httpx.ConnectError("연결 실패")
    _install_api(monkeypatch, api)

    assert bf.main(_args()) == 1  # 백필 자체는 실패

    statuses, status = _breaker_view(db)
    assert statuses == ["FAILED", "FAILED", "SUCCESS"]
    assert status.is_open is False and status.consecutive_failures == 2
    backfill_status = _scalar(
        clean,
        "SELECT status FROM public_serving.batch_run WHERE error_summary LIKE 'BACKFILL%'",
    )
    assert backfill_status == "FAILED"


def test_b04_in_progress_or_crashed_backfill_row_is_excluded(clean, db):
    _seed_ingest_runs(clean, ["SUCCESS", "FAILED"])
    _seed_ingest_runs(clean, ["FAILED"], summary="BACKFILL(진행 중)")  # 비정상 종료로 남은 행
    statuses, _ = _breaker_view(db)
    assert statuses == ["FAILED", "SUCCESS"]  # 'BACKFILL' 행은 보이지 않는다


def test_b04_regular_ingest_rows_including_null_summary_are_still_counted(clean, db):
    _seed_ingest_runs(clean, ["FAILED", "FAILED", "FAILED"], summary=None)
    statuses, status = _breaker_view(db)
    assert statuses == ["FAILED"] * 3 and status.is_open is True  # 기존 동작 회귀 없음


# ── TC-B05: 서비스키 비노출 ─────────────────────────────────────────────────────
def test_b05_service_key_never_appears_in_output_or_db(clean, env, monkeypatch, capsys):
    api = MockApi({D1: 10, D2: 10, D3: 10})
    api.explode = httpx.ConnectError(f"boom https://x/y?serviceKey={KEY}&basDt=20260901")
    _install_api(monkeypatch, api)

    assert bf.main(_args()) == 1
    captured = capsys.readouterr()
    assert KEY not in captured.out and KEY not in captured.err
    assert "SECRET/KEY" not in captured.out + captured.err
    summary = _scalar(clean, "SELECT error_summary FROM public_serving.batch_run")
    assert KEY not in summary and "SECRET/KEY" not in summary
    assert "***" in summary or "serviceKey" not in summary


def test_b05_dry_run_does_not_print_key(clean, env, capsys):
    assert bf.main(_args("--dry-run")) == 0
    captured = capsys.readouterr()
    assert KEY not in captured.out + captured.err


# ── TC-B06: 중단 후 재개 ────────────────────────────────────────────────────────
def test_b06_resume_after_midway_db_failure_without_duplicate_calls(
    clean, env, monkeypatch
):
    real_upsert = bf.upsert_ohlcv
    state = {"n": 0}

    def flaky(session, records, **kw):
        state["n"] += 1
        if state["n"] == 2:
            # 일부 행을 쓴 뒤 실패해도 해당 날짜 전체가 롤백되어야 한다.
            real_upsert(session, records[:3], **kw)
            raise RuntimeError("DB 일시 장애")
        return real_upsert(session, records, **kw)

    monkeypatch.setattr(bf, "upsert_ohlcv", flaky)
    api1 = MockApi({D1: 10, D2: 10, D3: 10})
    _install_api(monkeypatch, api1)
    assert bf.main(_args()) == 1
    # 최신(D3)은 성공, D2는 부분 기록 후 롤백, D1은 미실행
    assert _raw_count(clean, D3) == 10
    assert _raw_count(clean, D2) == 0
    assert _raw_count(clean, D1) == 0

    monkeypatch.setattr(bf, "upsert_ohlcv", real_upsert)
    api2 = MockApi({D1: 10, D2: 10, D3: 10})
    _install_api(monkeypatch, api2)
    assert bf.main(_args()) == 0
    assert {c[0] for c in api2.calls} == {"20260902", "20260901"}  # D3은 다시 호출하지 않음
    assert _scalar(clean, "SELECT count(*) FROM raw_internal.raw_ohlcv") == 30  # 중복 없음
    assert _backfill_run_count(clean) == 2


# ── TC-B07: --max-calls ─────────────────────────────────────────────────────────
def test_b07_max_calls_stops_cleanly_and_reports_remaining(clean, env, monkeypatch, capsys):
    api = MockApi({D1: 10, D2: 10, D3: 10})
    _install_api(monkeypatch, api)

    assert bf.main(_args("--max-calls", "4")) == 0  # 상한 도달은 깨끗한 종료
    out = capsys.readouterr().out
    assert len(api.calls) == 4
    assert "남은" in out and "2026-09-02" in out and "2026-09-01" in out
    assert _raw_count(clean, D3) == 10
    assert _raw_count(clean, D2) == 0
    assert _scalar(clean, "SELECT status FROM public_serving.batch_run") == "PARTIAL"


# ── 완료 검증 쿼리 (설계서 §7, B08의 로직 부분) ─────────────────────────────────
def test_coverage_ratio_counts_stocks_with_enough_rows(clean, db):
    _seed_raw(
        clean,
        [("000001", D1 + timedelta(days=i)) for i in range(3)] + [("000002", D1)],
    )
    eng = create_engine(TempDb.render(db.batch_url))
    try:
        with Session(eng) as s:
            ready, total = bf.coverage_counts(s, min_rows=2)
    finally:
        eng.dispose()
    assert (ready, total) == (1, 2)
