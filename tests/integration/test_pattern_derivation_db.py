"""패턴 지표 스키마·배치 통합 임시 DB 테스트 (REQ-030/035, 05-test-plan §5 TC-D01~D08).

실제 PostgreSQL 임시 DB(`pg_temp_db`)에 실제 마이그레이션(0011)과 실제 역할 권한(GRANT)을 적용해
검증한다. 개발 DB(`stock_screener`)에는 아무것도 쓰지 않는다. 실행:
`pytest tests/integration/test_pattern_derivation_db.py`.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from services.derivation_batch.compute import (
    compute_ma_gap_pct,
    compute_return_pct,
    compute_volume_anomaly_score,
)
from services.derivation_batch.run_derivation import run_once
from tests.integration.pattern_fixtures import (
    EXPECTED,
    TARGET_DATE,
    build_stocks,
    seed_fixture,
)
from tests.integration.pg_temp_db import (
    TempDb,
    TempDbUnavailable,
    run_alembic,
    temp_database,
)
from tests.unit import test_pattern_compute as oracle_tools

NEW_COLUMNS = {
    "sideways_range_pct": "numeric",
    "sideways_net_change_pct": "numeric",
    "ma_convergence_pct": "numeric",
    "volatility_contraction_ratio": "numeric",
    "ma60_gap_pct": "numeric",
    "ma20_vs_ma60_gap_pct": "numeric",
    "ma60_slope_pct": "numeric",
    "ma60_cross_up_days": "smallint",
    "volume_ratio_5_60": "numeric",
    "recent_surge_flag": "boolean",
    "pattern_metrics_status": "character varying",
}


@pytest.fixture(scope="module")
def db() -> Iterator[TempDb]:
    try:
        with temp_database() as tdb:
            yield tdb
    except TempDbUnavailable as exc:
        pytest.skip(f"임시 DB를 만들 수 없어 건너뜀(통과로 세지 않음): {exc}")


@pytest.fixture()
def clean(db: TempDb):
    """각 테스트 전 시드·산출물 초기화(임시 DB 안에서만). (슈퍼유저 엔진, batch_worker 엔진)."""
    mig = create_engine(TempDb.render(db.migrator_url))
    batch = create_engine(TempDb.render(db.batch_url))
    with mig.begin() as c:
        for t in (
            "public_serving.current_published_batch",
            "public_serving.market_summary_daily",
            "public_serving.derived_metrics_daily",
            "raw_internal.raw_fundamentals",
            "raw_internal.raw_ohlcv",
            "public_serving.stock_master",
            "public_serving.batch_run",
        ):
            c.execute(text(f"DELETE FROM {t}"))
    yield mig, batch
    mig.dispose()
    batch.dispose()


def _derive(batch_engine, trade_date: date = TARGET_DATE):
    with Session(batch_engine) as s:
        result = run_once(s, trade_date_override=trade_date)
        s.commit()
    return result


def _metrics_rows(engine) -> dict[str, dict]:
    with engine.connect() as c:
        rows = (
            c.execute(text("SELECT * FROM public_serving.derived_metrics_daily")).mappings().all()
        )
    return {r["stock_code"]: dict(r) for r in rows}


def _count(engine, table: str) -> int:
    with engine.connect() as c:
        return c.execute(text(f"SELECT count(*) FROM {table}")).scalar()


# ── 픽스처가 설계 의도대로인지(검증이 공허하지 않도록) ───────────────────────────
def test_fixture_series_match_design_intent():
    """05 §1-1: 각 픽스처 종목의 기대 상태·조건을 기준 구현(오라클)으로 확인."""
    for code, s in build_stocks().items():
        assert len(s.closes) == (50 if code == "T00008" else 130), code
        m = oracle_tools.oracle.compute_pattern_metrics(
            [float(x) for x in s.closes], [float(v) for v in s.volumes]
        )
        assert m["pattern_metrics_status"] == EXPECTED[code]["status"], code
        anomaly = compute_volume_anomaly_score(s.volumes[0], s.volumes[1:21], window=20)
        conds = oracle_tools.oracle.evaluate_conditions(
            m, None if anomaly is None else float(anomaly)
        )
        for cid, want in EXPECTED[code]["conds"].items():
            assert conds[cid] is want, (code, cid, conds[cid], want)


# ── D01·D03: 마이그레이션 가역성·구 행 보존 ──────────────────────────────────────
def test_d01_d03_migration_is_reversible_and_preserves_legacy_rows():
    """독립 임시 DB에서 head → downgrade 0010 → (구 행 삽입) → upgrade head."""
    with temp_database() as tdb:
        mig = create_engine(TempDb.render(tdb.migrator_url))

        def cols():
            with mig.connect() as c:
                rows = c.execute(
                    text(
                        "SELECT column_name, data_type FROM information_schema.columns"
                        " WHERE table_schema='public_serving'"
                        " AND table_name='derived_metrics_daily'"
                    )
                ).all()
            return dict(rows)

        assert NEW_COLUMNS.items() <= cols().items()  # head: 11개 컬럼 존재(타입 포함)

        down = run_alembic(tdb, "downgrade", "0010")
        assert down.returncode == 0, down.stderr[-400:]
        after_down = cols()
        assert not (set(NEW_COLUMNS) & set(after_down))  # 11개 모두 제거
        assert "return_pct" in after_down and "volume_raw" in after_down  # 기존 컬럼 보존

        batch_id = uuid.uuid4()
        with mig.begin() as c:  # 0010 상태의 "구 배치" 행
            c.execute(
                text(
                    "INSERT INTO public_serving.batch_run(batch_run_id,run_type,status)"
                    " VALUES (:i,'derive','SUCCESS')"
                ),
                {"i": batch_id},
            )
            c.execute(
                text(
                    "INSERT INTO public_serving.derived_metrics_daily"
                    "(stock_code,trade_date,market,return_pct,batch_run_id)"
                    " VALUES ('LEGACY',:d,'KOSPI',1.5,:b)"
                ),
                {"d": TARGET_DATE, "b": batch_id},
            )

        up = run_alembic(tdb, "upgrade", "head")
        assert up.returncode == 0, up.stderr[-400:]
        assert NEW_COLUMNS.items() <= cols().items()  # 재적용 후 다시 11개

        with mig.connect() as c:
            row = (
                c.execute(
                    text(
                        "SELECT * FROM public_serving.derived_metrics_daily"
                        " WHERE stock_code='LEGACY'"
                    )
                )
                .mappings()
                .one()
            )
        assert row["return_pct"] == Decimal("1.5")  # 기존 데이터 보존(D03)
        assert all(row[col] is None for col in NEW_COLUMNS)  # 신규 컬럼은 전부 NULL(D03)
        mig.dispose()


# ── D02: CHECK 제약 ───────────────────────────────────────────────────────────────
def test_d02_check_constraint_rejects_unknown_status_but_accepts_valid_and_null(clean):
    mig, _ = clean
    batch_id = uuid.uuid4()
    with mig.begin() as c:
        c.execute(
            text(
                "INSERT INTO public_serving.batch_run(batch_run_id,run_type,status)"
                " VALUES (:i,'derive','SUCCESS')"
            ),
            {"i": batch_id},
        )

    def insert(code: str, status):
        with mig.begin() as c:
            c.execute(
                text(
                    "INSERT INTO public_serving.derived_metrics_daily"
                    "(stock_code,trade_date,market,pattern_metrics_status,batch_run_id)"
                    " VALUES (:c,:d,'KOSPI',:s,:b)"
                ),
                {"c": code, "d": TARGET_DATE, "s": status, "b": batch_id},
            )

    with pytest.raises(IntegrityError):
        insert("BAD001", "BAD")
    for i, ok in enumerate(("OK", "INSUFFICIENT_HISTORY", "SUSPECT_PRICE_JUMP", None)):
        insert(f"OK{i:04d}", ok)  # 유효 값·NULL(구 배치 행)은 허용


# ── D04·D06: 130행 픽스처로 run_once 멱등·혼합 상태 발행 ──────────────────────────
def test_d04_d06_run_once_success_publishes_and_is_idempotent(clean):
    mig, batch = clean
    seed_fixture(mig)

    status, covered, summary = _derive(batch)
    assert (status, covered, summary) == ("SUCCESS", TARGET_DATE, None)
    first = _metrics_rows(mig)
    assert set(first) == set(EXPECTED)  # 10종목 전부(이력 부족·단절 포함) 행 생성
    with mig.connect() as c:
        published = (
            c.execute(text("SELECT trade_date FROM public_serving.current_published_batch"))
            .scalars()
            .all()
        )
    assert published == [TARGET_DATE]  # 혼합 상태에서도 발행 포인터 정상 갱신(D06)

    for code, want in EXPECTED.items():
        assert first[code]["pattern_metrics_status"] == want["status"], code
    assert first["T00001"]["sideways_range_pct"] is not None
    assert first["T00001"]["recent_surge_flag"] is False
    assert first["T00008"]["sideways_range_pct"] is None  # 이력 부족 → 지표 NULL, 상태만
    assert first["T00009"]["recent_surge_flag"] is None

    status2, _, _ = _derive(batch)  # 재실행(멱등 upsert)
    second = _metrics_rows(mig)
    assert status2 == "SUCCESS" and set(second) == set(first)  # 행 수 불변
    for code in first:
        for col in NEW_COLUMNS:
            assert second[code][col] == first[code][col], (code, col)  # 값 동일


def test_d04_rerun_overwrites_stale_pattern_columns_via_on_conflict_update(clean):
    """재실행이 기존 행의 패턴 컬럼 11개를 실제로 덮어쓴다(ON CONFLICT DO UPDATE 대상 포함)."""
    mig, batch = clean
    seed_fixture(mig)
    _derive(batch)
    good = _metrics_rows(mig)["T00001"]

    stale = {"numeric": "999", "smallint": "999", "boolean": "NOT recent_surge_flag"}
    set_clause = ", ".join(
        f"{col} = {stale.get(typ, repr('SUSPECT_PRICE_JUMP'))}" for col, typ in NEW_COLUMNS.items()
    )
    with mig.begin() as c:  # 낡은/오염된 값으로 되돌려 놓고
        c.execute(
            text(
                f"UPDATE public_serving.derived_metrics_daily SET {set_clause}"
                " WHERE stock_code='T00001'"
            )
        )
    assert _metrics_rows(mig)["T00001"]["pattern_metrics_status"] == "SUSPECT_PRICE_JUMP"

    _derive(batch)  # 같은 거래일 재실행
    fixed = _metrics_rows(mig)["T00001"]
    for col in NEW_COLUMNS:
        assert fixed[col] == good[col], col  # 11개 모두 올바른 값으로 복구


def test_stored_pattern_values_match_oracle_for_fixture_stocks(clean):
    """DB에 저장된 패턴 지표가 기준 구현(오라클)과 같다(배치→DB 경로 종단 검증)."""
    mig, batch = clean
    seed_fixture(mig)
    _derive(batch)
    rows = _metrics_rows(mig)
    for code, s in build_stocks().items():
        exp = oracle_tools.oracle.compute_pattern_metrics(
            [float(x) for x in s.closes], [float(v) for v in s.volumes]
        )
        for f in oracle_tools.NUMERIC_FIELDS:
            got, want = rows[code][f], exp[f]
            if want is None:
                assert got is None, (code, f)
            else:
                assert abs(float(got) - want) <= 1e-3, (code, f, got, want)
        assert rows[code]["ma60_cross_up_days"] == exp["ma60_cross_up_days"], code
        assert rows[code]["recent_surge_flag"] == exp["recent_surge_flag"], code


# ── D05: 실제 역할 권한 ────────────────────────────────────────────────────────────
def test_d05_api_service_can_select_new_columns_but_cannot_write(clean):
    mig, batch = clean
    seed_fixture(mig)
    _derive(batch)  # batch_worker가 신규 컬럼을 포함해 쓸 수 있음(성공해야 이후 검증 가능)
    cols = ", ".join(NEW_COLUMNS)

    # 슈퍼유저 세션에서 api_service 역할로 전환한다(비밀번호 불필요, 권한 판정은 동일).
    with mig.connect() as c:
        c.execute(text("SET ROLE api_service"))
        n = c.execute(
            text(
                f"SELECT count(*) FROM (SELECT {cols}"
                " FROM public_serving.derived_metrics_daily) t"
            )
        ).scalar()
        assert n == len(EXPECTED)  # 신규 컬럼 SELECT 가능
        c.rollback()

    attempts = {
        "INSERT": (
            "INSERT INTO public_serving.derived_metrics_daily(stock_code,trade_date,market,"
            "batch_run_id) SELECT 'X00001',trade_date,market,batch_run_id"
            " FROM public_serving.derived_metrics_daily LIMIT 1"
        ),
        "UPDATE_STATUS": "UPDATE public_serving.derived_metrics_daily"
        " SET pattern_metrics_status='OK'",
        "UPDATE_NEW_COLUMN": "UPDATE public_serving.derived_metrics_daily SET ma60_gap_pct=1",
        "DELETE": "DELETE FROM public_serving.derived_metrics_daily",
    }
    for name, sql in attempts.items():
        with mig.connect() as c:
            c.execute(text("SET ROLE api_service"))
            with pytest.raises(DBAPIError, match="permission denied"):
                c.execute(text(sql))
            c.rollback()
        assert name

    with mig.connect() as c:  # api_service는 raw_internal 접근 불가(DEC-006 3중 분리 유지)
        c.execute(text("SET ROLE api_service"))
        with pytest.raises(DBAPIError, match="permission denied"):
            c.execute(text("SELECT 1 FROM raw_internal.raw_ohlcv LIMIT 1"))
        c.rollback()


# ── D07: 패턴 지표가 전부 NULL이어도 발행 결과 불변 ────────────────────────────────
def test_d07_all_history_short_still_succeeds_and_publishes(clean):
    mig, batch = clean
    only_short = {k: v for k, v in build_stocks().items() if k == "T00008"}  # 50거래일 → 전부 부족
    seed_fixture(mig, stocks=only_short)
    status, _, summary = _derive(batch)
    assert (status, summary) == ("SUCCESS", None)  # 패턴 결측이 발행을 막지 않는다
    assert _metrics_rows(mig)["T00008"]["pattern_metrics_status"] == "INSUFFICIENT_HISTORY"
    assert _count(mig, "public_serving.current_published_batch") == 1


# ── D08: 기존 지표 무변화(윈도우 41→100) — DB 경로 ─────────────────────────────────
def test_d08_existing_metrics_in_db_equal_direct_computation_from_raw_series(clean):
    """윈도우를 100행으로 늘린 배치의 기존 지표가, 41행 이하만 쓰는 직접 계산과 동일."""
    mig, batch = clean
    seed_fixture(mig)
    _derive(batch)
    rows = _metrics_rows(mig)
    for code, s in build_stocks().items():
        closes = [Decimal(x) for x in s.closes][:41]  # 변경 전 윈도우(41행)만 사용
        r = rows[code]
        assert r["return_pct"] == compute_return_pct(closes[0], closes[1]), code
        assert r["ma5_gap_pct"] == compute_ma_gap_pct(closes, window=5), code
        assert r["ma20_gap_pct"] == compute_ma_gap_pct(closes, window=20), code
        assert r["volume_anomaly_score"] == compute_volume_anomaly_score(
            s.volumes[0], s.volumes[1:21], window=20
        ), code
        assert r["volume_raw"] == s.volumes[0], code
        assert r["market_cap_raw_krw"] == s.market_cap_krw, code
