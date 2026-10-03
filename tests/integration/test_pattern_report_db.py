"""임계값 보정 리포트 임시 DB 테스트 (REQ-032/036, 04 §2 UNIT-15, 05-test-plan §6 보정 리포트).

`scripts/pattern_threshold_report.py`는 **읽기 전용**이며 조건별 충족 수·전체 충족 수·지표
분포·임계값 ±민감도 표를 출력한다. 이 테스트는 픽스처(T00001~T00010)를 배치로 산출한 뒤, 리포트의
숫자가 기준 구현 (오라클)로 직접 센 값과 같은지, 쓰기가 불가능한지(읽기 전용 트랜잭션·`api_service`
계정), 종목을 식별·서열화하는 출력이 없는지를 확인한다. 실데이터 보정(Q2 임계값 확정)은 백필 이후
별도로 수행한다.
"""

from __future__ import annotations

import statistics
import uuid
from collections.abc import Iterator
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

import scripts.pattern_threshold_report as rpt
from services.derivation_batch.compute import compute_volume_anomaly_score
from services.derivation_batch.run_derivation import run_once
from services.public_api.core.pattern_config import load_pattern_thresholds
from tests.integration.pattern_fixtures import (
    TARGET_DATE,
    build_stocks,
    seed_fixture,
)
from tests.integration.pg_temp_db import TempDb, TempDbUnavailable, temp_database
from tests.unit import test_pattern_compute as oracle_tools

CONDS = ("c1", "c2", "c3", "c4", "c5", "c9")
TH = load_pattern_thresholds({})


@pytest.fixture(scope="module")
def db() -> Iterator[TempDb]:
    try:
        with temp_database() as tdb:
            yield tdb
    except TempDbUnavailable as exc:
        pytest.skip(f"임시 DB를 만들 수 없어 건너뜀(통과로 세지 않음): {exc}")


@pytest.fixture()
def derived(db):
    """픽스처를 시드하고 배치를 돌려 발행까지 마친 상태. (슈퍼유저, api_service) 엔진 반환."""
    mig = create_engine(TempDb.render(db.migrator_url))
    batch = create_engine(TempDb.render(db.batch_url))
    api = create_engine(TempDb.render(db.api_url))
    _wipe(mig)
    seed_fixture(mig)
    with Session(batch) as s:
        assert run_once(s, trade_date_override=TARGET_DATE)[0] == "SUCCESS"
        s.commit()
    yield mig, api
    for e in (mig, batch, api):
        e.dispose()


def _wipe(mig):
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


def _oracle_counts():
    """오라클로 직접 센 조건별 true/false/null 수와 전체 충족 수(검증 기준)."""
    counts = {c: {"true": 0, "false": 0, "null": 0} for c in CONDS}
    all6 = 0
    ok_rows = 0
    for s in build_stocks().values():
        m = oracle_tools.oracle.compute_pattern_metrics(
            [float(x) for x in s.closes], [float(v) for v in s.volumes]
        )
        if m["pattern_metrics_status"] == "OK":
            ok_rows += 1
        anomaly = compute_volume_anomaly_score(s.volumes[0], s.volumes[1:21], window=20)
        conds = oracle_tools.oracle.evaluate_conditions(
            m, None if anomaly is None else float(anomaly)
        )
        for c in CONDS:
            counts[c]["true" if conds[c] is True else "false" if conds[c] is False else "null"] += 1
        all6 += all(conds[c] is True for c in CONDS)
    return counts, all6, ok_rows


def test_report_counts_equal_oracle_counts(derived):
    mig, _ = derived
    with Session(mig) as s:
        data = rpt.generate_report(s, TH, market="ALL", trade_date=None, sensitivity_pct=20)
    counts, all6, ok_rows = _oracle_counts()
    assert data.trade_date == TARGET_DATE
    assert data.total_rows == 10 and data.ok_rows == ok_rows == 8
    for c in CONDS:
        got = data.condition_counts[c]
        assert (got.true, got.false, got.null) == (
            counts[c]["true"],
            counts[c]["false"],
            counts[c]["null"],
        ), c
        assert got.true + got.false + got.null == 10  # 합은 항상 전체 행 수
    assert data.all_met == all6 == 1  # T00001만 6개 조건 모두 충족


def test_report_market_filter_restricts_rows(derived):
    mig, _ = derived
    with Session(mig) as s:
        kospi = rpt.generate_report(s, TH, market="KOSPI", trade_date=None, sensitivity_pct=20)
        kosdaq = rpt.generate_report(s, TH, market="KOSDAQ", trade_date=None, sensitivity_pct=20)
    assert kospi.total_rows + kosdaq.total_rows == 10 and kospi.total_rows == 5


def test_sensitivity_base_matches_main_counts_and_is_monotonic(derived):
    mig, _ = derived
    with Session(mig) as s:
        data = rpt.generate_report(s, TH, market="ALL", trade_date=None, sensitivity_pct=20)
    params = {row.param for row in data.sensitivity}
    assert params == {
        "PATTERN_RANGE_MAX_PCT",
        "PATTERN_NET_CHANGE_MAX_PCT",
        "PATTERN_CONVERGENCE_MAX_PCT",
        "PATTERN_VOLATILITY_CONTRACTION_MAX",
        "PATTERN_MA60_APPROACH_BAND_PCT",
        "PATTERN_MA60_EARLY_MAX_GAP_PCT",
        "PATTERN_CROSS_EARLY_MAX_DAYS",
        "PATTERN_VOLUME_RATIO_MIN",
        "PATTERN_VOLUME_RATIO_MAX",
        "PATTERN_VOLUME_ANOMALY_MAX",
    }
    for row in data.sensitivity:
        base = next(v for v in row.variants if v.label == "기준")
        assert base.all_met == data.all_met  # 기준값 변형은 본 집계와 같다
        for cond in row.conditions:
            assert base.cond_true[cond] == data.condition_counts[cond].true
        # 단조성: "상한" 임계값을 키우면 충족 수가 줄지 않고,
        # "하한"(VOLUME_RATIO_MIN)은 키우면 늘지 않는다.
        by_label = {v.label: v for v in row.variants}
        low, high = by_label.get("-20%"), by_label.get("+20%")
        for cond in row.conditions:
            if low is not None and high is not None:
                if row.param == "PATTERN_VOLUME_RATIO_MIN":
                    assert low.cond_true[cond] >= base.cond_true[cond] >= high.cond_true[cond]
                else:
                    assert low.cond_true[cond] <= base.cond_true[cond] <= high.cond_true[cond]


def test_sensitivity_variants_respect_config_ranges_and_pair_constraint(derived):
    mig, _ = derived
    # 범위 끝값(상한 100)에 가까운 설정이면 +20%는 범위를 넘으므로
    # 변형을 만들지 않는다(조용한 클램프 금지).
    th = load_pattern_thresholds({"PATTERN_RANGE_MAX_PCT": "95", "PATTERN_VOLUME_RATIO_MAX": "2.2"})
    with Session(mig) as s:
        data = rpt.generate_report(s, th, market="ALL", trade_date=None, sensitivity_pct=20)
    by_param = {r.param: r for r in data.sensitivity}
    assert {v.label for v in by_param["PATTERN_RANGE_MAX_PCT"].variants} == {"-20%", "기준"}
    # VOLUME_RATIO_MIN(1.0)의 +20%=1.2는 MAX(2.2)보다 작아 유효하고,
    # MAX(2.2)의 -20%=1.76도 MIN(1.0)보다 커서 유효하다.
    assert "+20%" in {v.label for v in by_param["PATTERN_VOLUME_RATIO_MIN"].variants}
    assert "-20%" in {v.label for v in by_param["PATTERN_VOLUME_RATIO_MAX"].variants}


def test_quantiles_are_computed_from_ok_rows_only(derived):
    mig, _ = derived
    with Session(mig) as s:
        data = rpt.generate_report(s, TH, market="ALL", trade_date=None, sensitivity_pct=20)
        stored = (
            s.execute(
                text(
                    "SELECT sideways_range_pct FROM public_serving.derived_metrics_daily"
                    " WHERE pattern_metrics_status='OK'"
                )
            )
            .scalars()
            .all()
        )
    q = data.quantiles["sideways_range_pct"]
    assert q.n == len(stored) == 8
    assert abs(q.p50 - float(statistics.median(stored))) < 1e-9
    assert q.p10 <= q.p50 <= q.p90

    # 기존 컬럼 `volume_anomaly_score`는 상태가 OK가 아닌 행(이력 부족·단절)에도 값이 있다 —
    # 분포는 반드시 산정 가능(OK) 행만으로 계산해야 한다.
    with Session(mig) as s:
        ok_values = (
            s.execute(
                text(
                    "SELECT volume_anomaly_score FROM public_serving.derived_metrics_daily"
                    " WHERE pattern_metrics_status='OK' AND volume_anomaly_score IS NOT NULL"
                )
            )
            .scalars()
            .all()
        )
        all_values = (
            s.execute(
                text(
                    "SELECT volume_anomaly_score FROM public_serving.derived_metrics_daily"
                    " WHERE volume_anomaly_score IS NOT NULL"
                )
            )
            .scalars()
            .all()
        )
    assert len(all_values) > len(
        ok_values
    )  # 비 OK 행에도 값이 있는 상황임을 보장(검증이 공허하지 않도록)
    qa = data.quantiles["volume_anomaly_score"]
    assert qa.n == len(ok_values)
    assert abs(qa.p50 - float(statistics.median(ok_values))) < 1e-9


def test_verdict_rules_zero_ok_and_too_many(derived):
    mig, _ = derived
    with Session(mig) as s:
        data = rpt.generate_report(s, TH, market="ALL", trade_date=None, sensitivity_pct=20)
    assert data.verdict == "OK"  # 1/10 = 10.0% — '10% 초과 아님'(경계 포함)
    assert rpt.judge(all_met=0, total_rows=100, ok_rows=90) == "ZERO"
    assert rpt.judge(all_met=11, total_rows=100, ok_rows=90) == "TOO_MANY"
    assert rpt.judge(all_met=10, total_rows=100, ok_rows=90) == "OK"
    assert rpt.judge(all_met=0, total_rows=100, ok_rows=0) == "NOT_READY"


def test_report_is_read_only_at_transaction_level(derived):
    """슈퍼유저 세션에서도 리포트가 연 트랜잭션은 읽기 전용이라 쓰기가 거부된다."""
    mig, _ = derived
    with Session(mig) as s:
        rpt.generate_report(s, TH, market="ALL", trade_date=None, sensitivity_pct=20)
        with pytest.raises(DBAPIError, match="read-only"):
            s.execute(text("DELETE FROM public_serving.stock_master"))
        s.rollback()
    with mig.connect() as c:  # 아무것도 지워지지 않았다
        assert c.execute(text("SELECT count(*) FROM public_serving.stock_master")).scalar() == 10


def test_cli_prints_report_without_identifying_or_ranking_stocks(derived, db, monkeypatch, capsys):
    mig, _ = derived
    monkeypatch.setenv("PUBLIC_API_DATABASE_URL", TempDb.render(db.api_url))
    for k in [k for k in __import__("os").environ if k.startswith("PATTERN_")]:
        monkeypatch.delenv(k)

    with mig.connect() as c:
        before = c.execute(
            text("SELECT count(*) FROM public_serving.derived_metrics_daily")
        ).scalar()
    assert rpt.main(["--market", "ALL"]) == 0
    out = capsys.readouterr().out
    assert "임계값 보정 리포트" in out and "2026-09-30" in out
    for token in ("c1", "c2", "c3", "c4", "c5", "c9", "민감도", "p10", "PATTERN_RANGE_MAX_PCT"):
        assert token in out, token
    # 종목 식별·서열화 정보가 없다(코드·이름·"추천/순위/TOP")
    for s in build_stocks().values():
        assert s.code not in out and s.name not in out
    for word in ("추천", "순위", "TOP", "유력"):
        assert word not in out, word
    with mig.connect() as c:
        after = c.execute(
            text("SELECT count(*) FROM public_serving.derived_metrics_daily")
        ).scalar()
    assert before == after


def test_cli_fails_explicitly_when_nothing_is_published(db, monkeypatch, capsys):
    mig = create_engine(TempDb.render(db.migrator_url))
    _wipe(mig)
    mig.dispose()
    monkeypatch.setenv("PUBLIC_API_DATABASE_URL", TempDb.render(db.api_url))
    assert rpt.main([]) == 1
    assert "발행" in capsys.readouterr().err


def test_cli_reports_not_ready_when_no_stock_is_evaluable(db, monkeypatch, capsys):
    mig = create_engine(TempDb.render(db.migrator_url))
    batch = create_engine(TempDb.render(db.batch_url))
    _wipe(mig)
    only_short = {k: v for k, v in build_stocks().items() if k == "T00008"}
    seed_fixture(mig, stocks=only_short)
    with Session(batch) as s:
        run_once(s, trade_date_override=TARGET_DATE)
        s.commit()
    monkeypatch.setenv("PUBLIC_API_DATABASE_URL", TempDb.render(db.api_url))
    assert rpt.main([]) == 0
    out = capsys.readouterr().out
    assert "산정 가능 종목이 없습니다" in out
    mig.dispose()
    batch.dispose()


def test_cli_rejects_invalid_threshold_environment(db, monkeypatch, capsys):
    monkeypatch.setenv("PUBLIC_API_DATABASE_URL", TempDb.render(db.api_url))
    monkeypatch.setenv("PATTERN_RANGE_MAX_PCT", "999")
    assert rpt.main([]) == 1
    assert "PATTERN_RANGE_MAX_PCT" in capsys.readouterr().err
    _ = Decimal


def test_report_universe_excludes_spac_and_preferred_like_the_api(derived):
    """리포트 숫자와 API 결과가 어긋나지 않도록 같은 평가 대상(스팩·우선주 제외)을 쓴다."""
    mig, _ = derived
    batch_id = uuid.uuid4()
    rows = [
        ("Q00010", "테스트스팩"),
        ("Q00015", "삼성테스트우"),
        ("Q00020", "성우"),  # 보통주(코드 끝자리 0) — 포함
    ]
    with mig.begin() as c:
        c.execute(
            text(
                "INSERT INTO public_serving.batch_run(batch_run_id,run_type,status)"
                " VALUES (:i,'derive','SUCCESS')"
            ),
            {"i": batch_id},
        )
        for code, name in rows:
            c.execute(
                text(
                    "INSERT INTO public_serving.stock_master(stock_code,name,market,is_active)"
                    " VALUES (:c,:n,'KOSPI',true)"
                ),
                {"c": code, "n": name},
            )
            c.execute(
                text(
                    "INSERT INTO public_serving.derived_metrics_daily"
                    "(stock_code,trade_date,market,pattern_metrics_status,recent_surge_flag,"
                    "batch_run_id) VALUES (:c,:d,'KOSPI','OK',false,:b)"
                ),
                {"c": code, "d": TARGET_DATE, "b": batch_id},
            )
    with Session(mig) as s:
        on = rpt.generate_report(s, TH, market="ALL", trade_date=None, sensitivity_pct=20)
    with Session(mig) as s:
        off_th = load_pattern_thresholds({"PATTERN_EXCLUDE_SPAC_PREFERRED": "false"})
        off = rpt.generate_report(s, off_th, market="ALL", trade_date=None, sensitivity_pct=20)
    assert on.total_rows == 11  # 픽스처 10 + 보통주 '성우'(스팩·우선주 2종목 제외)
    assert off.total_rows == 13  # 제외 스위치 off면 모두 포함
    assert on.ok_rows == 9 and off.ok_rows == 11
