"""한국표준산업분류(KSIC) 코드 -> 업종명 조회 (업종 분류 실데이터, DART 연동).

DART "기업개황" API가 주는 `induty_code`가 표준산업분류 코드 체계를 그대로
따른다는 것을 실측으로 확인했다(2026-09-22, 삼성전자 induty_code="264" ==
KSIC 코드표의 "264: 통신 및 방송 장비 제조업"과 정확히 일치 — 임의 추정이
아니라 공개 코드표 대조로 검증). 코드표 자체는 `data/reference/ksic_codes.csv`
(FinanceData/KSIC 프로젝트가 공개한 9차 개정 코드표, 통계청 표준산업분류
기준)를 그대로 사용한다.

`induty_code`의 자릿수가 회사마다 다를 수 있어(대분류~세세분류, 1~5자리),
정확히 일치하는 코드가 없으면 마지막 한 자리씩 줄여가며(세분류 -> 소분류
-> ...) 다시 찾는다 — 존재하지 않는 업종명을 지어내지 않고, 찾은 만큼만
정확하게 보여준다는 원칙(§8-2 항목8, "업종 정보를 준비 중입니다" 부분 실패
표시 원칙과 동일)을 코드 매칭에도 적용한 것이다.
"""

from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

_DEFAULT_CSV_PATH = Path(__file__).resolve().parents[2] / "data" / "reference" / "ksic_codes.csv"


@lru_cache(maxsize=1)
def _load_code_map(csv_path: str) -> dict[str, str]:
    mapping: dict[str, str] = {}
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = row["Industy_code"].strip()
            name = row["Industy_name"].strip()
            if code:
                mapping[code] = name
    return mapping


def lookup_sector_name(induty_code: str | None, *, csv_path: Path | None = None) -> str | None:
    """`induty_code`에 해당하는 업종명을 반환한다. 못 찾으면 None(지어내지 않음)."""
    if not induty_code:
        return None
    code = induty_code.strip()
    if not code:
        return None

    mapping = _load_code_map(str(csv_path or _DEFAULT_CSV_PATH))
    while code:
        if code in mapping:
            return mapping[code]
        code = code[:-1]
    return None


__all__ = ["lookup_sector_name"]
