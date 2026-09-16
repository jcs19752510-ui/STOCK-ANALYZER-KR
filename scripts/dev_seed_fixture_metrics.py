#!/usr/bin/env python
"""UNIT-06 로컬 검증 전용 픽스처 시딩 스크립트 (REQ-002, 개발자 로컬 전용).

**이 스크립트는 운영 파이프라인의 일부가 아니다.** Ingestion Batch가 실
서비스키 없이는 검증되지 않은 상태(unit-02-note.md)라 `raw_internal.
raw_ohlcv`/`raw_fundamentals`가 비어 있는 로컬 환경에서, Derivation Batch
(`services/derivation_batch/run_derivation.py`)의 가공 로직을 **실제
PostgreSQL**로 종단간 검증하기 위해 종가/거래량/PER·PBR·시가총액
**테스트 픽스처**를 직접 적재한다. 상상 데이터를 실제 운영 데이터인 것처럼
속이지 않기 위해, 여기서 만드는 값은 전부 합성 데이터임을 명시한다
(`unit-06-note.md` §3 참조).

사용법(로컬 Docker PostgreSQL, batch_worker 계정 필요):
    BATCH_DATABASE_URL=postgresql+psycopg://batch_worker:<pw>@localhost:5432/stock_screener \\
        python scripts/dev_seed_fixture_metrics.py

시딩 후 `python -m services.derivation_batch.run_derivation --trade-date 2026-09-14`를
실행하면 실제 등락률 순위/이동평균 괴리율/거래량 이상치 스코어/PER·PBR·
시가총액 백분위가 계산되어 `public_serving.derived_metrics_daily`에
적재되는 것을 확인할 수 있다.

정리(다음 세션을 위해 되돌리기):
    TRUNCATE public_serving.derived_metrics_daily, public_serving.current_published_batch CASCADE;
    DELETE FROM raw_internal.raw_ohlcv WHERE stock_code IN ('005930','000660');
    DELETE FROM raw_internal.raw_fundamentals WHERE stock_code IN ('005930','000660');
    DELETE FROM public_serving.stock_master WHERE stock_code IN ('005930','000660');
    DELETE FROM public_serving.batch_run WHERE run_type IN ('ingest','derive');
"""

from __future__ import annotations

import sys
import uuid
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from services.derivation_batch.core.config import ConfigError, get_settings  # noqa: E402

# 실제 reference.market_calendar(KRX)에 존재하는, 2026-09-14 기준 최근
# 25거래일(주말/공휴일 제외 — 로컬 검증 시 `select trade_date from
# reference.market_calendar where market='KRX' and is_trading_day and
# trade_date <= '2026-09-14' order by trade_date desc limit 25;`로 재확인 가능).
TRADE_DATES = [
    date(2026, 8, 11), date(2026, 8, 12), date(2026, 8, 13), date(2026, 8, 14),
    date(2026, 8, 17), date(2026, 8, 18), date(2026, 8, 19), date(2026, 8, 20),
    date(2026, 8, 21), date(2026, 8, 24), date(2026, 8, 25), date(2026, 8, 26),
    date(2026, 8, 27), date(2026, 8, 28), date(2026, 8, 31), date(2026, 9, 1),
    date(2026, 9, 2), date(2026, 9, 3), date(2026, 9, 4), date(2026, 9, 7),
    date(2026, 9, 8), date(2026, 9, 9), date(2026, 9, 10), date(2026, 9, 11),
    date(2026, 9, 14),
]  # fmt: skip

# (stock_code, 종목명, 기준 종가, 기준 거래량, 일별 증분, 마지막날 종가, 마지막날 거래량)
# 005930: 완만한 상승 + 마지막날 거래량 급증(거래량 이상치 스코어 양수 기대)
# 000660: 완만한 하락(등락률 순위 하위 기대)
STOCKS = [
    ("005930", "삼성전자(테스트픽스처)", 70000, 10_000_000, 200, 78000, 60_000_000),
    ("000660", "SK하이닉스(테스트픽스처)", 150000, 5_000_000, -300, 142000, 5_200_000),
]


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    try:
        settings = get_settings()
    except ConfigError as exc:
        print(f"[실패] {exc}", file=sys.stderr)
        return 1

    engine = create_engine(settings.database_url)
    last_date = TRADE_DATES[-1]

    with Session(engine) as session:
        for stock_code, name, *_ in STOCKS:
            session.execute(
                text(
                    "INSERT INTO public_serving.stock_master (stock_code, name, market, is_active) "
                    "VALUES (:code, :name, 'KOSPI', true) "
                    "ON CONFLICT (stock_code) DO UPDATE SET name = EXCLUDED.name"
                ),
                {"code": stock_code, "name": name},
            )

        ingest_run_id = uuid.uuid4()
        session.execute(
            text(
                "INSERT INTO public_serving.batch_run "
                "(batch_run_id, run_type, status, validation_passed, trade_date_covered) "
                "VALUES (:id, 'ingest', 'SUCCESS', true, :d)"
            ),
            {"id": ingest_run_id, "d": last_date},
        )

        for stock_code, _name, base_close, base_volume, drift, last_close, last_volume in STOCKS:
            for idx, trade_date in enumerate(TRADE_DATES):
                if trade_date == last_date:
                    close, volume = last_close, last_volume
                else:
                    close = base_close + drift * idx
                    volume = base_volume + (idx % 3) * 100_000
                session.execute(
                    text(
                        "INSERT INTO raw_internal.raw_ohlcv "
                        "(stock_code, trade_date, market, open, high, low, close, volume, "
                        " trading_value, source_batch_id) "
                        "VALUES (:code, :d, 'KRX', :close, :close, :close, :close, :volume, "
                        " :trading_value, :bid) "
                        "ON CONFLICT (stock_code, trade_date, market) DO UPDATE SET "
                        " close = EXCLUDED.close, volume = EXCLUDED.volume"
                    ),
                    {
                        "code": stock_code,
                        "d": trade_date,
                        "close": close,
                        "volume": volume,
                        "trading_value": close * volume,
                        "bid": ingest_run_id,
                    },
                )

        session.execute(
            text(
                "INSERT INTO raw_internal.raw_fundamentals "
                "(stock_code, trade_date, per, pbr, market_cap, source_batch_id) "
                "VALUES ('005930', :d, 15.5, 1.8, 500000000000000, :bid), "
                "       ('000660', :d, 25.0, 3.2, 100000000000000, :bid) "
                "ON CONFLICT (stock_code, trade_date) DO UPDATE SET "
                " per = EXCLUDED.per, pbr = EXCLUDED.pbr, market_cap = EXCLUDED.market_cap"
            ),
            {"d": last_date, "bid": ingest_run_id},
        )

        session.commit()

    print(f"[완료] 테스트 픽스처 적재 완료 (ingest_run_id={ingest_run_id}, last_date={last_date})")
    print(
        "  다음: python -m services.derivation_batch.run_derivation "
        f"--trade-date {last_date.isoformat()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
