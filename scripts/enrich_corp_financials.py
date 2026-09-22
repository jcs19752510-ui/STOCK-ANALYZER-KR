#!/usr/bin/env python
"""DART 연동 — 업종분류·PER/PBR용 재무 원문 수집 스크립트.

`seed_stock_master.py`가 sector를 의도적으로 비워두는 이유(다른 출처가 채울
값을 재시드가 덮어쓰지 않도록)에서 말한 "다른 출처"가 바로 이 스크립트다.
공공데이터포털이 PER/PBR을 제공하지 않는다는 사실이 실측(DEF-005)으로
확정되고, KRX Open API에도 없으며 KRX Data Marketplace의 해당 상품은 유료
구매 항목으로 확인된 뒤(2026-09-22) 도입한 무료 대체 소스다.

이 스크립트가 하는 일(종목마다):
1. `stock_master`에서 활성 종목코드를 가져온다.
2. DART `corpCode.xml`로 (종목코드 -> DART 고유번호) 매핑을 구한다.
3. "기업개황"에서 업종코드를 받아 `data/reference/ksic_codes.csv`로 업종명을
   찾아 `stock_master.sector`를 갱신한다.
4. "단일회사 전체 재무제표"에서 당기순이익/자본총계를 받아
   `raw_internal.raw_corp_financials`에 적재한다(연결(CFS) 우선, 없으면
   개별(OFS)로 대체).

PER/PBR 자체는 이 스크립트가 계산하지 않는다 — `run_ingestion.py`가 매일
시가총액(raw_fundamentals.market_cap)과 이 스크립트가 적재한 재무 원문을
조합해 계산한다(`repository.apply_dart_valuation`).

**재수집 주기(2026-09-22 확정, 시장상황 검토 결과)**: 상장기업 정기보고서
법정 제출기한(자본시장법) — 사업보고서 사업연도 종료 후 90일, 분기/반기
보고서 45일 — 을 근거로 **연 4회**(분기마다) 재실행하는 것을 권장한다.
지각 제출 기업까지 감안한 권장 실행 시점:
  - 매년 4월 5일경  -> 사업보고서(연간, 11011)
  - 매년 5월 20일경 -> 1분기보고서(11013)
  - 매년 8월 20일경 -> 반기보고서(11012)
  - 매년 11월 20일경 -> 3분기보고서(11014)
`resolve_target_report()`가 실행 시점(오늘 날짜) 기준으로 이 중 가장 최근
확정됐을 보고서를 자동으로 고른다 — 운영자가 매번 `--reprt-code`를 외워서
넣을 필요 없이, 위 4개 시점에 그냥 재실행만 하면 된다. 분기/반기 보고서는
연간 실적이 아니라 "연초 누적" 실적만 나오므로(`dart_client.py`
`REPRT_MONTHS_COVERED` 주석 참조, DART 개발가이드 실측 대조), 당기순이익은
12개월 기준으로 연환산해 저장한다(자본총계는 시점 스냅샷이라 연환산 없음).

사용법:
    python scripts/enrich_corp_financials.py
    python scripts/enrich_corp_financials.py --limit 20   # 검증용 소규모 실행
    python scripts/enrich_corp_financials.py --dry-run
    python scripts/enrich_corp_financials.py --bsns-year 2025 --reprt-code 11011  # 수동 지정

명시적 실패 원칙: 종목 단위 오류(특정 종목의 DART 매핑 없음/데이터 없음)는
전체를 막지 않고 건너뛴 뒤 요약에 집계한다 — 이 값들은 애초에
`raw_corp_financials`/`stock_master.sector`가 전 컬럼 nullable로 설계된
"있으면 쓰고 없어도 되는" 보조 데이터이기 때문이다(§0 docstring 참조).
다만 DB 접속 실패, 인증키 미설정처럼 전체를 막는 오류는 0이 아닌 종료 코드로
명시적으로 실패 처리한다.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from services.ingestion_batch.core.config import ConfigError, get_settings  # noqa: E402
from services.ingestion_batch.dart_client import (  # noqa: E402
    DartApiError,
    DartClient,
    DartClientError,
)
from services.ingestion_batch.ksic_lookup import lookup_sector_name  # noqa: E402
from services.ingestion_batch.repository import (  # noqa: E402
    upsert_corp_financials,
    upsert_stock_sector,
)
from shared.db_models.public_serving import StockMaster  # noqa: E402

KST = ZoneInfo("Asia/Seoul")

# 상장기업 정기보고서 법정 제출기한(자본시장법 159조/160조) — 사업보고서는
# 사업연도 종료 후 90일 이내, 분기/반기보고서는 45일 이내. 12월 결산
# 법인(대다수) 기준 마감일은 3/31, 5/15, 8/14, 11/14다. 아래 체크포인트는
# 지각 제출 기업까지 감안해 각 마감일에서 며칠 여유를 둔 시점이다(§0
# docstring "재수집 주기" 참조 — 2026-09-22 시장 관행 조사 후 확정, 사용자
# 승인 완료). 최신 것부터 확인해야 하므로 내림차순으로 정렬돼 있다.
_REPORT_CHECKPOINTS: tuple[tuple[int, int, str], ...] = (
    (11, 20, "11014"),  # 3분기보고서(마감 11/14)
    (8, 20, "11012"),  # 반기보고서(마감 8/14)
    (5, 20, "11013"),  # 1분기보고서(마감 5/15)
    (4, 5, "11011"),  # 사업보고서(마감 3/31, bsns_year는 전년도)
)


def resolve_target_report(today: datetime) -> tuple[str, str]:
    """오늘 날짜 기준 가장 최근 확정 발표됐을 정기보고서를 (bsns_year, reprt_code)로 고른다.

    체크포인트를 아직 하나도 못 지난 해 초(1/1~4/4)는 전년도 3분기보고서가
    가장 최근 확정 실적이다(전년도 사업보고서는 아직 마감 전일 수 있어
    안전하게 한 단계 더 물린다 — 이전 구현의 "1~3월엔 2년 전"보다 더
    정확해졌다: 이제 정확히 "가장 최근 확정된 분기"를 가리킨다).
    """
    month_day = (today.month, today.day)
    for checkpoint_month, checkpoint_day, reprt_code in _REPORT_CHECKPOINTS:
        if month_day >= (checkpoint_month, checkpoint_day):
            bsns_year = today.year - 1 if reprt_code == "11011" else today.year
            return str(bsns_year), reprt_code
    return str(today.year - 1), "11014"


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bsns-year",
        default=None,
        help="대상 사업연도(YYYY). --reprt-code와 함께 지정해야 함. 생략 시 오늘 날짜로 자동 추정.",
    )
    parser.add_argument(
        "--reprt-code",
        default=None,
        choices=("11011", "11012", "11013", "11014"),
        help="대상 보고서구분(11011=사업보고서,11012=반기,11013=1분기,11014=3분기). "
        "--bsns-year와 함께 지정해야 함. 생략 시 오늘 날짜로 자동 추정.",
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="처리할 종목 수 상한(검증용, 생략 시 전체)."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="설정만 검증하고 실제 API 호출/DB 반영은 하지 않는다.",
    )
    args = parser.parse_args(argv)

    try:
        settings = get_settings(require_service_key=False, require_dart_key=not args.dry_run)
    except ConfigError as exc:
        print(f"[실패] {exc}", file=sys.stderr)
        return 1

    if args.dry_run:
        print("(--dry-run) 설정 확인 완료. 실제 API 호출/DB 반영은 하지 않았습니다.")
        print(
            f"  DART_API_KEY: {'설정됨' if settings.dart_api_key else '미설정(dry-run이라 허용)'}"
        )
        return 0

    if args.bsns_year and args.reprt_code:
        bsns_year, reprt_code = args.bsns_year, args.reprt_code
    elif args.bsns_year or args.reprt_code:
        print("[실패] --bsns-year와 --reprt-code는 반드시 함께 지정해야 합니다.", file=sys.stderr)
        return 1
    else:
        bsns_year, reprt_code = resolve_target_report(datetime.now(KST))
    print(f"[정보] 대상 사업연도={bsns_year}, 보고서구분={reprt_code}")

    engine = create_engine(settings.database_url)
    stats = {
        "active_stocks": 0,
        "corp_code_matched": 0,
        "sector_updated": 0,
        "financials_fetched": 0,
        "skipped_no_corp_code": 0,
        "skipped_no_financials": 0,
        "errors": 0,
    }
    error_samples: list[str] = []

    try:
        with (
            Session(engine) as session,
            DartClient(
                api_key=settings.dart_api_key,  # type: ignore[arg-type]
                timeout_seconds=settings.request_timeout_seconds,
                max_retries=settings.max_retries,
            ) as client,
        ):
            active_codes = (
                session.execute(
                    select(StockMaster.stock_code)
                    .where(StockMaster.is_active.is_(True))
                    .order_by(StockMaster.stock_code)
                )
                .scalars()
                .all()
            )
            if args.limit is not None:
                active_codes = active_codes[: args.limit]
            stats["active_stocks"] = len(active_codes)

            print(f"[정보] 활성 종목 {len(active_codes)}건, DART 고유번호 매핑 다운로드 중...")
            corp_code_map = client.fetch_corp_code_map()
            print(f"[정보] DART 고유번호 매핑 {len(corp_code_map)}건 확인")

            # **2026-09-22 추가**: 전 종목(~2,900건) 실행이 DART 요청 제한(020)
            # 재시도 백오프 누적으로 실측 24분 넘게 걸렸는데, 기존 코드는 전체
            # 루프가 끝난 뒤 딱 한 번만 commit해서 — 중간에 프로세스가 죽거나
            # (실제로 이 실행 중 운영자가 "멈춘 것으로 오판"해 강제 종료시킨
            # 사고가 있었다) 어떤 이유로든 끝까지 못 가면 그동안 받은 결과가
            # 전부 유실됐다. `COMMIT_EVERY`마다 지금까지 모은 것만 커밋해
            # 중단돼도 그 지점까지는 남게 한다(멱등 upsert라 재실행해도 안전).
            COMMIT_EVERY = 200
            sector_updates: dict[str, str] = {}
            financials_updates: list[tuple[str, object]] = []

            def _flush() -> None:
                nonlocal sector_updates, financials_updates
                if sector_updates:
                    upsert_stock_sector(session, sector_updates)
                if financials_updates:
                    upsert_corp_financials(session, financials_updates, source_batch_id=None)
                session.commit()
                sector_updates = {}
                financials_updates = []

            for i, stock_code in enumerate(active_codes, start=1):
                corp_code = corp_code_map.get(stock_code)
                if not corp_code:
                    stats["skipped_no_corp_code"] += 1
                    continue
                stats["corp_code_matched"] += 1

                try:
                    overview = client.fetch_company_overview(corp_code)
                    if overview and overview.induty_code:
                        sector_name = lookup_sector_name(overview.induty_code)
                        if sector_name:
                            sector_updates[stock_code] = sector_name
                            stats["sector_updated"] += 1

                    financials = client.fetch_financials(
                        corp_code, bsns_year=bsns_year, reprt_code=reprt_code, fs_div="CFS"
                    )
                    if financials is None:
                        financials = client.fetch_financials(
                            corp_code,
                            bsns_year=bsns_year,
                            reprt_code=reprt_code,
                            fs_div="OFS",
                        )
                    if financials is not None:
                        financials_updates.append((stock_code, financials))
                        stats["financials_fetched"] += 1
                    else:
                        stats["skipped_no_financials"] += 1
                except (DartApiError, DartClientError) as exc:
                    stats["errors"] += 1
                    if len(error_samples) < 10:
                        error_samples.append(f"{stock_code}: {exc}")

                if i % COMMIT_EVERY == 0:
                    _flush()
                    print(f"[진행] {i}/{len(active_codes)}건 처리, 커밋 완료", flush=True)

            _flush()
    except Exception as exc:  # DB/네트워크 계층의 예기치 못한 오류도 명시적으로 알린다
        print(f"[실패] 예기치 못한 오류: {exc}", file=sys.stderr)
        return 1

    print("[완료] 결과 요약:")
    for key, value in stats.items():
        print(f"  {key}: {value}")
    if error_samples:
        print("  오류 샘플(최대 10건):")
        for line in error_samples:
            print(f"    - {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
