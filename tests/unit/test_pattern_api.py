"""`GET /api/v1/screen/pattern` 단위테스트 — 가짜 리포지토리 기반 (REQ-032/034/035/036,
05-test-plan §7 TC-A·§8 TC-S).

DB 없이 입력 검증·에러 코드·응답 형태·화이트리스트·미들웨어 적용을 검증한다. 실제 SQL(필터·정렬· 3값
논리·`ma60_stage`)과 골든 비교(`/screen` 불변)는 `tests/integration/test_pattern_api_db.py`.

주의(05 A15 보정): `required` 조건은 `expr IS TRUE`로 걸리므로 **산정 불가 종목은 결과 행으로 나올
수 없다**(설계서 §5-4). 따라서 "이력 부족 종목이 전 조건 null로 나온다"는 응답 행 검증이 아니라
`reason_for()` 매핑과 SQL 계층(`test_pattern_conditions_db.py`)에서 검증한다. 결과 행에서 null이
나오는 경우는 `required`가 아닌 조건의 셀(예: 평탄 종목의 c2·c5)이다.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
import time as time_module
from datetime import date, time
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from services.public_api.api.pattern import (
    SORT_BY_VALUES,
    get_pattern_calendar_repository,
    get_pattern_repository,
    get_pattern_thresholds,
    parse_required,
    reason_for,
)
from services.public_api.core.config import get_cors_allowed_origins
from services.public_api.core.pattern_config import load_pattern_thresholds
from services.public_api.db.pattern_repository import PatternQueryResult, PatternRow
from services.public_api.db.session import get_db
from services.public_api.errors import ApiError
from services.public_api.main import app
from services.public_api.rate_limit import DEFAULT_LIMIT, reset_rate_limit_state
from shared.calendar_service import CalendarIntegrityError
from shared.calendar_service.types import CalendarRow

REPO_ROOT = Path(__file__).resolve().parents[2]
PUBLISHED = date(2026, 9, 30)
ALL_REQUIRED = ["c1", "c2", "c3", "c4", "c5", "c9"]
METRIC_KEYS = {
    "sideways_range_pct",
    "sideways_net_change_pct",
    "ma_convergence_pct",
    "volatility_contraction_ratio",
    "ma60_gap_pct",
    "ma20_vs_ma60_gap_pct",
    "ma60_slope_pct",
    "ma60_cross_up_days",
    "volume_ratio_5_60",
    "volume_anomaly_score",
    "recent_surge_flag",
}
ITEM_KEYS = {"stock_code", "name", "market", "conditions", "metrics", "ma60_stage"}
SEC_HEADERS = ("Content-Security-Policy", "X-Content-Type-Options", "Strict-Transport-Security")


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    reset_rate_limit_state()
    yield
    app.dependency_overrides.clear()
    reset_rate_limit_state()


class WeekdayCalendar:
    """어떤 날짜든 평일=거래일(마감 15:30)로 답하는 캘린더 — 실제 현재 시각과 무관하게 동작."""

    def get(self, trade_date: date, market: str) -> CalendarRow | None:
        trading = trade_date.weekday() < 5
        return CalendarRow(
            trade_date=trade_date,
            market=market,
            is_trading_day=trading,
            session_close_at=time(15, 30) if trading else None,
            holiday_name=None if trading else "휴장",
            source="test",
        )


class GapCalendar:
    def get(self, trade_date: date, market: str):
        return None


class BrokenCalendar:
    def get(self, trade_date: date, market: str):
        raise CalendarIntegrityError("캘린더 이상")


def _row(code="T00001", market="KOSPI", **over) -> PatternRow:
    base = {
        "stock_code": code,
        "name": "테스트",
        "market": market,
        "status": "OK",
        "stage": "BELOW_NEAR",
        "conds": dict.fromkeys(ALL_REQUIRED, True),
        "metrics": {
            "sideways_range_pct": Decimal("18.2000"),
            "sideways_net_change_pct": Decimal("-3.1000"),
            "ma_convergence_pct": Decimal("1.9000"),
            "volatility_contraction_ratio": Decimal("0.7200"),
            "ma60_gap_pct": Decimal("-1.4000"),
            "ma20_vs_ma60_gap_pct": Decimal("0.6000"),
            "ma60_slope_pct": Decimal("-0.8000"),
            "ma60_cross_up_days": None,
            "volume_ratio_5_60": Decimal("1.3000"),
            "volume_anomaly_score": Decimal("0.6000"),
            "recent_surge_flag": False,
        },
    }
    base.update(over)
    return PatternRow(**base)


class FakeRepo:
    def __init__(self, *, published=PUBLISHED, total=10, ok=8, rows=None, total_count=None):
        self.published = published
        self.total, self.ok = total, ok
        self.rows = [_row()] if rows is None else rows
        self.total_count = len(self.rows) if total_count is None else total_count
        self.calls: list[tuple] = []

    def get_current_published_trade_date(self, market):
        self.calls.append(("published", market))
        return self.published

    def readiness(self, trade_date, market, thresholds):
        self.calls.append(("readiness", trade_date, market))
        self.readiness_thresholds = thresholds
        return self.total, self.ok

    def search(self, filters, thresholds):
        self.calls.append(("search", filters, thresholds))
        return PatternQueryResult(items=self.rows, total_count=self.total_count)


def _client(repo=None, *, calendar=None, thresholds=None) -> tuple[TestClient, FakeRepo]:
    repo = repo or FakeRepo()
    app.dependency_overrides[get_pattern_repository] = lambda: repo
    app.dependency_overrides[get_pattern_calendar_repository] = lambda: (
        calendar or WeekdayCalendar()
    )
    app.dependency_overrides[get_pattern_thresholds] = lambda: (
        thresholds or load_pattern_thresholds({})
    )
    return TestClient(app), repo


def _error(resp, status, code):
    assert resp.status_code == status, resp.text
    body = resp.json()
    assert body["data"] is None and body["error"]["code"] == code, body


# ── 라우트 등록·기존 /screen 공존 ────────────────────────────────────────────────
def test_route_registered_and_existing_screen_route_still_present():
    paths = app.openapi()["paths"]
    assert "get" in paths["/api/v1/screen/pattern"]
    assert "get" in paths["/api/v1/screen"]
    assert set(paths["/api/v1/screen/pattern"]) == {"get"}  # 읽기 전용 GET만


# ── TC-A01/A26: 기본 호출·envelope ───────────────────────────────────────────────
def test_a01_a26_default_call_envelope_structure():
    client, repo = _client()
    resp = client.get("/api/v1/screen/pattern")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["error"] is None
    meta = body["meta"]
    assert meta["disclaimer"] and meta["generated_at"]
    fresh = meta["data_freshness"]
    assert fresh["trade_date"] == "2026-09-30" and fresh["market"] == "KRX"
    # staleness_note는 최신 거래일이 아닐 때만(일관성)
    assert (fresh["staleness_note"] is None) == fresh["is_latest_trading_day"]
    data = body["data"]
    assert set(data) == {"items", "total_count", "page", "definition", "readiness"}
    assert data["page"] == 1 and data["total_count"] == 1
    # 기본 required = 6개 전부, 기본 정렬 market_cap desc
    search = next(c for c in repo.calls if c[0] == "search")
    assert list(search[1].required) == ALL_REQUIRED
    assert (search[1].market, search[1].sort_by, search[1].sort_dir) == (
        "ALL",
        "market_cap",
        "desc",
    )
    assert (search[1].page, search[1].page_size) == (1, 50)


# ── TC-A05~A08: required 파싱 ───────────────────────────────────────────────────
@pytest.mark.parametrize(
    "raw",
    [
        "c1,c1",  # A05 중복
        "c7",  # A06 미지 ID
        "c6",
        "c8",
        "C1",  # 대소문자 구분
        "",  # A07 빈 값
        "c1, c2",  # A08 공백
        " c1",
        "c1 ",
        "c1,",  # 빈 토큰
        ",c1",
        "c1,,c2",
        "c1;c2",
        "c1,c2,c3,c4,c5,c9,c1",  # 6개 초과(중복)
        "c1,c2,c3,c4,c5,c9,c10",
        "'; DROP TABLE derived_metrics_daily; --",  # S01
        "c1) OR (1=1",
        ",".join(["c1"] * 1000),  # S02
        "c1" * 5000,
    ],
)
def test_a05_to_a08_s01_s02_invalid_required_is_400_and_repo_never_called(raw):
    client, repo = _client()
    t0 = time_module.perf_counter()
    resp = client.get("/api/v1/screen/pattern", params={"required": raw})
    elapsed = time_module.perf_counter() - t0
    _error(resp, 400, "INVALID_PARAMETER")
    assert repo.calls == []  # 검증 실패 시 DB 접근 없음
    assert elapsed < 1.0  # S02: 파싱 상한으로 즉시 응답


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("c1", ["c1"]),
        ("c9,c1", ["c1", "c9"]),  # 입력 순서와 무관하게 정규 순서
        ("c5,c4,c3,c2,c1,c9", ALL_REQUIRED),
    ],
)
def test_a04_required_subset_is_accepted_in_canonical_order(raw, expected):
    assert parse_required(raw) == expected
    client, repo = _client()
    assert client.get("/api/v1/screen/pattern", params={"required": raw}).status_code == 200
    assert list(next(c for c in repo.calls if c[0] == "search")[1].required) == expected


def test_parse_required_default_is_all_six_and_error_type():
    assert parse_required(None) == ALL_REQUIRED
    with pytest.raises(ApiError) as exc:
        parse_required("c7")
    assert exc.value.status_code == 400 and exc.value.code == "INVALID_PARAMETER"


# ── TC-A09~A12·A02: 기타 파라미터 검증 ─────────────────────────────────────────────
@pytest.mark.parametrize(
    "sort_by", ["market_cap", "ma60_gap_pct", "sideways_range_pct", "ma_convergence_pct"]
)
def test_a09_allowed_sort_by_values(sort_by):
    client, repo = _client()
    assert client.get("/api/v1/screen/pattern", params={"sort_by": sort_by}).status_code == 200
    assert next(c for c in repo.calls if c[0] == "search")[1].sort_by == sort_by
    assert set(SORT_BY_VALUES) == {
        "market_cap",
        "ma60_gap_pct",
        "sideways_range_pct",
        "ma_convergence_pct",
    }


@pytest.mark.parametrize(
    "bad",
    ["score", "rank", "met_count", "return_pct", "market_cap; DROP TABLE x", "", "MARKET_CAP"],
)
def test_a09_s01_disallowed_sort_by_is_400(bad):
    client, repo = _client()
    _error(client.get("/api/v1/screen/pattern", params={"sort_by": bad}), 400, "INVALID_PARAMETER")
    assert repo.calls == []  # 점수·순위 정렬은 제공하지 않는다(REQ-034)


@pytest.mark.parametrize("bad", ["ASC", "up", "", "desc;"])
def test_a10_invalid_sort_dir_is_400(bad):
    client, _ = _client()
    _error(client.get("/api/v1/screen/pattern", params={"sort_dir": bad}), 400, "INVALID_PARAMETER")


def test_a10_sort_dir_asc_and_desc_accepted():
    client, repo = _client()
    for d in ("asc", "desc"):
        assert client.get("/api/v1/screen/pattern", params={"sort_dir": d}).status_code == 200


@pytest.mark.parametrize("params", [{"page_size": 201}, {"page_size": 0}, {"page_size": 1000000}])
def test_a11_page_size_out_of_range_is_400(params):
    client, _ = _client()
    _error(client.get("/api/v1/screen/pattern", params=params), 400, "INVALID_PARAMETER")


@pytest.mark.parametrize("params", [{"page": 0}, {"page": -1}, {"page": "x"}])
def test_a12_invalid_page_uses_same_error_format_as_existing_screen(params):
    client, _ = _client()
    resp = client.get("/api/v1/screen/pattern", params=params)
    _error(resp, 400, "INVALID_PARAMETER")
    # 기존 /screen과 동일한 응답 형식(RequestValidationError → 400 envelope).
    # /screen은 DB 세션 의존성이 있으므로 검증 실패 경로만 보도록 가짜 세션으로 대체한다.
    app.dependency_overrides[get_db] = lambda: iter([None])
    other = client.get("/api/v1/screen", params=params)
    assert other.status_code == 400
    assert other.json()["error"]["code"] == "INVALID_PARAMETER"


def test_page_size_200_is_allowed_boundary():
    client, repo = _client()
    assert client.get("/api/v1/screen/pattern", params={"page_size": 200}).status_code == 200
    assert next(c for c in repo.calls if c[0] == "search")[1].page_size == 200


@pytest.mark.parametrize("market", ["ALL", "KOSPI", "KOSDAQ"])
def test_a02_market_is_passed_through(market):
    client, repo = _client()
    assert client.get("/api/v1/screen/pattern", params={"market": market}).status_code == 200
    assert next(c for c in repo.calls if c[0] == "search")[1].market == market
    assert next(c for c in repo.calls if c[0] == "readiness")[2] == market  # 시장 필터 후 집합


@pytest.mark.parametrize("market", ["kospi", "NXT", "", "KOSPI,KOSDAQ", "ALL'--"])
def test_invalid_market_is_400(market):
    client, _ = _client()
    _error(
        client.get("/api/v1/screen/pattern", params={"market": market}), 400, "INVALID_PARAMETER"
    )


@pytest.mark.parametrize(
    "params",
    [{"market_cap_min": -1}, {"volume_min": -5}, {"market_cap_min": "abc"}, {"volume_min": 1.5}],
)
def test_a27_numeric_filters_are_validated(params):
    client, _ = _client()
    _error(client.get("/api/v1/screen/pattern", params=params), 400, "INVALID_PARAMETER")


def test_a27_filters_are_passed_to_repository_and_not_echoed_in_response():
    client, repo = _client()
    resp = client.get(
        "/api/v1/screen/pattern", params={"market_cap_min": 500000000000, "volume_min": 100000}
    )
    assert resp.status_code == 200
    f = next(c for c in repo.calls if c[0] == "search")[1]
    assert (f.market_cap_min, f.volume_min) == (500000000000, 100000)
    assert "500000000000" not in resp.text and "100000" not in json.dumps(
        resp.json()["data"]["items"]
    )


# ── TC-S03·S04: 알 수 없는 파라미터·임계값 우회 시도는 무시 ───────────────────────────
def test_s03_s04_unknown_and_threshold_params_are_ignored():
    th = load_pattern_thresholds({})
    client, repo = _client(thresholds=th)
    base = client.get("/api/v1/screen/pattern")
    attack = client.get(
        "/api/v1/screen/pattern",
        params={
            "range_max_pct": 100,
            "threshold": 999,
            "PATTERN_RANGE_MAX_PCT": 100,
            "thresholds[range_max_pct]": 100,
            "foo": "bar",
        },
    )
    assert attack.status_code == 200
    assert attack.json()["data"] == base.json()["data"]
    searches = [c for c in repo.calls if c[0] == "search"]
    assert all(s[2] is th for s in searches)  # 항상 서버 설정 객체만 사용


# ── TC-A19~A22: 에러 흐름 ───────────────────────────────────────────────────────
def test_a19_pattern_data_not_ready_is_424_and_search_is_skipped():
    client, repo = _client(FakeRepo(total=2760, ok=0))
    resp = client.get("/api/v1/screen/pattern", params={"market": "KOSDAQ"})
    _error(resp, 424, "PATTERN_DATA_NOT_READY")
    assert "시세 기간" in resp.json()["error"]["message"]
    assert [c[0] for c in repo.calls] == ["published", "readiness"]  # search 호출 없음
    assert repo.calls[1][2] == "KOSDAQ"  # 부분 시장 미준비 상태를 숨기지 않는다


def test_a20_some_ready_but_zero_matches_is_200_with_empty_list():
    client, _ = _client(FakeRepo(total=2760, ok=2650, rows=[], total_count=0))
    resp = client.get("/api/v1/screen/pattern")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["items"] == [] and data["total_count"] == 0
    assert data["readiness"] == {
        "evaluated_count": 2650,
        "total_count": 2760,
        "ready_ratio": round(2650 / 2760, 4),
    }


def test_a21_no_published_data_is_503_data_pipeline_stale():
    client, _ = _client(FakeRepo(published=None))
    _error(client.get("/api/v1/screen/pattern"), 503, "DATA_PIPELINE_STALE")


def test_a22_calendar_errors_follow_existing_codes():
    client, _ = _client(calendar=GapCalendar())
    _error(client.get("/api/v1/screen/pattern"), 424, "CALENDAR_NOT_CONFIRMED")
    client, _ = _client(calendar=BrokenCalendar())
    _error(client.get("/api/v1/screen/pattern"), 503, "SERVICE_UNAVAILABLE")


def test_a25_feature_switch_off_returns_404_feature_disabled_without_db_access():
    client, repo = _client(thresholds=load_pattern_thresholds({"PATTERN_SCREEN_ENABLED": "false"}))
    _error(client.get("/api/v1/screen/pattern"), 404, "FEATURE_DISABLED")
    assert repo.calls == []


# ── TC-A15(매핑)·A33: 산정 불가 사유 매핑 ───────────────────────────────────────────
@pytest.mark.parametrize(
    ("met", "status", "reason"),
    [
        (True, "OK", None),
        (False, "OK", None),
        (None, "INSUFFICIENT_HISTORY", "INSUFFICIENT_HISTORY"),
        (None, "SUSPECT_PRICE_JUMP", "SUSPECT_PRICE_JUMP"),
        (None, "OK", "METRIC_UNAVAILABLE"),  # 상태 OK인데 개별 값이 NULL
        (None, None, "METRIC_UNAVAILABLE"),  # 구 배치 행(A33)
        (True, "INSUFFICIENT_HISTORY", None),  # met가 값이면 사유 없음
    ],
)
def test_a15_a33_reason_mapping(met, status, reason):
    assert reason_for(met, status) == reason


def test_condition_cells_expose_met_and_reason_for_non_required_nulls():
    row = _row(
        status="OK",
        stage="ABOVE_SETTLED",
        conds={"c1": True, "c2": None, "c3": True, "c4": False, "c5": None, "c9": True},
    )
    client, _ = _client(FakeRepo(rows=[row]))
    item = client.get("/api/v1/screen/pattern", params={"required": "c1,c3,c9"}).json()["data"][
        "items"
    ][0]
    assert item["conditions"]["c2"] == {"met": None, "reason": "METRIC_UNAVAILABLE"}
    assert item["conditions"]["c4"] == {"met": False, "reason": None}
    assert item["conditions"]["c1"] == {"met": True, "reason": None}
    assert item["ma60_stage"] == "ABOVE_SETTLED"


# ── TC-A23·S07: 응답 필드 화이트리스트(가격·원값 비노출) ─────────────────────────────────
FORBIDDEN_KEYS = {
    "open", "high", "low", "close", "volume", "volume_raw", "trading_value",
    "market_cap", "market_cap_raw_krw", "per_raw", "pbr_raw",
}  # fmt: skip


def _walk_keys(node):
    if isinstance(node, dict):
        for k, v in node.items():
            yield k
            yield from _walk_keys(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk_keys(v)


def test_a23_response_keys_are_exactly_the_whitelist_and_no_raw_fields():
    client, _ = _client()
    data = client.get("/api/v1/screen/pattern").json()["data"]
    item = data["items"][0]
    assert set(item) == ITEM_KEYS
    assert set(item["metrics"]) == METRIC_KEYS
    assert set(item["conditions"]) == set(ALL_REQUIRED)
    assert set(item["conditions"]["c1"]) == {"met", "reason"}
    keys = set(_walk_keys(data))
    assert not (keys & FORBIDDEN_KEYS), keys & FORBIDDEN_KEYS
    assert not any(k.endswith("_raw") for k in keys)
    assert not any("percentile" in k or k in {"score", "rank", "rank_pct"} for k in keys)


def test_s07_response_schema_declares_no_price_or_raw_fields():
    tree = ast.parse(
        (REPO_ROOT / "services/public_api/schemas/pattern.py").read_text(encoding="utf-8")
    )
    declared = {
        n.target.id
        for n in ast.walk(tree)
        if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)
    }
    assert declared, "스키마에 필드가 선언되어야 한다"
    assert not (declared & FORBIDDEN_KEYS)
    assert not any(name.endswith("_raw") for name in declared)
    assert {"stock_code", "name", "market", "conditions", "metrics", "ma60_stage"} <= declared


# ── TC-A24·C08: definition ──────────────────────────────────────────────────────
def test_a24_definition_mirrors_loaded_settings_and_fixed_calc_params():
    th = load_pattern_thresholds(
        {"PATTERN_RANGE_MAX_PCT": "35", "PATTERN_CROSS_EARLY_MAX_DAYS": "6"}
    )
    client, _ = _client(thresholds=th)
    defn = client.get("/api/v1/screen/pattern").json()["data"]["definition"]
    assert defn["version"] == "v1"
    assert defn["thresholds"] == th.definition_thresholds()
    assert (
        defn["thresholds"]["range_max_pct"] == 35.0
        and defn["thresholds"]["cross_early_max_days"] == 6
    )
    assert defn["calc"] == {
        "lookback_days": 80,
        "ma60_window": 60,
        "cross_lookback_days": 10,
        "surge_lookback_days": 20,
        "surge_return_pct": 10.0,
        "surge_volume_mult": 3.0,
    }


# ── TC-A18: readiness ───────────────────────────────────────────────────────────
def test_a18_readiness_counts_and_ratio():
    client, repo = _client(FakeRepo(total=10, ok=8))
    r = client.get("/api/v1/screen/pattern").json()["data"]["readiness"]
    assert r == {"evaluated_count": 8, "total_count": 10, "ready_ratio": 0.8}
    assert next(c for c in repo.calls if c[0] == "readiness")[1] == PUBLISHED


# ── TC-A34: 직렬화 ──────────────────────────────────────────────────────────────
def test_a34_json_is_strict_and_decimals_become_numbers():
    client, _ = _client()
    text_ = client.get("/api/v1/screen/pattern").text

    def reject(constant):
        raise AssertionError(f"비표준 JSON 상수: {constant}")

    parsed = json.loads(text_, parse_constant=reject)  # NaN/Infinity가 있으면 실패
    m = parsed["data"]["items"][0]["metrics"]
    assert isinstance(m["sideways_range_pct"], float) and m["sideways_range_pct"] == 18.2
    assert m["ma60_cross_up_days"] is None and m["recent_surge_flag"] is False
    assert isinstance(m["volume_anomaly_score"], float)


# ── TC-S05·S06·S11: 기존 미들웨어가 신규 경로에도 적용 ──────────────────────────────────
def test_s06_security_headers_on_success_and_error_responses():
    client, _ = _client()
    responses = [
        client.get("/api/v1/screen/pattern"),
        client.get("/api/v1/screen/pattern", params={"required": "c7"}),
        client.get("/api/v1/screen/pattern", params={"page": 0}),
    ]
    client2, _ = _client(FakeRepo(total=5, ok=0))
    responses.append(client2.get("/api/v1/screen/pattern"))
    client3, _ = _client(thresholds=load_pattern_thresholds({"PATTERN_SCREEN_ENABLED": "false"}))
    responses.append(client3.get("/api/v1/screen/pattern"))
    assert [r.status_code for r in responses] == [200, 400, 400, 424, 404]
    for r in responses:
        for h in SEC_HEADERS:
            assert h in r.headers, (r.status_code, h)


def test_s05_rate_limit_applies_to_new_path_with_security_headers_on_429():
    client, _ = _client()
    statuses = [client.get("/api/v1/screen/pattern").status_code for _ in range(DEFAULT_LIMIT + 1)]
    assert statuses[:DEFAULT_LIMIT] == [200] * DEFAULT_LIMIT
    assert statuses[-1] == 429
    last = client.get("/api/v1/screen/pattern")
    assert last.status_code == 429
    for h in SEC_HEADERS:
        assert h in last.headers
    assert last.json()["error"]["code"]  # envelope 형식 유지


def test_s11_cors_preflight_only_allows_configured_origin():
    client, _ = _client()
    allowed = get_cors_allowed_origins()[0]
    ok = client.options(
        "/api/v1/screen/pattern",
        headers={"Origin": allowed, "Access-Control-Request-Method": "GET"},
    )
    assert ok.headers.get("access-control-allow-origin") == allowed
    bad = client.options(
        "/api/v1/screen/pattern",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in bad.headers


# ── TC-S08: DB 장애 시 503 envelope, 내부 정보 비노출 ───────────────────────────────────
def test_s08_db_failure_returns_503_envelope_without_internal_details():
    from sqlalchemy.exc import OperationalError

    class Broken(FakeRepo):
        def readiness(self, trade_date, market, thresholds):
            raise OperationalError("SELECT 1", {}, Exception("password=SECRETPW host=10.0.0.5"))

    client, _ = _client(Broken())
    resp = client.get("/api/v1/screen/pattern")
    _error(resp, 503, "SERVICE_UNAVAILABLE")
    assert "SECRETPW" not in resp.text and "10.0.0.5" not in resp.text
    assert "Traceback" not in resp.text


# ── 기동 시 설정 오류는 즉시 실패(조용한 기본값 대체 금지) ───────────────────────────────
def test_invalid_pattern_environment_prevents_app_start():
    code = "import services.public_api.main"
    env = {**__import__("os").environ, "PATTERN_RANGE_MAX_PCT": "999"}
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    assert proc.returncode != 0
    assert "PATTERN_RANGE_MAX_PCT" in proc.stderr


# ── Q3: 스팩·우선주 제외는 조용히 하지 않는다(definition.universe) ─────────────────────
def test_definition_universe_discloses_excluded_types_and_readiness_receives_same_thresholds():
    th = load_pattern_thresholds({})
    client, repo = _client(thresholds=th)
    data = client.get("/api/v1/screen/pattern").json()["data"]
    assert data["definition"]["universe"] == {"excluded_types": ["SPAC", "PREFERRED"]}
    assert repo.readiness_thresholds is th  # 평가 대상 집계도 같은 설정(제외 여부)을 쓴다

    th_off = load_pattern_thresholds({"PATTERN_EXCLUDE_SPAC_PREFERRED": "false"})
    client, _ = _client(thresholds=th_off)
    off = client.get("/api/v1/screen/pattern").json()["data"]["definition"]["universe"]
    assert off == {"excluded_types": []}


# ── DEC-041: 종목 상세용 단일 종목 조건 체크 ───────────────────────────────────────────
CHECK_URL = "/api/v1/stocks/{code}/pattern-check"


def test_pattern_check_passes_single_stock_filter_with_no_required_and_returns_item():
    client, repo = _client(FakeRepo(rows=[_row("T00001")]))
    resp = client.get(CHECK_URL.format(code="T00001"))
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["item"]["stock_code"] == "T00001" and data["trade_date"]
    assert set(data["item"]["conditions"]) == {"c1", "c2", "c3", "c4", "c5", "c9"}
    assert data["definition"]["universe"] == {"excluded_types": ["SPAC", "PREFERRED"]}
    f = repo.calls[-1][1]
    assert f.stock_code == "T00001" and f.required == ()  # 충족 여부와 무관하게 6개 모두 표시


def test_pattern_check_item_is_null_when_not_evaluated_and_has_no_rank_fields():
    client, _ = _client(FakeRepo(rows=[]))
    data = client.get(CHECK_URL.format(code="Q00010")).json()["data"]
    assert data["item"] is None
    text = str(data)
    for banned in ("score", "rank", "total_met", "met_count"):
        assert banned not in text


def test_pattern_check_respects_feature_switch():
    client, _ = _client(thresholds=load_pattern_thresholds({"PATTERN_SCREEN_ENABLED": "false"}))
    resp = client.get(CHECK_URL.format(code="T00001"))
    _error(resp, 404, "FEATURE_DISABLED")
