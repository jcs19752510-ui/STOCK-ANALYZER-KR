#!/usr/bin/env python
# ruff: noqa: E501
"""한국투자증권 일봉(주식현재가 일자별) 연동 확인 도구 (DEC-090) — **내 PC에서 실제 앱키로 실행**한다.

목적: 장중 재계산이 발행 일봉이 뒤처진 날 증권사 일봉으로 빠진 날을 채우는데(계약서 §7), 그 전제를 실제 응답으로 확인한다.
  ① 일봉이 오는지(행 수·최신 날짜·응답 필드 이름) ② 장중에 오늘 진행 봉이 맨 앞에 끼는지 ③ **발행 일봉(DB)과 같은 날짜의 종가가 같은지**(수정주가 기준·종목 일치)
  ④ 호출 지연·한도 오류. ③이 어긋나면 사이트는 그 종목을 결과에서 빼므로(숨기지 않고 meta에 표시) 일치율이 낮으면 알려 주세요.
이 저장소의 자동 시험은 모의 서버만 쓰며 개발 환경에서는 증권사로 나갈 수 없으므로 실제 응답 확인은 이 도구로만 가능하다.
읽기 전용이다(주문·계좌 호출 없음). 앱키·시크릿·토큰은 어떤 출력에도 나오지 않는다.

사용(프로젝트 루트에서, `.env`에 KIS_APP_KEY·KIS_APP_SECRET, 비교하려면 PUBLIC_API_DATABASE_URL):
    py -3.12 scripts\\kis_daily_price_smoke_test.py                       # 대표 종목 10개 조회, DB가 있으면 발행 일봉과 비교
    py -3.12 scripts\\kis_daily_price_smoke_test.py --code 005930 --code 000660 --no-db --out daily-report.json
종료코드: 0 정상(응답·비교 모두 이상 없음) / 1 실패(설정·인증·응답 이상) / 2 확인필요(비교 불일치·일부 종목 빈 응답·DB 없음)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from services.public_api.intraday import config as cfg  # noqa: E402
from services.public_api.intraday.kis_client import KisClient, KisError  # noqa: E402
from services.public_api.intraday.normalize import (  # noqa: E402
    DAILY_PRICE_FIELDS,
    normalize_daily_price,
)
from services.public_api.live_screen.types import DailyBar  # noqa: E402

KST = timezone(timedelta(hours=9))
DEFAULT_CODES = ["005930", "000660", "035420", "005380", "051910", "035720", "068270", "105560", "000270", "012330"]
MAX_CODES = 30


def _load_dotenv() -> None:
    env_file = REPO_ROOT / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def published_closes(codes: list[str]) -> dict[str, dict[date, Decimal]]:
    """발행 일봉(`public_serving.daily_prices`)의 최근 종가. DB 주소가 없거나 접속하지 못하면 예외."""
    from sqlalchemy import create_engine, text

    url = os.environ.get("PUBLIC_API_DATABASE_URL", "")
    if not url:
        raise RuntimeError("PUBLIC_API_DATABASE_URL이 없습니다.")
    engine = create_engine(url)
    try:
        with engine.connect() as c:
            rows = c.execute(
                text("SELECT stock_code, trade_date, close FROM public_serving.daily_prices WHERE stock_code = ANY(:c) AND trade_date > current_date - 60"),
                {"c": codes},
            )
            out: dict[str, dict[date, Decimal]] = {}
            for code, d, close in rows:
                out.setdefault(code, {})[d] = Decimal(close)
            return out
    finally:
        engine.dispose()


def compare(kis: list[DailyBar], published: dict[date, Decimal]) -> tuple[int, int]:
    """(같은 날짜 수, 그중 종가가 같은 수)."""
    both = [b for b in kis if b.trade_date in published]
    return len(both), sum(1 for b in both if b.close == published[b.trade_date])


def run(client: Any, codes: list[str], *, db_loader: Callable[[list[str]], dict[str, dict[date, Decimal]]] | None, now: datetime | None = None, sleep: Callable[[float], None] = time.sleep) -> tuple[int, dict[str, Any]]:
    now = (now or datetime.now(KST)).astimezone(KST)
    report: dict[str, Any] = {"checked_at": now.isoformat(), "codes": {}, "fields_seen": []}
    pub: dict[str, dict[date, Decimal]] | None = None
    if db_loader is not None:
        try:
            pub = db_loader(codes)
        except Exception as exc:  # noqa: BLE001 — 접속 정보가 메시지에 섞일 수 있어 종류만 보인다
            print(f"[알림] 발행 일봉(DB)을 읽지 못했습니다({type(exc).__name__}) — 비교 없이 응답만 확인합니다.")
    needs_check = pub is None
    failed = 0
    for code in codes:
        t0 = time.perf_counter()
        try:
            body = client.daily_price(code)
        except KisError as exc:
            failed += 1
            print(f"[실패] {code}: {exc.code}")
            report["codes"][code] = {"error": exc.code}
            continue
        ms = (time.perf_counter() - t0) * 1000
        rows = [r for r in (body.get("output") or []) if isinstance(r, dict)] if isinstance(body, dict) else []
        if rows and not report["fields_seen"]:
            report["fields_seen"] = sorted(rows[0].keys())
        bars = normalize_daily_price(rows)
        entry: dict[str, Any] = {"rows": len(rows), "usable": len(bars), "newest": bars[-1].trade_date.isoformat() if bars else None, "ms": round(ms)}
        line = f"{code}: 행 {len(rows)}개(사용 가능 {len(bars)}), 최신 {entry['newest']}, {ms:.0f}ms"
        if bars and bars[-1].trade_date == now.date():
            entry["today_partial"] = True
            line += " — 오늘 진행 봉 포함"
        if not bars:
            needs_check = True
            line += " — 사용할 수 있는 일봉 없음"
        if pub is not None and code in pub and bars:
            n, same = compare(bars, pub[code])
            entry["compared"], entry["same_close"] = n, same
            line += f", 발행 일봉과 비교 {same}/{n}"
            if n == 0 or same != n:
                needs_check = True
        elif pub is not None:
            needs_check = True
            line += " — 발행 일봉 없음(비교 불가)"
        print(line)
        report["codes"][code] = entry
        sleep(0.2)
    missing = [f for f in DAILY_PRICE_FIELDS.values() if report["fields_seen"] and f not in report["fields_seen"]]
    if missing:
        needs_check = True
        print(f"[확인필요] 응답에 기대한 필드가 없습니다: {', '.join(missing)} (정규화가 해당 행을 버립니다)")
    report["fields_missing"] = missing
    code = 1 if failed == len(codes) else 2 if (failed or needs_check) else 0
    print({0: "[정상] 일봉 응답과 발행 일봉 비교가 모두 일치합니다.", 1: "[실패] 모든 종목 조회에 실패했습니다.", 2: "[확인필요] 위 알림을 확인하세요."}[code])
    return code, report


def main(argv: list[str] | None = None, env: dict[str, str] | None = None, client_factory: Callable[[cfg.IntradaySettings], Any] | None = None, db_loader: Callable[[list[str]], Any] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--code", action="append", default=[], help="종목코드(여러 번 지정 가능, 최대 30개). 생략하면 대표 종목 10개")
    parser.add_argument("--no-db", action="store_true", help="발행 일봉(DB)과 비교하지 않는다")
    parser.add_argument("--out", help="결과를 JSON 파일로 저장")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code == 0 else 1
    codes = args.code or DEFAULT_CODES
    if len(codes) > MAX_CODES or any(not (len(c) == 6 and c.isalnum() and c.isascii() and c == c.upper()) for c in codes):
        print("[설정 오류] 종목코드는 6자리 영숫자 대문자, 최대 30개입니다.")
        return 1
    if env is None:
        _load_dotenv()
    try:
        settings = cfg.get_settings(env)
    except cfg.IntradayConfigError as exc:
        print(f"[설정 오류] {exc}")
        return 1
    if not settings.configured:
        print("[설정 오류] KIS_APP_KEY·KIS_APP_SECRET이 없습니다(.env 확인).")
        return 1
    client = client_factory(settings) if client_factory else KisClient(settings)
    code, report = run(client, codes, db_loader=None if args.no_db else (db_loader or published_closes))
    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"결과 저장: {args.out}")
    return code


if __name__ == "__main__":
    sys.exit(main())
