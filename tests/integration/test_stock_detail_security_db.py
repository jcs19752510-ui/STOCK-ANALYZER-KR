"""종목 상세(C안) 신규 엔드포인트 보안·견고성 통합 테스트 (DEC-041, UNIT-24).

임시 DB + 실제 FastAPI 앱(읽기 전용 `api_service` 세션). 대상: `/stocks/{code}/prices`,
`/stocks/{code}/earnings`, `/stocks/{code}/pattern-check`, `/stocks/quotes`.
검증: SQL 인젝션·비정상 입력이 데이터를 바꾸거나 내부 정보를 노출하지 않는다 / 쓰기 메서드 거부 /
rate limit 적용 / CORS 비허용 출처 거부 / 응답에 내부 필드 없음. 개발 DB에는 쓰지 않는다.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text

from services.public_api.rate_limit import DEFAULT_LIMIT, reset_rate_limit_state
from tests.integration.pattern_api_env import api_client, prepare_database
from tests.integration.pg_temp_db import TempDb, TempDbUnavailable, temp_database

PATH_ENDPOINTS = ("prices", "earnings", "pattern-check")
HOSTILE_CODES = [
    "T00001'; DROP TABLE public_serving.daily_prices; --",
    "' OR '1'='1",
    "T00001%27%20OR%201%3D1",
    "../../etc/passwd",
    "T00001%00",
    "가나다라마바",
    "A" * 5000,
    "T00001 UNION SELECT 1",
]
LEAK_MARKERS = ("Traceback", "psycopg", "sqlalchemy", "api_service", "permission denied")


@pytest.fixture(scope="module")
def db() -> Iterator[TempDb]:
    try:
        with temp_database() as tdb:
            prepare_database(tdb)
            yield tdb
    except TempDbUnavailable as exc:
        pytest.skip(f"임시 DB를 만들 수 없어 건너뜀(통과로 세지 않음): {exc}")


def _counts(db) -> tuple[int, int, int]:
    eng = create_engine(TempDb.render(db.migrator_url))
    try:
        with eng.connect() as c:
            return tuple(  # type: ignore[return-value]
                c.execute(text(f"SELECT count(*) FROM public_serving.{t}")).scalar_one()
                for t in ("daily_prices", "corp_earnings", "derived_metrics_daily")
            )
    finally:
        eng.dispose()


@pytest.fixture()
def client(db):
    with api_client(db) as c:
        yield c


@pytest.mark.parametrize("endpoint", PATH_ENDPOINTS)
@pytest.mark.parametrize("code", HOSTILE_CODES)
def test_s_path_code_injection_is_inert_and_never_leaks_internals(db, client, endpoint, code):
    before = _counts(db)
    resp = client.get(f"/api/v1/stocks/{code}/{endpoint}")
    assert resp.status_code in (200, 400, 404, 414, 422), (resp.status_code, resp.text[:200])
    assert resp.status_code != 500
    body = resp.text
    assert not any(m in body for m in LEAK_MARKERS), body[:300]
    # 입력을 에러 메시지로 되돌려 주지 않는다(반사 금지): 인젝션 문자열·초장문이 응답에 없어야 한다
    assert "DROP TABLE" not in body and "A" * 50 not in body
    assert _counts(db) == before  # 테이블이 그대로(DROP·DELETE 없음)


@pytest.mark.parametrize(
    "params",
    [
        {"days": "120; DROP TABLE public_serving.daily_prices"},
        {"days": "1e9"},
        {"days": "-1"},
        {"days": "0x10"},
        {"days": "99999999999999999999"},
        {"days": "20' OR '1'='1"},
    ],
)
def test_s_prices_days_param_is_strictly_validated(db, client, params):
    before = _counts(db)
    resp = client.get("/api/v1/stocks/T00001/prices", params=params)
    assert resp.status_code in (400, 422), resp.text[:200]
    assert resp.json()["data"] is None
    assert not any(m in resp.text for m in LEAK_MARKERS)
    assert _counts(db) == before


@pytest.mark.parametrize(
    "codes",
    [
        "T00001'; DROP TABLE public_serving.daily_prices; --",
        "T00001,' OR '1'='1",
        "T00001\n",
        "T00001,T00002,",
        "%",
        "*",
        ",".join(f"A{i:05d}" for i in range(51)),
    ],
)
def test_s_quotes_codes_param_is_whitelisted(db, client, codes):
    before = _counts(db)
    resp = client.get("/api/v1/stocks/quotes", params={"codes": codes})
    assert resp.status_code in (400, 422), resp.text[:200]
    assert not any(m in resp.text for m in LEAK_MARKERS)
    assert _counts(db) == before


def test_s_quotes_missing_param_is_rejected_not_500(client):
    assert client.get("/api/v1/stocks/quotes").status_code in (400, 422)


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/stocks/T00001/prices",
        "/api/v1/stocks/T00001/earnings",
        "/api/v1/stocks/T00001/pattern-check",
        "/api/v1/stocks/quotes",
    ],
)
def test_s_write_methods_are_not_allowed(client, method, path):
    resp = getattr(client, method)(path)
    assert resp.status_code in (404, 405), (method, path, resp.status_code)


def test_s_responses_have_no_internal_or_forbidden_fields(client):
    forbidden = ("_raw", "market_cap", "per", "pbr", "source_batch_id", "batch_run_id", "ingested")
    for url in (
        "/api/v1/stocks/T00001/prices",
        "/api/v1/stocks/T00001/earnings",
        "/api/v1/stocks/T00001/pattern-check",
        "/api/v1/stocks/quotes?codes=T00001",
    ):
        body = client.get(url).json()
        keys = _all_keys(body)
        assert not {k for k in keys if any(k == f or k.endswith(f) for f in forbidden)}, (url, keys)


def _all_keys(obj) -> set[str]:
    out: set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(k)
            out |= _all_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            out |= _all_keys(v)
    return out


def test_s_new_endpoints_are_rate_limited_per_client(client):
    reset_rate_limit_state()
    statuses = [
        client.get("/api/v1/stocks/quotes", params={"codes": "T00001"}).status_code
        for _ in range(DEFAULT_LIMIT + 1)
    ]
    assert statuses[:DEFAULT_LIMIT] == [200] * DEFAULT_LIMIT
    assert statuses[-1] == 429
    reset_rate_limit_state()


def test_s_cors_does_not_allow_unlisted_origin(client):
    resp = client.get(
        "/api/v1/stocks/T00001/prices", headers={"Origin": "https://evil.example.com"}
    )
    assert "access-control-allow-origin" not in {k.lower() for k in resp.headers}
    pre = client.options(
        "/api/v1/stocks/quotes",
        headers={
            "Origin": "https://evil.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert pre.headers.get("access-control-allow-origin") != "https://evil.example.com"


def test_s_error_responses_use_the_common_envelope_without_stack_traces(client):
    resp = client.get("/api/v1/stocks/ZZZZZZ/prices")
    body = resp.json()
    assert resp.status_code == 404
    assert set(body) == {"meta", "data", "error"} and body["data"] is None
    assert set(body["error"]) == {"code", "message"}
