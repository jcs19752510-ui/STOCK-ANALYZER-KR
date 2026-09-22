"""services/ingestion_batch/ksic_lookup.py 단위테스트.

`data/reference/ksic_codes.csv`(FinanceData/KSIC 공개 코드표) 자체가 아니라
조회 로직(정확 일치 -> 자릿수 축소 재시도 -> 못 찾으면 None)을 임시 CSV로
검증한다. 실제 코드표 대조 검증(DART induty_code="264"가 코드표의
"264: 통신 및 방송 장비 제조업"과 정확히 일치)은 2026-09-22 삼성전자 실
데이터로 이미 수동 확인했다(테스트 결과서 참조).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from services.ingestion_batch.ksic_lookup import _load_code_map, lookup_sector_name


@pytest.fixture
def sample_csv(tmp_path: Path) -> Path:
    csv_path = tmp_path / "ksic_sample.csv"
    csv_path.write_text(
        '"Industy_code","Industy_name"\n'
        '"26","전자부품, 컴퓨터, 영상, 음향 및 통신장비 제조업"\n'
        '"264","통신 및 방송 장비 제조업"\n',
        encoding="utf-8",
    )
    _load_code_map.cache_clear()
    return csv_path


def test_exact_match(sample_csv: Path):
    assert lookup_sector_name("264", csv_path=sample_csv) == "통신 및 방송 장비 제조업"


def test_falls_back_to_shorter_prefix_when_no_exact_match(sample_csv: Path):
    # "2641"처럼 더 세분화된 코드가 코드표에 없으면 한 자리 줄여 "264"로 재시도.
    assert lookup_sector_name("2641", csv_path=sample_csv) == "통신 및 방송 장비 제조업"


def test_returns_none_when_nothing_matches(sample_csv: Path):
    assert lookup_sector_name("999", csv_path=sample_csv) is None


def test_returns_none_for_empty_or_missing_code(sample_csv: Path):
    assert lookup_sector_name(None, csv_path=sample_csv) is None
    assert lookup_sector_name("", csv_path=sample_csv) is None
    assert lookup_sector_name("   ", csv_path=sample_csv) is None
