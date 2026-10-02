"""`GET /api/v1/screen/pattern` 임시 DB 통합 테스트 (REQ-032/033/035/036, 05-test-plan §7·§8·§9).

실제 PostgreSQL 임시 DB에 픽스처(T00001~T00010)를 배치로 산출·발행한 뒤, `api_service`(읽기 전용)
세션으로 실제 FastAPI 앱을 호출한다 — 실제 SQL·권한·미들웨어. 기대값은 기준 구현(오라클)로 직접
계산한다. 개발 DB에는 아무것도 쓰지 않는다.
"""

from __future__ import annotations

import hashlib
import json
import statistics
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from services.derivation_batch.compute import compute_volume_anomaly_score
from services.public_api.core.pattern_config import load_pattern_thresholds
from tests.integration.pattern_api_env import api_client, prepare_database, seed_calendar, wipe
from tests.integration.pattern_fixtures import (
    EXPECTED,
    TARGET_DATE,
    build_stocks,
)
from tests.integration.pg_temp_db import TempDb, TempDbUnavailable, temp_database
from tests.unit import test_pattern_compute as oracle_tools

REPO_ROOT = Path(__file__).resolve().parents[2]
CONDS = ("c1", "c2", "c3", "c4", "c5", "c9")
URL = "/api/v1/screen/pattern"
STAGES_FOR_C4 = {"BELOW_NEAR", "CROSS_EARLY"}


@pytest.fixture(scope="module")
def db() -> Iterator[TempDb]:
    try:
        with temp_database() as tdb:
            prepare_database(tdb)
            yield tdb
    except TempDbUnavailable as exc:
        pytest.skip(f"임시 DB를 만들 수 없어 건너뜀(통과로 세지 않음): {exc}")


@pytest.fixture(scope="module")
def client(db):
    with api_client(db) as c:
        yield c


def oracle_conds() -> dict[str, dict]:
    """픽스처 종목별 조건 판정(True/False/None)을 기준 구현으로 계산."""
    out = {}
    for code, s in build_stocks().items():
        m = oracle_tools.oracle.compute_pattern_metrics(
            [float(x) for x in s.closes], [float(v) for v in s.volumes]
        )
        anomaly = compute_volume_anomaly_score(s.volumes[0], s.volumes[1:21], window=20)
        out[code] = oracle_tools.oracle.evaluate_conditions(
            m, None if anomaly is None else float(anomaly)
        )
    return out


ORACLE = oracle_conds()


def expected_codes(required: list[str], *, market: str = "ALL", extra=lambda s: True) -> set[str]:
    stocks = build_stocks()
    return {
        code
        for code, conds in ORACLE.items()
        if all(conds[c] is True for c in required)
        and (market == "ALL" or stocks[code].market == market)
        and extra(stocks[code])
    }


def codes(resp) -> list[str]:
    assert resp.status_code == 200, resp.text
    return [i["stock_code"] for i in resp.json()["data"]["items"]]


# ── A01·A03: 기본 호출 = 6개 조건 모두 충족 종목 ────────────────────────────────────
def test_a01_a03_default_returns_only_stocks_meeting_all_six_conditions(client):
    resp = client.get(URL)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    data = body["data"]
    assert set(data) == {"items", "total_count", "page", "definition", "readiness"}
    assert (
        [i["stock_code"] for i in data["items"]]
        == ["T00001"]
        == sorted(expected_codes(list(CONDS)))
    )
    assert data["total_count"] == 1 and data["page"] == 1
    item = data["items"][0]
    assert all(item["conditions"][c] == {"met": True, "reason": None} for c in CONDS)
    assert item["ma60_stage"] == "BELOW_NEAR"
    assert item["name"] == "픽스처01" and item["market"] == "KOSPI"
    assert (
        body["meta"]["disclaimer"] and body["meta"]["data_freshness"]["trade_date"] == "2026-09-30"
    )


# ── A02: 시장 필터 ─────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("market", ["ALL", "KOSPI", "KOSDAQ"])
def test_a02_market_filter(client, market):
    got = codes(client.get(URL, params={"required": "c9", "market": market, "page_size": 200}))
    assert set(got) == expected_codes(["c9"], market=market)
    if market != "ALL":
        stocks = build_stocks()
        assert all(stocks[c].market == market for c in got)


# ── A04·A16: 필수 조건 부분집합 — TRUE만 통과(FALSE·NULL 제외) ─────────────────────────
@pytest.mark.parametrize(
    "required", [["c1", "c2"], ["c1", "c3", "c9"], ["c2"], ["c4"], ["c5"], ["c9"]]
)
def test_a04_a16_required_subset_matches_oracle_and_excludes_false_and_null(client, required):
    got = set(codes(client.get(URL, params={"required": ",".join(required), "page_size": 200})))
    assert got == expected_codes(required)
    # 산정 불가(T00008/T00009)·c2 NULL(T00010)·FALSE 종목은 해당 조건이 필수면 결과에 없다
    for code in ("T00008", "T00009"):
        assert code not in got
    if "c2" in required:
        assert "T00010" not in got


def test_a15_non_required_null_cells_expose_reason_metric_unavailable(client):
    resp = client.get(URL, params={"required": "c1,c3,c9", "page_size": 200})
    items = {i["stock_code"]: i for i in resp.json()["data"]["items"]}
    flat = items["T00010"]["conditions"]  # 완전 평탄: c2·c5는 값이 NULL, c4는 FALSE
    assert flat["c2"] == {"met": None, "reason": "METRIC_UNAVAILABLE"}
    assert flat["c5"] == {"met": None, "reason": "METRIC_UNAVAILABLE"}
    assert flat["c4"] == {"met": False, "reason": None}
    assert flat["c1"]["met"] is True
    assert items["T00010"]["metrics"]["volatility_contraction_ratio"] is None
    assert items["T00010"]["ma60_stage"] == "ABOVE_SETTLED"
    # 산정 불가 종목(이력 부족·단절)은 필수 조건에 걸려 결과 행으로는 나올 수 없다(설계서 §5-4)
    assert "T00008" not in items and "T00009" not in items


# ── A17·A13: total_count·페이지네이션 결정론 ────────────────────────────────────────
def test_a17_a13_total_count_and_deterministic_pagination(client):
    full = client.get(URL, params={"required": "c9", "page_size": 200}).json()["data"]
    want = sorted(expected_codes(["c9"]))
    assert full["total_count"] == len(want) == len(full["items"])
    collected = []
    for page in range(1, 20):
        data = client.get(URL, params={"required": "c9", "page_size": 2, "page": page}).json()[
            "data"
        ]
        assert data["total_count"] == len(want)
        if not data["items"]:
            break
        collected += [i["stock_code"] for i in data["items"]]
    assert len(collected) == len(set(collected)) == len(want)  # 중복·누락 없음
    assert collected == [i["stock_code"] for i in full["items"]]  # 한 번에 받은 순서와 동일
    # 정렬 키 동률이어도 stock_code 오름차순(2차 키)
    same = client.get(
        URL, params={"required": "c9", "sort_by": "sideways_range_pct", "page_size": 200}
    )
    assert [i["stock_code"] for i in same.json()["data"]["items"]]  # 호출 성공


# ── A32: 정렬 4종 × 2방향 ─────────────────────────────────────────────────────────
SORT_VALUE = {
    "ma60_gap_pct": lambda i: i["metrics"]["ma60_gap_pct"],
    "sideways_range_pct": lambda i: i["metrics"]["sideways_range_pct"],
    "ma_convergence_pct": lambda i: i["metrics"]["ma_convergence_pct"],
}


@pytest.mark.parametrize("sort_by", sorted(SORT_VALUE))
@pytest.mark.parametrize("sort_dir", ["asc", "desc"])
def test_a32_sorting_on_metric_columns(client, sort_by, sort_dir):
    items = client.get(
        URL, params={"required": "c9", "sort_by": sort_by, "sort_dir": sort_dir, "page_size": 200}
    ).json()["data"]["items"]
    values = [SORT_VALUE[sort_by](i) for i in items]
    nonnull = [v for v in values if v is not None]
    assert len(items) >= 5
    assert nonnull == sorted(nonnull, reverse=(sort_dir == "desc"))
    # 동률은 stock_code 오름차순
    for a, b in zip(items, items[1:], strict=False):
        if SORT_VALUE[sort_by](a) == SORT_VALUE[sort_by](b):
            assert a["stock_code"] < b["stock_code"]


@pytest.mark.parametrize("sort_dir", ["asc", "desc"])
def test_a32_sort_by_market_cap_uses_hidden_raw_value_without_exposing_it(client, sort_dir):
    items = client.get(
        URL,
        params={"required": "c9", "sort_by": "market_cap", "sort_dir": sort_dir, "page_size": 200},
    ).json()["data"]["items"]
    stocks = build_stocks()
    caps = [stocks[i["stock_code"]].market_cap_krw for i in items]
    assert caps == sorted(caps, reverse=(sort_dir == "desc"))
    assert not any("market_cap" in k for i in items for k in i)  # 응답에는 시가총액이 없다


# ── A14: 산정 불가(NULL) 값은 정렬에서 항상 마지막 ───────────────────────────────────
def test_a14_null_sort_values_are_last_in_both_directions(db, client):
    mig = create_engine(TempDb.render(db.migrator_url))
    batch_id = uuid.uuid4()
    try:
        with mig.begin() as c:
            c.execute(
                text(
                    "INSERT INTO public_serving.batch_run(batch_run_id,run_type,status)"
                    " VALUES (:i,'derive','SUCCESS')"
                ),
                {"i": batch_id},
            )
            c.execute(
                text(
                    "INSERT INTO public_serving.stock_master(stock_code,name,market,is_active)"
                    " VALUES ('N00001','널값종목','KOSPI',true)"
                )
            )
            c.execute(  # 상태 OK이고 c9는 true인데 ma60_gap_pct만 NULL
                text(
                    "INSERT INTO public_serving.derived_metrics_daily"
                    "(stock_code,trade_date,market,pattern_metrics_status,recent_surge_flag,batch_run_id)"
                    " VALUES ('N00001',:d,'KOSPI','OK',false,:b)"
                ),
                {"d": TARGET_DATE, "b": batch_id},
            )
        for d in ("asc", "desc"):
            items = client.get(
                URL,
                params={
                    "required": "c9",
                    "sort_by": "ma60_gap_pct",
                    "sort_dir": d,
                    "page_size": 200,
                },
            ).json()["data"]["items"]
            assert items[-1]["stock_code"] == "N00001", d
            assert items[-1]["metrics"]["ma60_gap_pct"] is None
    finally:
        with mig.begin() as c:
            c.execute(
                text("DELETE FROM public_serving.derived_metrics_daily WHERE stock_code='N00001'")
            )
            c.execute(text("DELETE FROM public_serving.stock_master WHERE stock_code='N00001'"))
            c.execute(
                text("DELETE FROM public_serving.batch_run WHERE batch_run_id=:b"), {"b": batch_id}
            )
        mig.dispose()


# ── A18·A33: readiness(시장 필터 후, 구 배치 행 포함) ─────────────────────────────────
def test_a18_readiness_counts_by_market(client):
    all_ready = client.get(URL).json()["data"]["readiness"]
    assert all_ready == {"evaluated_count": 8, "total_count": 10, "ready_ratio": 0.8}
    stocks = build_stocks()
    for market in ("KOSPI", "KOSDAQ"):
        r = client.get(URL, params={"market": market}).json()["data"]["readiness"]
        in_market = [c for c, s in stocks.items() if s.market == market]
        ok = [c for c in in_market if EXPECTED[c]["status"] == "OK"]
        assert r["total_count"] == len(in_market) and r["evaluated_count"] == len(ok)
        assert r["ready_ratio"] == round(len(ok) / len(in_market), 4)


def test_a33_legacy_rows_with_null_status_count_as_not_evaluated_and_never_match(db, client):
    mig = create_engine(TempDb.render(db.migrator_url))
    batch_id = uuid.uuid4()
    try:
        with mig.begin() as c:
            c.execute(
                text(
                    "INSERT INTO public_serving.batch_run(batch_run_id,run_type,status)"
                    " VALUES (:i,'derive','SUCCESS')"
                ),
                {"i": batch_id},
            )
            c.execute(
                text(
                    "INSERT INTO public_serving.stock_master(stock_code,name,market,is_active)"
                    " VALUES ('L00001','구배치','KOSPI',true)"
                )
            )
            c.execute(  # 패턴 컬럼이 전부 NULL인 구 배치 행(0011 이전)
                text(
                    "INSERT INTO public_serving.derived_metrics_daily"
                    "(stock_code,trade_date,market,return_pct,batch_run_id)"
                    " VALUES ('L00001',:d,'KOSPI',1.0,:b)"
                ),
                {"d": TARGET_DATE, "b": batch_id},
            )
        data = client.get(URL, params={"required": "c9", "page_size": 200}).json()["data"]
        assert data["readiness"]["total_count"] == 11 and data["readiness"]["evaluated_count"] == 8
        assert "L00001" not in [i["stock_code"] for i in data["items"]]
    finally:
        with mig.begin() as c:
            c.execute(
                text("DELETE FROM public_serving.derived_metrics_daily WHERE stock_code='L00001'")
            )
            c.execute(text("DELETE FROM public_serving.stock_master WHERE stock_code='L00001'"))
            c.execute(
                text("DELETE FROM public_serving.batch_run WHERE batch_run_id=:b"), {"b": batch_id}
            )
        mig.dispose()


# ── A20: 일부만 준비·결과 0건 → 200 + 빈 목록 ─────────────────────────────────────────
def test_a20_zero_matches_is_200_empty_list_not_an_error(client):
    resp = client.get(URL, params={"market_cap_min": 10**15})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["items"] == [] and data["total_count"] == 0
    assert data["readiness"]["evaluated_count"] == 8  # 시장·시총 필터와 무관(시장 필터만 적용)


# ── A27: market_cap_min·volume_min은 필터로만 동작 ───────────────────────────────────
def test_a27_market_cap_and_volume_filters_work_and_values_are_not_exposed(client):
    stocks = build_stocks()
    got = set(
        codes(
            client.get(
                URL, params={"required": "c9", "market_cap_min": 500_000_000_000, "page_size": 200}
            )
        )
    )
    assert got == expected_codes(["c9"], extra=lambda s: s.market_cap_krw >= 500_000_000_000)
    got_v = set(
        codes(client.get(URL, params={"required": "c9", "volume_min": 400_000, "page_size": 200}))
    )
    assert got_v == expected_codes(["c9"], extra=lambda s: s.volumes[0] >= 400_000)
    assert "T00006" in got_v  # 오늘 거래량 8배 종목만 40만 주 이상
    text_ = client.get(URL, params={"required": "c9", "market_cap_min": 500_000_000_000}).text
    for s in stocks.values():
        assert str(s.market_cap_krw) not in text_
        assert str(s.volumes[0]) not in text_


# ── A31: ma60_stage ↔ c4 일치(API 응답에서) ──────────────────────────────────────────
def test_a31_stage_and_c4_are_consistent_in_responses(client):
    items = client.get(URL, params={"required": "c9", "page_size": 200}).json()["data"]["items"]
    assert items
    for i in items:
        met = i["conditions"]["c4"]["met"]
        stage = i["ma60_stage"]
        if met is True:
            assert stage in STAGES_FOR_C4
        elif met is False:
            assert stage not in STAGES_FOR_C4 and stage is not None
        else:
            assert stage is None
    by_code = {i["stock_code"]: i for i in items}
    assert by_code["T00005"]["ma60_stage"] == "EXTENDED"  # 8일 전 돌파·60일선 +12%
    assert by_code["T00005"]["conditions"]["c4"]["met"] is False
    only_c4 = codes(client.get(URL, params={"required": "c4", "page_size": 200}))
    assert set(only_c4) == expected_codes(["c4"])
    for i in client.get(URL, params={"required": "c4", "page_size": 200}).json()["data"]["items"]:
        assert i["ma60_stage"] in STAGES_FOR_C4


# ── A23: 응답에 가격·원값 필드 없음(재귀) ────────────────────────────────────────────
def test_a23_real_response_has_only_whitelisted_keys(client):
    forbidden = {"open", "high", "low", "close", "volume", "volume_raw", "trading_value",
                 "market_cap", "market_cap_raw_krw", "per_raw", "pbr_raw"}  # fmt: skip
    data = client.get(URL, params={"required": "c9", "page_size": 200}).json()["data"]
    seen = set()

    def walk(n):
        if isinstance(n, dict):
            seen.update(n)
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)

    walk(data)
    assert not (seen & forbidden) and not any(k.endswith("_raw") for k in seen)
    for item in data["items"]:
        assert set(item) == {"stock_code", "name", "market", "conditions", "metrics", "ma60_stage"}
        assert len(item["metrics"]) == 11


# ── A24: definition == 서버 설정 ─────────────────────────────────────────────────────
def test_a24_definition_equals_server_configuration(client):
    th = load_pattern_thresholds({})
    defn = client.get(URL).json()["data"]["definition"]
    assert defn["thresholds"] == th.definition_thresholds()
    assert defn["version"] == "v1"


# ── A34: 직렬화 ──────────────────────────────────────────────────────────────────────
def test_a34_real_response_is_strict_json_with_numbers(client):
    def reject(c):
        raise AssertionError(c)

    parsed = json.loads(
        client.get(URL, params={"required": "c9", "page_size": 200}).text, parse_constant=reject
    )
    for item in parsed["data"]["items"]:
        for k, v in item["metrics"].items():
            assert v is None or isinstance(v, (int, float, bool)), (k, v)


# ── S01·S04: 인젝션·임계값 우회가 데이터·결과에 영향 없음 ─────────────────────────────────
def test_s01_injection_attempts_are_rejected_and_data_is_intact(db, client):
    mig = create_engine(TempDb.render(db.migrator_url))
    try:
        with mig.connect() as c:
            before = c.execute(
                text("SELECT count(*) FROM public_serving.derived_metrics_daily")
            ).scalar()
        for params in (
            {"required": "'; DROP TABLE public_serving.derived_metrics_daily; --"},
            {"required": "c1) OR (1=1"},
            {"sort_by": "market_cap; DELETE FROM public_serving.stock_master"},
            {"market": "KOSPI' OR '1'='1"},
        ):
            r = client.get(URL, params=params)
            assert r.status_code == 400 and r.json()["error"]["code"] == "INVALID_PARAMETER", params
        with mig.connect() as c:
            after = c.execute(
                text("SELECT count(*) FROM public_serving.derived_metrics_daily")
            ).scalar()
            masters = c.execute(text("SELECT count(*) FROM public_serving.stock_master")).scalar()
        assert before == after == 10 and masters == 10
    finally:
        mig.dispose()


def test_s04_threshold_bypass_parameters_do_not_change_results(client):
    base = client.get(URL, params={"required": "c1", "page_size": 200}).json()["data"]
    bypass = client.get(
        URL,
        params={
            "required": "c1",
            "page_size": 200,
            "range_max_pct": 100,
            "net_change_max_pct": 50,
            "threshold": 0,
        },  # fmt: skip
    ).json()["data"]
    assert bypass == base


# ── A35: 기존 /screen 계약 불변(골든 비교) ──────────────────────────────────────────
# screen.py 해시는 DEC-046(R2)에서 400 메시지의 입력값 반사를 제거하며 1회 갱신했다
# (에러 코드·상태·성공 응답 계약은 불변).
FROZEN_SHA256 = {
    "services/public_api/api/screen.py": (
        "a905eae0be40791bdaeb20a8a58f8e1513ef2180c6e0565441e516c8e83beac7"
    ),
    "services/public_api/db/screen_repository.py": (
        "ca04b7bc69e672d107c19c720ed5c7c402e0b8187f73e8195f9d93d06f1e68a4"
    ),
    "services/public_api/schemas/screen.py": (
        "cb0005cc23c328ff04c63be00973af1f494342a5d48fbe37103b1d0fd7e6ee28"
    ),
}


def test_a35_existing_screen_source_files_are_unchanged():
    """기존 계약 파일은 수정 금지(additive only).

    줄바꿈 정규화 후 해시가 UNIT-16 시작 시점과 같아야 한다.
    """
    for rel, expected in FROZEN_SHA256.items():
        content = (REPO_ROOT / rel).read_text(encoding="utf-8").replace("\r\n", "\n")
        assert hashlib.sha256(content.encode("utf-8")).hexdigest() == expected, rel


def test_a35_existing_screen_responses_equal_pre_change_golden(client):
    golden = json.loads(
        (REPO_ROOT / "tests/integration/golden_screen_before_pattern.json").read_text(
            encoding="utf-8"
        )
    )
    assert len(golden) == 5
    for name, g in golden.items():
        resp = client.get(g["url"])
        assert resp.status_code == 200, name
        assert resp.json()["data"] == g["data"], name


# ── 에러 경로(실제 DB) ──────────────────────────────────────────────────────────────
def test_a19_a21_error_paths_on_real_database(db):
    # A21: 발행 데이터 없음
    prepare_database(db, stocks={}, derive=False)
    with api_client(db) as c:
        r = c.get(URL)
        assert r.status_code == 503 and r.json()["error"]["code"] == "DATA_PIPELINE_STALE"
    # A19: 발행은 됐지만 산정 가능(OK) 행이 0건(이력 부족 종목뿐)
    only_short = {k: v for k, v in build_stocks().items() if k == "T00008"}
    prepare_database(db, stocks=only_short)
    with api_client(db) as c:
        r = c.get(URL)
        assert r.status_code == 424 and r.json()["error"]["code"] == "PATTERN_DATA_NOT_READY"
        assert c.get(URL, params={"market": "KOSDAQ"}).status_code in (424, 200)
    prepare_database(db)  # 이후 테스트를 위해 원상 복구


# ── 성능(TC-P01·P02) ───────────────────────────────────────────────────────────────
def test_p01_p02_response_time_and_query_plan_on_2700_rows(db):
    mig = create_engine(TempDb.render(db.migrator_url))
    wipe(mig)
    seed_calendar(mig)
    batch_id = uuid.uuid4()
    n = 2700
    import random

    rnd = random.Random(1)
    with mig.begin() as c:
        c.execute(
            text(
                "INSERT INTO public_serving.batch_run"
                "(batch_run_id,run_type,status,validation_passed)"
                " VALUES (:i,'derive','SUCCESS',true)"
            ),
            {"i": batch_id},
        )
        c.execute(
            text(
                "INSERT INTO public_serving.stock_master(stock_code,name,market,is_active)"
                " VALUES (:c,:n,:m,true)"
            ),
            [
                {"c": f"P{i:05d}", "n": f"성능{i}", "m": "KOSPI" if i % 2 else "KOSDAQ"}
                for i in range(n)
            ],
        )
        rows = []
        for i in range(n):
            ok = i % 20 != 0

            def val(lo, hi, _ok=ok):
                return rnd.uniform(lo, hi) if _ok else None

            rows.append(
                {
                    "c": f"P{i:05d}",
                    "d": TARGET_DATE,
                    "m": "KOSPI" if i % 2 else "KOSDAQ",
                    "st": "OK" if ok else "INSUFFICIENT_HISTORY",
                    "b": batch_id,
                    "rng": val(1, 80),
                    "net": val(-30, 30),
                    "conv": val(0, 8),
                    "vc": val(0.2, 1.8),
                    "gap": val(-12, 15),
                    "g2": val(-8, 8),
                    "cross": rnd.choice([None, None, 0, 3, 7]) if ok else None,
                    "vr": val(0.5, 4),
                    "an": val(-1, 4),
                    "sg": rnd.random() < 0.2 if ok else None,
                    "cap": rnd.randint(10**10, 10**13),
                    "vol": rnd.randint(1000, 10**7),
                }
            )
        c.execute(
            text(
                "INSERT INTO public_serving.derived_metrics_daily"
                "(stock_code,trade_date,market,pattern_metrics_status,sideways_range_pct,"
                "sideways_net_change_pct,ma_convergence_pct,volatility_contraction_ratio,ma60_gap_pct,"
                "ma20_vs_ma60_gap_pct,ma60_cross_up_days,volume_ratio_5_60,volume_anomaly_score,"
                "recent_surge_flag,market_cap_raw_krw,volume_raw,batch_run_id)"
                " VALUES (:c,:d,:m,:st,:rng,:net,:conv,:vc,:gap,:g2,:cross,:vr,:an,:sg,"
                ":cap,:vol,:b)"
            ),
            rows,
        )
        c.execute(
            text(
                "INSERT INTO public_serving.current_published_batch(market,trade_date,batch_run_id)"
                " VALUES ('KRX',:d,:b)"
            ),
            {"d": TARGET_DATE, "b": batch_id},
        )
    mig.dispose()

    with api_client(db) as client:
        warm = client.get(URL, params={"required": "c1", "page_size": 50})
        assert warm.status_code == 200 and warm.json()["data"]["total_count"] > 0
        times = []
        for k in range(50):
            required = ["c1", "c1,c3", "c2", "c9", "c1,c2,c3,c4,c5,c9"][k % 5]
            t0 = time.perf_counter()
            r = client.get(URL, params={"required": required, "page_size": 50})
            times.append(time.perf_counter() - t0)
            assert r.status_code == 200
            if k % 25 == 24:  # 레이트리밋(분당 60) 방지를 위해 카운터 초기화
                from services.public_api.rate_limit import reset_rate_limit_state

                reset_rate_limit_state()
        p95 = sorted(times)[int(len(times) * 0.95) - 1]
        print(f"\n[P01] n={len(times)} median={statistics.median(times)*1000:.1f}ms "
              f"p95={p95*1000:.1f}ms max={max(times)*1000:.1f}ms")  # fmt: skip
        assert p95 <= 0.5  # 05 §9: p95 ≤ 500ms (로컬 PG, ~2,700종목)

    # P02: 실행 계획 — 단일 거래일 범위로 좁혀지고 행 수가 ~2,700 규모임을 기록
    from services.public_api.core.pattern_config import load_pattern_thresholds as load
    from services.public_api.db.pattern_repository import PatternFilters, SqlPatternScreenRepository

    eng = create_engine(TempDb.render(db.api_url))
    with Session(eng) as s:
        repo = SqlPatternScreenRepository(s)
        stmt = repo.search_statement(
            PatternFilters(TARGET_DATE, "ALL", ("c1", "c2", "c3", "c4", "c5", "c9"), None, None,
                           "market_cap", "desc", 1, 50),
            load({}),
        )  # fmt: skip
        plan = "\n".join(
            r[0]
            for r in s.execute(
                text(
                    "EXPLAIN "
                    + str(stmt.compile(s.get_bind(), compile_kwargs={"literal_binds": True}))
                )
            )
        )
    print("\n[P02] EXPLAIN\n" + plan)
    assert "derived_metrics_daily" in plan
    assert "Seq Scan" in plan or "Index Scan" in plan or "Bitmap" in plan
    eng.dispose()
