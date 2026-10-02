#!/usr/bin/env python
# ruff: noqa: E501
"""한국투자증권 연동 스모크 테스트 (DEC-052) — **내 PC에서 실제 앱키로 한 번 실행**해 개인 로컬 모드 연동을 확인한다.

이 저장소의 자동 테스트는 증권사 서버에 접속하지 않고(모의 서버·가짜 응답), 개발 환경에서도 증권사 서버로 나갈 수 없어 실제
응답으로는 검증하지 못했다. 이 스크립트가 그 마지막 확인이다. 앱키·시크릿·토큰은 출력하지 않는다.

사용(프로젝트 루트에서):
    py -3.12 scripts/kis_smoke_test.py            # 삼성전자(005930)
    py -3.12 scripts/kis_smoke_test.py 000660     # 다른 종목
환경변수 또는 `.env`: KIS_APP_KEY, KIS_APP_SECRET (선택: KIS_TOKEN_CACHE_PATH)
종료코드: 0 모두 정상 / 1 설정 오류 / 2 하나 이상 실패
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def _load_dotenv() -> None:
    env_file = REPO_ROOT / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    _load_dotenv()
    code = argv[0] if argv else "005930"
    os.environ["LOCAL_INTRADAY_ENABLED"] = "true"  # 이 스크립트는 클라이언트를 직접 호출한다

    from datetime import datetime

    from services.public_api.intraday import config as cfg
    from services.public_api.intraday.kis_client import KST, KisClient, KisError
    from services.public_api.intraday.service import IntradayService

    try:
        settings = cfg.get_settings()
    except cfg.IntradayConfigError as exc:
        print(f"[설정 오류] {exc}")
        return 1
    if not settings.configured:
        print("[설정 오류] KIS_APP_KEY / KIS_APP_SECRET 이 설정되지 않았습니다(.env 확인).")
        return 1

    try:
        client = KisClient(settings)
    except KisError as exc:
        print(f"[설정 오류] {exc.message}")
        return 1
    service = IntradayService(client)
    failures = 0

    def step(name, fn):
        nonlocal failures
        try:
            result = fn()
        except KisError as exc:
            failures += 1
            print(f"[실패] {name}: {exc.code} — {exc.message}")
            return None
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"[실패] {name}: 예상치 못한 오류 {type(exc).__name__}")
            return None
        return result

    print(f"종목 {code}, 현재 {datetime.now(KST):%Y-%m-%d %H:%M} KST (실제 시세 조회 — 값은 증권사 응답 그대로)")

    book = step("호가(10단계)", lambda: service.orderbook(code))
    if book:
        ok = len(book.asks) > 0 or len(book.bids) > 0
        print(f"[{'OK' if ok else '확인필요'}] 호가: 매도 {len(book.asks)}단계, 매수 {len(book.bids)}단계, "
              f"총잔량 {book.total_ask_quantity:,}/{book.total_bid_quantity:,}, 시각 {book.time}")
        if book.asks and book.bids:
            print(f"        최우선 매도 {book.asks[0].price:,.0f} / 매수 {book.bids[0].price:,.0f}")
        if not ok:
            failures += 1
            print("        → 장 시간이 아니면 호가가 비어 있을 수 있습니다. 장중에 다시 실행해 보세요.")

    ticks = step("체결(최근 120건)", lambda: service.ticks(code, 120))
    if ticks:
        print(f"[{'OK' if ticks.ticks else '확인필요'}] 체결: {len(ticks.ticks)}건"
              f"{' (일부만)' if ticks.truncated else ''}"
              + (f", 최근 {ticks.ticks[0].time} 가격 {ticks.ticks[0].price:,.0f}" if ticks.ticks else ""))

    for interval in (1, 5):
        minutes = step(f"분봉({interval}분)", lambda i=interval: service.minutes(code, i, day=None, fallback_day=None))
        if minutes:
            if minutes.bars:
                b0, b1 = minutes.bars[0], minutes.bars[-1]
                print(f"[OK] {interval}분봉: {len(minutes.bars)}개 ({minutes.date}) {b0.time}~{b1.time}, "
                      f"마지막 종가 {b1.close:,.0f}")
            else:
                print(f"[확인필요] {interval}분봉: 오늘 데이터가 없습니다(장 시작 전·휴장일이면 정상). 장중에 다시 실행하세요.")

    print("완료." if failures == 0 else f"실패 {failures}건 — 위 메시지를 확인하세요.")
    return 0 if failures == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
