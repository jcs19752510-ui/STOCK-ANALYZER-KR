#!/usr/bin/env python
"""휴장일/영업일 캘린더 갱신 CLI (REQ-012).

03-system-design.md §3-3: "휴장일 목록은 애플리케이션 코드에 넣지 않는다.
연 1회 이상 운영자가 `scripts/load_calendar.py <year>.yaml` 형태로 KRX 공식
발표 기준 캘린더 데이터 파일을 DB에 upsert하는 절차로 관리한다."

사용법:
    python scripts/load_calendar.py data/calendar/2026.yaml
    python scripts/load_calendar.py data/calendar/2026.yaml --dry-run

DB 접속 정보는 환경변수 BATCH_DATABASE_URL로 받는다(batch_worker 역할 —
reference 스키마 쓰기 권한, §3-1). 이 스크립트는 로그인/관리자 UI가 없는
MVP 특성상 서버 접근 권한이 있는 운영자가 직접 실행하는 것을 전제로 한다.

명시적 실패 원칙: YAML 형식 오류, DB 연결 실패, upsert 실패 등 어떤 단계에서든
문제가 있으면 조용히 넘어가지 않고 0이 아닌 종료 코드와 에러 메시지를 남긴다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import yaml  # noqa: E402
from sqlalchemy import create_engine, func  # noqa: E402
from sqlalchemy.dialects.postgresql import insert as pg_insert  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from shared.calendar_service.calendar_file import (  # noqa: E402
    CalendarFileError,
    CalendarRowInput,
    build_calendar_rows,
)
from shared.db_models.reference import MarketCalendar  # noqa: E402


class LoadCalendarError(RuntimeError):
    pass


def load_yaml_file(path: Path) -> dict:
    if not path.exists():
        raise LoadCalendarError(f"파일을 찾을 수 없습니다: {path}")
    with path.open("r", encoding="utf-8") as f:
        try:
            data = yaml.safe_load(f)
        except yaml.YAMLError as exc:
            raise LoadCalendarError(f"YAML 파싱 실패: {exc}") from exc
    if not isinstance(data, dict):
        raise LoadCalendarError("YAML 최상위는 매핑(딕셔너리)이어야 합니다.")
    return data


def upsert_rows(session: Session, rows: list[CalendarRowInput]) -> int:
    """reference.market_calendar에 upsert. (trade_date, market) 충돌 시 갱신."""
    affected = 0
    for row in rows:
        stmt = pg_insert(MarketCalendar).values(
            trade_date=row.trade_date,
            market=row.market,
            is_trading_day=row.is_trading_day,
            session_close_at=row.session_close_at,
            holiday_name=row.holiday_name,
            source=row.source,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[MarketCalendar.trade_date, MarketCalendar.market],
            set_={
                "is_trading_day": stmt.excluded.is_trading_day,
                "session_close_at": stmt.excluded.session_close_at,
                "holiday_name": stmt.excluded.holiday_name,
                "source": stmt.excluded.source,
                # DEF-004: 내용이 갱신될 때 updated_at도 함께 갱신돼야 하는데
                # 빠져 있어 최초 삽입 시각에 고정되는 결함이 있었다(unit-01-test.md
                # v3 TC-069). 갱신 시각은 DB 서버 기준(func.now())으로 통일한다.
                "updated_at": func.now(),
            },
        )
        session.execute(stmt)
        affected += 1
    return affected


def summarize(rows: list[CalendarRowInput]) -> str:
    by_market: dict[str, dict[str, int]] = {}
    for row in rows:
        counter = by_market.setdefault(row.market, {"trading": 0, "holiday": 0})
        counter["trading" if row.is_trading_day else "holiday"] += 1
    lines = [f"총 {len(rows)}건"]
    for market, counter in sorted(by_market.items()):
        lines.append(f"  {market}: 거래일 {counter['trading']}일, 휴장일 {counter['holiday']}일")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    # Windows 콘솔 기본 코드페이지(cp949 등)에서 한글 로그가 깨지는 것을 방지.
    # 리눅스/CI 환경은 이미 UTF-8이라 영향 없음.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("yaml_path", type=Path, help="연간 캘린더 YAML 파일 경로")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="DB에 쓰지 않고 파싱 결과 요약만 출력한다",
    )
    args = parser.parse_args(argv)

    try:
        raw = load_yaml_file(args.yaml_path)
        rows = build_calendar_rows(raw)
    except (LoadCalendarError, CalendarFileError) as exc:
        print(f"[실패] {exc}", file=sys.stderr)
        return 1

    print(summarize(rows))

    if args.dry_run:
        print("(--dry-run) DB에 반영하지 않았습니다.")
        return 0

    import os

    database_url = os.environ.get("BATCH_DATABASE_URL")
    if not database_url:
        print(
            "[실패] 환경변수 BATCH_DATABASE_URL이 설정되지 않았습니다. "
            "(reference 스키마 쓰기 권한이 있는 batch_worker 계정 접속 문자열 필요)",
            file=sys.stderr,
        )
        return 1

    try:
        engine = create_engine(database_url)
        with Session(engine) as session:
            affected = upsert_rows(session, rows)
            session.commit()
    except Exception as exc:  # DB 계층 예외는 원인 그대로 알리고 종료 코드로 실패를 표시
        print(f"[실패] DB 반영 중 오류: {exc}", file=sys.stderr)
        return 1

    print(f"[완료] {affected}건을 reference.market_calendar에 반영했습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
