"""증권사 일봉 캐시(public_serving.kis_daily_bar, 마이그레이션 0019, DEC-097) — 실제 PostgreSQL 임시 DB.

upsert·증분 건너뛰기·정리(trade_date <= P 삭제)·역할 권한(api_service SELECT만)을 가짜 증권사 클라이언트로 검증한다.
"""

# ruff: noqa: E501
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from scripts import collect_kis_daily_bars as ckb
from services.public_api.intraday.normalize import DAILY_PRICE_FIELDS
from tests.integration.pattern_api_env import prepare_database
from tests.integration.pattern_fixtures import TARGET_DATE
from tests.integration.pg_temp_db import TempDb, TempDbUnavailable, temp_database

P = TARGET_DATE  # 2026-09-30(발행 거래일)
D1, D2 = date(2026, 10, 1), date(2026, 10, 2)  # 달력은 평일=거래일 단순 모델


@pytest.fixture()
def db():
    try:
        with temp_database() as tdb:
            prepare_database(tdb)
            yield tdb
    except TempDbUnavailable as exc:
        pytest.skip(f"임시 DB를 만들 수 없어 건너뜀(통과로 세지 않음): {exc}")


def _row(day: date, close: int) -> dict:
    f = DAILY_PRICE_FIELDS
    return {
        f["date"]: day.strftime("%Y%m%d"),
        f["open"]: str(close),
        f["high"]: str(close + 5),
        f["low"]: str(close - 5),
        f["close"]: str(close),
        f["volume"]: "1234",
    }


class FakeClient:
    def __init__(self, fail_codes=()):
        self.calls: list[str] = []
        self.fail_codes = set(fail_codes)

    def daily_price(self, code):
        self.calls.append(code)
        if code in self.fail_codes:
            raise RuntimeError("down")
        return {
            "output": [
                _row(date(2026, 9, 29), 90),
                _row(P, 100),
                _row(D1, 101),
                _row(D2, 102),
                _row(date(2026, 10, 5), 103),
            ]
        }


def _count(batch, where=""):
    with Session(batch) as s:
        return s.execute(
            text(f"SELECT count(*) FROM public_serving.kis_daily_bar {where}")
        ).scalar_one()


def test_collect_upserts_skips_cached_and_purges(db, monkeypatch):
    monkeypatch.setattr(ckb, "RETRY_DELAY_SEC", 0)
    batch = create_engine(TempDb.render(db.batch_url))
    try:
        with Session(batch) as s:
            codes = ckb.codes_published_on(s, P)
        assert len(codes) >= 3
        # 1) 첫 실행: P..D2 범위(3일)만 적재, 9/29·10/5는 범위 밖
        client = FakeClient()
        with Session(batch) as s:
            stats, samples = ckb.collect(s, client, codes, P, D2)
            assert ckb.purge_published(s, P) == len(codes)  # P 행은 정리 대상
            s.commit()
        assert (
            stats["fetched"] == len(codes)
            and stats["rows"] == 3 * len(codes)
            and stats["errors"] == 0
            and samples == []
        )
        assert _count(batch) == 2 * len(codes)  # 정리 뒤엔 D1·D2만
        assert _count(batch, "WHERE trade_date <= '2026-09-30'") == 0
        # 2) 같은 범위 재실행(P 행이 정리돼 캐시에는 D1·D2만 있어 P가 비어 있음 → 증분 판정은 P 포함이므로 다시 조회)
        # 정리 없이 연속 실행하는 경우: 모두 캐시에 있어 건너뜀
        with Session(batch) as s:
            ckb.collect(s, FakeClient(), codes, P, D2)  # P 행 다시 채움(정리 전 상태)
            s.commit()
        client2 = FakeClient()
        with Session(batch) as s:
            stats2, _ = ckb.collect(s, client2, codes, P, D2)
        assert stats2["skipped"] == len(codes) and client2.calls == [] and stats2["rows"] == 0
        # 3) E가 하루 늘면(10/5) 그 날짜가 캐시에 없으므로 다시 조회
        D3 = date(2026, 10, 5)
        client3 = FakeClient()
        with Session(batch) as s:
            stats3, _ = ckb.collect(s, client3, codes, P, D3)
            s.commit()
        assert stats3["fetched"] == len(codes) and _count(
            batch, "WHERE trade_date = '2026-10-05'"
        ) == len(codes)
        # upsert 멱등: 행 수 불변(중복 없음)
        assert _count(batch) == 4 * len(codes)
    finally:
        batch.dispose()


def test_failures_are_counted_and_do_not_stop_others(db, monkeypatch):
    monkeypatch.setattr(ckb, "RETRY_DELAY_SEC", 0)
    batch = create_engine(TempDb.render(db.batch_url))
    try:
        with Session(batch) as s:
            codes = ckb.codes_published_on(s, P)
        client = FakeClient(fail_codes=[codes[0]])
        with Session(batch) as s:
            stats, samples = ckb.collect(s, client, codes, P, D2)
        assert stats["errors"] == 1 and stats["fetched"] == len(codes) - 1 and len(samples) == 1
        assert client.calls.count(codes[0]) == ckb.MAX_RETRIES + 1
    finally:
        batch.dispose()


def test_main_exit_codes_and_purge_only_path(db, monkeypatch, capsys):
    monkeypatch.setattr(ckb, "RETRY_DELAY_SEC", 0)
    monkeypatch.setattr(ckb, "load_kis_keys_from_dotenv", lambda p: [])
    monkeypatch.setenv("BATCH_DATABASE_URL", TempDb.render(db.batch_url))
    monkeypatch.setattr(ckb, "get_settings", lambda: SimpleNamespace(configured=True))
    fake = FakeClient()
    monkeypatch.setattr(ckb, "KisClient", lambda settings: fake)
    mig = create_engine(TempDb.render(db.migrator_url))
    try:
        # P < E: 적재 후 종료코드 0, 정리로 P 행은 없고 D1·D2만 남는다
        monkeypatch.setattr(ckb, "get_last_trading_day", lambda *a, **k: D2)
        assert ckb.main([]) == 0
        with Session(mig) as s:
            n = s.execute(
                text("SELECT count(*) FROM public_serving.daily_prices WHERE trade_date=:d"),
                {"d": P},
            ).scalar_one()
        assert _count(mig, "WHERE trade_date <= '2026-09-30'") == 0 and _count(mig) == 2 * n
        # --dry-run: 호출·쓰기 없음
        calls_before = len(fake.calls)
        assert ckb.main(["--dry-run"]) == 0 and len(fake.calls) == calls_before
        # --limit
        with mig.begin() as c:
            c.execute(text("DELETE FROM public_serving.kis_daily_bar"))
        assert ckb.main(["--limit", "2"]) == 0 and _count(mig) == 4
        # 일부 종목 실패 → 종료코드 2
        with mig.begin() as c:
            c.execute(text("DELETE FROM public_serving.kis_daily_bar"))
        with Session(mig) as s:
            first = ckb.codes_published_on(s, P)[0]
        fake.fail_codes.add(first)
        assert ckb.main([]) == 2
        # P >= E: KIS 호출 없이 정리만(남은 모든 행이 P 이하면 삭제), 종료코드 0
        with mig.begin() as c:
            c.execute(
                text(
                    "INSERT INTO public_serving.kis_daily_bar(stock_code,trade_date,open,high,low,close,volume) VALUES ('000001','2026-09-29',1,1,1,1,1),('000001','2026-10-01',1,1,1,1,1)"
                )
            )
        monkeypatch.setattr(ckb, "get_last_trading_day", lambda *a, **k: P)
        calls_before = len(fake.calls)
        assert ckb.main([]) == 0 and len(fake.calls) == calls_before
        assert (
            _count(mig, "WHERE trade_date <= '2026-09-30'") == 0
            and _count(mig, "WHERE stock_code='000001'") == 1
        )
        # 키 미설정 → 1
        monkeypatch.setattr(ckb, "get_last_trading_day", lambda *a, **k: D2)
        monkeypatch.setattr(ckb, "get_settings", lambda: SimpleNamespace(configured=False))
        assert ckb.main([]) == 1
        out = capsys.readouterr()
        assert "x@" not in out.out + out.err  # 접속 문자열 비출력
    finally:
        mig.dispose()


def test_role_privileges(db):
    batch = create_engine(TempDb.render(db.batch_url))
    api = create_engine(TempDb.render(db.api_url))
    try:
        with batch.begin() as c:
            c.execute(
                text(
                    "INSERT INTO public_serving.kis_daily_bar(stock_code,trade_date,open,high,low,close,volume) VALUES ('000001','2026-10-01',1,2,1,2,10)"
                )
            )
            c.execute(text("UPDATE public_serving.kis_daily_bar SET close=3"))
        with api.connect() as c:
            assert (
                c.execute(text("SELECT close FROM public_serving.kis_daily_bar")).scalar_one() == 3
            )
        for stmt in (
            "INSERT INTO public_serving.kis_daily_bar(stock_code,trade_date,open,high,low,close,volume) VALUES ('000002','2026-10-01',1,2,1,2,10)",
            "UPDATE public_serving.kis_daily_bar SET close=9",
            "DELETE FROM public_serving.kis_daily_bar",
        ):
            with pytest.raises(DBAPIError), api.begin() as c:
                c.execute(text(stmt))
        with batch.begin() as c:
            c.execute(text("DELETE FROM public_serving.kis_daily_bar"))
    finally:
        batch.dispose()
        api.dispose()
