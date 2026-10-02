"""Q3 평가 대상 제외(스팩·우선주) 통합 테스트 — 임시 DB + 실제 FastAPI 앱.

성능 테스트(2,700행)가 있는 `test_pattern_api_db.py`와 분리해 픽스처 10종목만 있는 깨끗한 DB에서
결과 개수를 정확히 검증한다. 개발 DB에는 아무것도 쓰지 않는다.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text

from services.public_api.core.pattern_config import load_pattern_thresholds
from tests.integration.pattern_api_env import api_client, prepare_database
from tests.integration.pattern_fixtures import TARGET_DATE
from tests.integration.pg_temp_db import TempDb, TempDbUnavailable, temp_database

URL = "/api/v1/screen/pattern"


@pytest.fixture(scope="module")
def db() -> Iterator[TempDb]:
    try:
        with temp_database() as tdb:
            prepare_database(tdb)
            yield tdb
    except TempDbUnavailable as exc:
        pytest.skip(f"임시 DB를 만들 수 없어 건너뜀(통과로 세지 않음): {exc}")

SPECIAL_ROWS = [
    # (코드, 이름, 제외 대상?) — 우선주는 "이름이 우로 끝남 + 코드 끝자리 != 0"
    ("Q00010", "테스트스팩", True),  # 스팩: 이름에 '스팩'
    ("Q00015", "삼성테스트우", True),  # 우선주
    ("Q00017", "현대테스트2우B", True),  # 우선주(2우B)
    ("Q00025", "한화테스트3우(전환)", True),  # 우선주(전환)
    ("Q00020", "성우", False),  # 보통주인데 이름이 '우'로 끝남 — 코드 끝자리 0 → 제외하면 안 됨(오탐 방지)
    ("Q00030", "우리테스트기술", False),  # '우'가 이름 앞에 있는 보통주
]


def _insert_special_rows(db) -> uuid.UUID:
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
            for code, name, _ in SPECIAL_ROWS:
                c.execute(
                    text(
                        "INSERT INTO public_serving.stock_master(stock_code,name,market,is_active)"
                        " VALUES (:c,:n,'KOSPI',true)"
                    ),
                    {"c": code, "n": name},
                )
                c.execute(  # 상태 OK + 급등 이력 없음(c9 충족) — 필수 c9로 조회하면 통과해야 하는 행
                    text(
                        "INSERT INTO public_serving.derived_metrics_daily"
                        "(stock_code,trade_date,market,pattern_metrics_status,recent_surge_flag,"
                        "batch_run_id) VALUES (:c,:d,'KOSPI','OK',false,:b)"
                    ),
                    {"c": code, "d": TARGET_DATE, "b": batch_id},
                )
    finally:
        mig.dispose()
    return batch_id


def _remove_special_rows(db, batch_id) -> None:
    mig = create_engine(TempDb.render(db.migrator_url))
    try:
        codes = [c for c, _, _ in SPECIAL_ROWS]
        with mig.begin() as c:
            c.execute(
                text("DELETE FROM public_serving.derived_metrics_daily WHERE stock_code = ANY(:c)"),
                {"c": codes},
            )
            c.execute(
                text("DELETE FROM public_serving.stock_master WHERE stock_code = ANY(:c)"),
                {"c": codes},
            )
            c.execute(text("DELETE FROM public_serving.batch_run WHERE batch_run_id=:b"), {"b": batch_id})
    finally:
        mig.dispose()


def test_q3_spac_and_preferred_are_excluded_by_default_but_look_alike_common_stocks_are_kept(db):
    batch_id = _insert_special_rows(db)
    try:
        with api_client(db) as c:  # 앞선 테스트가 dependency_overrides를 비우므로 자체 클라이언트 사용
            data = c.get(URL, params={"required": "c9", "page_size": 200}).json()["data"]
        got = {i["stock_code"] for i in data["items"]}
        excluded = {c for c, _, ex in SPECIAL_ROWS if ex}
        kept = {c for c, _, ex in SPECIAL_ROWS if not ex}
        assert not (got & excluded), got & excluded  # 스팩·우선주는 결과에 없다
        assert kept <= got  # '성우'(보통주)·'우리테스트기술'은 포함
        assert data["total_count"] == len(got)  # 개수도 제외 후 기준
        # 평가 대상 집계(readiness)에서도 제외: 기존 10종목 + 보통주 2종목
        assert data["readiness"]["total_count"] == 12
        assert data["readiness"]["evaluated_count"] == 10
        assert data["definition"]["universe"] == {"excluded_types": ["SPAC", "PREFERRED"]}
    finally:
        _remove_special_rows(db, batch_id)


def test_q3_exclusion_can_be_switched_off_by_server_setting(db):
    from services.public_api.api.pattern import get_pattern_thresholds
    from services.public_api.main import app

    batch_id = _insert_special_rows(db)
    try:
        with api_client(db) as c:
            app.dependency_overrides[get_pattern_thresholds] = lambda: load_pattern_thresholds(
                {"PATTERN_EXCLUDE_SPAC_PREFERRED": "false"}
            )
            data = c.get(URL, params={"required": "c9", "page_size": 200}).json()["data"]
        got = {i["stock_code"] for i in data["items"]}
        assert {c for c, _, _ in SPECIAL_ROWS} <= got  # 스위치 off면 모두 포함
        assert data["readiness"]["total_count"] == 16  # 10 + 6
        assert data["definition"]["universe"] == {"excluded_types": []}
    finally:
        _remove_special_rows(db, batch_id)
