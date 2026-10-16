"""start_local_api.ps1이 `.env`에서 서버로 넘기는 키 목록 — 개인 로컬 모드가 읽는 키가 빠지면 `.env`에 넣어도 서버에 전달되지 않는다."""

# ruff: noqa: E501
from __future__ import annotations

import re
from pathlib import Path

PS1 = (Path(__file__).resolve().parents[2] / "scripts" / "start_local_api.ps1").read_text(encoding="utf-8")


def _keys() -> set[str]:
    block = re.search(r"\$keys\s*=\s*@\((.*?)\)", PS1, re.S).group(1)
    return set(re.findall(r'"([A-Z0-9_]+)"', block))


def test_로컬_모드가_읽는_증권사_키가_모두_전달_목록에_있다():
    keys = _keys()
    for needed in ("LOCAL_INTRADAY_ENABLED", "KIS_APP_KEY", "KIS_APP_SECRET", "KIS_HTS_ID", "KIS_MARKET_MIN_INTERVAL", "KIS_MARKET_CONCURRENCY"):
        assert needed in keys, f"{needed} 가 start_local_api.ps1 키 목록에 없다 → .env에 넣어도 API에 전달되지 않는다"


def test_로그인_설정_키도_전달된다():
    assert {"PUBLIC_API_AUTH_DATABASE_URL", "PUBLIC_API_INTERNAL_TOKEN", "PUBLIC_API_REQUIRE_INTERNAL_TOKEN"} <= _keys()
