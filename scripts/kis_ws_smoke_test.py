#!/usr/bin/env python
# ruff: noqa: E501
"""한국투자증권 실시간(웹소켓) 스모크 테스트 (DEC-084) — **장중에 내 PC에서 실제 앱키로 한 번 실행**해 실시간 연동을 확인한다.

이 저장소의 자동 테스트는 모의 증권사 서버만 쓰고, 개발 환경에서는 증권사 서버로 나갈 수 없어 실제 응답으로는 검증하지 못했다.
이 스크립트가 그 마지막 확인이다. 앱키·시크릿·접속키는 어떤 출력에도 나오지 않는다(출력 직전에 가린다).

하는 일: 접속키 발급(POST /oauth2/Approval) → ws://ops.koreainvestment.com:21000 접속 → 종목의 체결(H0UNCNT0)·호가(H0UNASP0) 구독
→ N초 수신하며 해석·값 검증 → 요약.

사용(프로젝트 루트에서):
    py -3.12 scripts\\kis_ws_smoke_test.py                       # 삼성전자(005930), 20초
    py -3.12 scripts\\kis_ws_smoke_test.py --code 000660 --seconds 30
환경변수 또는 `.env`: KIS_APP_KEY, KIS_APP_SECRET (모의 서버 시험 때만 KIS_BASE_URL·KIS_WS_URL·KIS_ALLOW_CUSTOM_BASE_URL=true)
종료코드: 0 정상 / 1 실패(설정·접속·값 이상) / 2 확인필요(장 시간 밖·휴장일 등으로 체결을 못 받음)
"""

from __future__ import annotations

import argparse
import asyncio
import os
import statistics
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import httpx  # noqa: E402
from websockets.asyncio.client import connect as ws_connect  # noqa: E402
from websockets.exceptions import ConnectionClosed  # noqa: E402

from services.public_api.intraday import config as cfg  # noqa: E402
from services.public_api.realtime import protocol as proto  # noqa: E402
from services.public_api.realtime.connection import APPROVAL_PATH  # noqa: E402

KST = timezone(timedelta(hours=9))
MAX_SECONDS = 120.0
DEFAULT_SECONDS = 20.0
MARKET_OPEN_HHMM = (8, 0)  # 통합시세(KRX + NXT) 08:00~20:00
MARKET_CLOSE_HHMM = (20, 0)
CLOCK_WARN_SECONDS = 60.0  # 체결 시각과 PC 시계 차이가 이보다 크면 PC 시계를 확인


def _load_dotenv() -> None:
    env_file = REPO_ROOT / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def mask(text: str, secrets: set[str]) -> str:
    """출력 직전에 비밀값(앱키·시크릿·접속키)을 가린다. 긴 값부터 바꿔 부분 겹침을 막는다."""
    for s in sorted((s for s in secrets if s), key=len, reverse=True):
        text = text.replace(s, "***")
    return text


def short(text: object, limit: int = 80) -> str:
    return " ".join(str(text).split())[:limit]


def in_market_hours(now: datetime) -> bool:
    """한국시간 평일 08:00~20:00인지. 공휴일은 알 수 없으므로(달력 없음) 체결이 없을 때 안내 문구로 덧붙인다."""
    now = now.astimezone(KST)
    if now.weekday() >= 5:
        return False
    hm = (now.hour, now.minute)
    return MARKET_OPEN_HHMM <= hm < MARKET_CLOSE_HHMM


def seconds_of_day(hhmmss: str) -> int:
    h, m, s = (int(x) for x in hhmmss.split(":"))
    return h * 3600 + m * 60 + s


def clock_diff_seconds(now: datetime, trade_time: str) -> float:
    """PC 시계(한국시간) − 체결 시각. 자정 경계는 ±12시간 범위로 접는다. 양수면 PC 시계가 더 늦다(정상은 0~수 초)."""
    n = now.astimezone(KST)
    now_s = n.hour * 3600 + n.minute * 60 + n.second + n.microsecond / 1e6
    d = now_s - seconds_of_day(trade_time)
    return (d + 43200) % 86400 - 43200


def check_book(book: Any) -> list[str]:
    """호가 한 건의 값 검증. 문제 설명 목록(없으면 정상)."""
    problems: list[str] = []
    asks = [lv.price for lv in book.asks]
    bids = [lv.price for lv in book.bids]
    if any(a > b for a, b in zip(asks, asks[1:], strict=False)):
        problems.append("매도호가가 1단계→10단계로 오름차순이 아님")
    if any(a < b for a, b in zip(bids, bids[1:], strict=False)):
        problems.append("매수호가가 1단계→10단계로 내림차순이 아님")
    if book.total_ask_quantity < 0 or book.total_bid_quantity < 0:
        problems.append("총잔량이 음수")
    return problems


@dataclass
class Stats:
    trades: int = 0
    books: int = 0
    pings: int = 0
    subscribe_ok: int = 0
    first_trade_after: float | None = None
    clock_diffs: list[float] = field(default_factory=list)
    last_trade: Any = None
    last_book: Any = None
    last_acml: int | None = None
    acml_missing: int = 0
    undecodable_trades: int = 0
    undecodable_books: int = 0
    problems: list[str] = field(default_factory=list)  # 값 검증 실패(중복 제거)
    subscribe_errors: list[str] = field(default_factory=list)
    invalid_approval: bool = False
    closed: str | None = None

    def problem(self, text: str) -> None:
        if text not in self.problems:
            self.problems.append(text)


async def fetch_approval(
    settings: cfg.IntradaySettings, http_factory: Callable[[], httpx.AsyncClient]
) -> tuple[str | None, str]:
    """접속키 발급 — `KisWsManager._approval_key`와 같은 요청(필드 이름 포함). 실패 시 (None, 사유)."""
    try:
        async with http_factory() as http:
            resp = await http.post(
                settings.base_url + APPROVAL_PATH,
                json={"grant_type": "client_credentials", "appkey": settings.app_key, "secretkey": settings.app_secret},
                headers={"content-type": "application/json; charset=utf-8"},
            )
    except httpx.HTTPError as exc:
        return None, f"증권사 서버에 연결하지 못했습니다({type(exc).__name__}). 인터넷·방화벽·해외 IP 여부를 확인하세요."
    try:
        body = resp.json()
    except ValueError:
        return None, f"증권사 응답을 해석할 수 없습니다(HTTP {resp.status_code})."
    key = body.get("approval_key") if isinstance(body, dict) else None
    if resp.status_code == 200 and isinstance(key, str) and key:
        return key, ""
    detail = ""
    if isinstance(body, dict):
        code = body.get("error_code") or body.get("msg_cd") or ""
        msg = body.get("error_description") or body.get("msg1") or ""
        detail = short(f"{code} {msg}")
    return None, f"HTTP {resp.status_code}" + (f" — {detail}" if detail else "") + " (앱키·시크릿을 확인하세요)"


def _fmt(n: float | int | None) -> str:
    return "-" if n is None else f"{n:,.0f}"


async def run_check(
    settings: cfg.IntradaySettings,
    code: str,
    seconds: float,
    *,
    now_fn: Callable[[], datetime] | None = None,
    http_factory: Callable[[], httpx.AsyncClient] | None = None,
    connect: Callable[..., Any] = ws_connect,
    out: Callable[[str], None] = print,
) -> int:
    """점검을 실행하고 종료 코드(0/1/2)를 돌려준다. 모든 출력은 비밀값을 가려서 나간다."""
    now_fn = now_fn or (lambda: datetime.now(KST))
    http_factory = http_factory or (lambda: httpx.AsyncClient(timeout=10.0))
    secrets: set[str] = {s for s in (settings.app_key, settings.app_secret) if s}

    def say(text: str) -> None:
        out(mask(text, secrets))

    start = now_fn()
    market = in_market_hours(start)
    say(f"종목 {code}, 현재 {start.astimezone(KST):%Y-%m-%d %H:%M:%S} KST, {seconds:g}초 수신 "
        f"(통합시세 {MARKET_OPEN_HHMM[0]:02d}:00~{MARKET_CLOSE_HHMM[0]:02d}:00 평일: 지금은 {'장 시간' if market else '장 시간 밖'})")
    if settings.ws_url != cfg.KIS_REAL_WS_URL:
        say("※ 증권사 실전 주소가 아닌 사용자 지정 주소(모의 서버 시험용)에 접속합니다.")

    # 1) 접속키
    approval, why = await fetch_approval(settings, http_factory)
    if approval is None:
        say(f"[실패] 접속키 발급: {why}")
        return 1
    secrets.add(approval)
    say("[OK] 접속키 발급")

    # 2) 접속·구독·수신
    st = Stats()
    try:
        async with connect(settings.ws_url, ping_interval=None, open_timeout=10, max_size=1 << 20) as ws:
            say("[OK] 웹소켓 접속")
            for tr in (proto.TR_TRADE, proto.TR_BOOK):
                await ws.send(proto.build_subscribe(approval, tr, code))
            t0 = time.monotonic()
            deadline = t0 + seconds
            try:
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                    except TimeoutError:
                        break
                    frame = proto.parse_message(raw)
                    if frame is None:
                        continue
                    if isinstance(frame, proto.ControlFrame):
                        if frame.kind == "pingpong":
                            st.pings += 1
                            await ws.pong(raw)
                        elif frame.kind == "subscribe_ok":
                            st.subscribe_ok += 1
                        elif frame.kind == "subscribe_error":
                            st.subscribe_errors.append(f"{frame.tr_id or '-'} {frame.msg_cd or '-'}: {frame.msg or ''}".strip())
                            if frame.msg_cd in ("OPSP0011",):
                                st.invalid_approval = True
                        continue
                    _consume(frame, code, st, now_fn, t0)
            except ConnectionClosed as exc:
                st.closed = f"연결이 닫혔습니다({type(exc).__name__})"
    except Exception as exc:  # noqa: BLE001 — 접속 실패 사유는 종류와 짧은 설명만(비밀값은 mask가 가린다)
        say(f"[실패] 웹소켓 접속: {type(exc).__name__}: {short(exc, 60)} (주소·인터넷·해외 IP 여부 확인)")
        return 1

    return _report(say, st, code, seconds, market, now_fn())


def _consume(frame: proto.DataFrame, code: str, st: Stats, now_fn: Callable[[], datetime], t0: float) -> None:
    for rec in frame.records:
        if frame.tr_id == proto.TR_TRADE:
            trade = proto.parse_trade(rec)
            if trade is None:
                st.undecodable_trades += 1
                continue
            if trade.code != code:
                continue
            st.trades += 1
            if st.first_trade_after is None:
                st.first_trade_after = time.monotonic() - t0
            st.clock_diffs.append(clock_diff_seconds(now_fn(), trade.time))
            if trade.acml_volume is None:
                st.acml_missing += 1
            else:
                if st.last_acml is not None and trade.acml_volume < st.last_acml:
                    st.problem(f"누적 거래량이 줄어듦({st.last_acml:,} → {trade.acml_volume:,})")
                st.last_acml = trade.acml_volume
            st.last_trade = trade
        elif frame.tr_id == proto.TR_BOOK:
            book = proto.parse_book(rec)
            if book is None:
                st.undecodable_books += 1
                continue
            if book.stock_code != code:
                continue
            st.books += 1
            for p in check_book(book):
                st.problem(p)
            st.last_book = book


def _report(say: Callable[[str], None], st: Stats, code: str, seconds: float, market: bool, now: datetime) -> int:
    failures: list[str] = []
    confirms: list[str] = []

    # 구독 결과
    if st.invalid_approval:
        failures.append("접속키 오류: 증권사가 접속키를 인정하지 않았습니다(OPSP0011). 잠시 뒤 다시 실행하거나 앱키·시크릿을 확인하세요.")
    for err in st.subscribe_errors:
        if "OPSP0011" not in err:
            failures.append(f"구독 오류: {short(err, 100)}")
    if st.closed and st.subscribe_ok == 0 and st.trades == 0 and st.books == 0:
        failures.append(f"{st.closed} — 아무 데이터도 받기 전에 끊겼습니다.")
    elif st.closed:
        failures.append(f"{st.closed} — 수신 도중 끊겼습니다.")
    say(f"[{'OK' if st.subscribe_ok >= 2 else '확인필요'}] 구독 응답 {st.subscribe_ok}/2"
        + ("" if st.subscribe_ok >= 2 else " (장 시간 밖이면 응답이 없을 수 있습니다)"))

    # 수신 요약
    say(f"수신 요약: 체결 {st.trades}건, 호가 {st.books}건, PINGPONG {st.pings}회 ({seconds:g}초)")
    if st.first_trade_after is not None:
        say(f"  첫 체결까지 {st.first_trade_after:.1f}초")
    if st.clock_diffs:
        med = statistics.median(st.clock_diffs)
        say(f"  체결 시각 대비 내 PC 시계 차이: 중앙값 {med:+.1f}초 (최소 {min(st.clock_diffs):+.1f} ~ 최대 {max(st.clock_diffs):+.1f})"
            " — 양수면 PC 시계가 더 늦음, 정상은 0~수 초")
        if abs(med) > CLOCK_WARN_SECONDS:
            confirms.append(f"PC 시계와 체결 시각이 {abs(med):.0f}초 이상 어긋납니다. Windows 시간 동기화를 확인하세요.")
    t = st.last_trade
    if t is not None:
        say(f"  현재가 예시: {t.price:,.0f}원 (체결 {t.time}, 체결량 {t.volume:,}, 누적 {_fmt(t.acml_volume)})")
    b = st.last_book
    if b is not None and b.asks and b.bids:
        say(f"  호가 1단계 예시: 매도 {b.asks[0].price:,.0f} × {b.asks[0].quantity:,} / 매수 {b.bids[0].price:,.0f} × {b.bids[0].quantity:,}"
            f", 총잔량 {b.total_ask_quantity:,}/{b.total_bid_quantity:,}, 단계 {len(b.asks)}/{len(b.bids)}")

    # 값 검증
    if st.undecodable_trades:
        failures.append(f"해석하지 못한 체결 {st.undecodable_trades}건(종목코드·시각·현재가·체결량 중 이상한 값)")
    if st.undecodable_books:
        failures.append(f"해석하지 못한 호가 {st.undecodable_books}건(종목코드 이상)")
    for p in st.problems:
        failures.append(f"값 이상: {p}")
    if st.trades:
        if st.acml_missing:
            confirms.append(f"누적 거래량이 비어 있는 체결 {st.acml_missing}건(단조 증가 검증 일부 생략)")
        if not failures:
            say(f"[OK] 값 검증: 현재가>0, 시각 형식, 호가 10단계 순서, 총잔량≥0, 누적 거래량 증가 — 체결 {st.trades}건·호가 {st.books}건 이상 없음")
        if st.books == 0:
            confirms.append("체결은 왔는데 호가가 오지 않았습니다. 다시 실행해 보세요.")

    # 체결이 없을 때
    if st.trades == 0 and not failures:
        if not market:
            confirms.append("지금은 통합시세 장 시간(한국시간 평일 08:00~20:00) 밖이라 체결이 없는 것이 정상입니다. 장중에 다시 실행하세요.")
        elif st.subscribe_ok >= 2 or st.books or st.pings:
            confirms.append(f"장 시간인데 {seconds:g}초 동안 체결이 없었습니다. 휴장일이거나 거래가 드문 종목일 수 있습니다. 종목을 바꾸거나 --seconds를 늘려 다시 실행하세요.")
        else:
            failures.append("장 시간인데 구독 응답·체결·호가·PINGPONG 중 아무것도 받지 못했습니다. 증권사 서버 상태·앱키 권한을 확인하세요.")

    for f in failures:
        say(f"[실패] {f}")
    for c in confirms:
        say(f"[확인필요] {c}")
    if failures:
        say("→ 실패 줄을 그대로(앱키 제외) 알려 주세요. 이 도구는 앱키·접속키를 출력하지 않습니다.")
        return 1
    if confirms:
        say("완료(확인필요 있음).")
        return 2
    say("완료. 실시간 체결·호가 연동이 정상입니다.")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="한국투자증권 실시간(웹소켓) 연동 확인 — 장중에 실행하세요.")
    ap.add_argument("--code", default="005930", help="종목코드 6자리(기본 005930 삼성전자)")
    ap.add_argument("--seconds", type=float, default=DEFAULT_SECONDS, help=f"수신 시간(초, 기본 {DEFAULT_SECONDS:g}, 최대 {MAX_SECONDS:g})")
    return ap


def main(argv: list[str] | None = None, env: dict[str, str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    try:
        args = _build_parser().parse_args(argv)
    except SystemExit as exc:  # argparse의 오류 종료 코드 2는 "확인필요"와 겹치므로 1로 바꾼다
        return 0 if exc.code == 0 else 1
    if not (len(args.code) == 6 and args.code.isdigit()):
        print("[설정 오류] --code는 숫자 6자리 종목코드여야 합니다(예: 005930).")
        return 1
    if not (0 < args.seconds <= MAX_SECONDS):
        print(f"[설정 오류] --seconds는 0보다 크고 {MAX_SECONDS:g} 이하여야 합니다.")
        return 1
    if env is None:
        _load_dotenv()
        env = dict(os.environ)
    env = dict(env)
    env[cfg.ENABLED_ENV] = "true"  # 이 스크립트는 연결을 직접 만든다
    try:
        settings = cfg.get_settings(env)
    except cfg.IntradayConfigError as exc:
        print(f"[설정 오류] {exc}")
        return 1
    if not settings.configured:
        print("[설정 오류] KIS_APP_KEY / KIS_APP_SECRET 이 설정되지 않았습니다(.env 확인).")
        return 1
    return asyncio.run(run_check(settings, args.code, args.seconds))


if __name__ == "__main__":
    raise SystemExit(main())
