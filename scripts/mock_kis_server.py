#!/usr/bin/env python
"""모의 KIS Open API 서버 (DEC-052) — 앱키 없이 개인 로컬 모드 화면·연동을 시험하는 개발 도구.

실제 증권사 서버가 아니다. 한국투자증권 시세 조회 엔드포인트(토큰·분봉(당일/과거)·호가·체결·투자자별 순매수)와 같은 모양의 응답을
종목코드·날짜로 결정되는 가짜 값으로 돌려준다. **실제 시세가 아니므로** 화면 동작 확인용으로만 쓴다.

사용:
    python scripts/mock_kis_server.py --port 9100
    # API 서버 환경변수
    LOCAL_INTRADAY_ENABLED=true KIS_APP_KEY=mock KIS_APP_SECRET=mock \
    KIS_BASE_URL=http://127.0.0.1:9100 KIS_ALLOW_CUSTOM_BASE_URL=true \
    python scripts/run_public_api.py
"""

# ruff: noqa: E501
from __future__ import annotations

import argparse
import hashlib
import json
import random
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

KST = timezone(timedelta(hours=9))
OPEN_MIN, CLOSE_MIN = 9 * 60, 15 * 60 + 30


def _rng(*parts: str) -> random.Random:
    return random.Random(int(hashlib.sha256("|".join(parts).encode()).hexdigest()[:12], 16))


def _base_price(code: str) -> int:
    return 5_000 + int(hashlib.sha256(code.encode()).hexdigest()[:6], 16) % 90_000 // 100 * 100


def _tick_size(p: float) -> int:
    for limit, t in ((2000, 1), (5000, 5), (20000, 10), (50000, 50), (200000, 100), (500000, 500)):
        if p < limit:
            return t
    return 1000


def minute_series(code: str, day: str) -> list[dict]:
    """하루치 1분봉(09:00~15:30), 종목·날짜로 결정되는 랜덤워크."""
    rng = _rng(code, day)
    price = float(_base_price(code))
    out = []
    for m in range(OPEN_MIN, CLOSE_MIN + 1):
        o = price
        price = max(100.0, price * (1 + rng.uniform(-0.002, 0.002)))
        c = price
        h = max(o, c) * (1 + rng.uniform(0, 0.001))
        lo = min(o, c) * (1 - rng.uniform(0, 0.001))
        out.append(
            {
                "stck_bsop_date": day,
                "stck_cntg_hour": f"{m // 60:02d}{m % 60:02d}00",
                "stck_oprc": str(round(o)),
                "stck_hgpr": str(round(h)),
                "stck_lwpr": str(round(lo)),
                "stck_prpr": str(round(c)),
                "cntg_vol": str(rng.randint(100, 5000)),
                "acml_tr_pbmn": "0",
            }
        )
    return out


def _now_hhmmss(now: datetime) -> str:
    return now.strftime("%H%M%S")


def ticks_today(code: str, now: datetime) -> list[dict]:
    """오늘 09:00부터 지금까지 약 7초 간격 체결(최근이 앞)."""
    day = now.strftime("%Y%m%d")
    rng = _rng(code, day, "ticks")
    price = float(_base_price(code))
    prev_close = price
    rows = []
    t = datetime(now.year, now.month, now.day, 9, 0, 0, tzinfo=KST)
    end = min(now, datetime(now.year, now.month, now.day, 15, 30, 0, tzinfo=KST))
    while t <= end:
        step = _tick_size(price)
        price = max(step, round((price + rng.choice((-2, -1, 0, 1, 2)) * step) / step) * step)
        diff = price - prev_close
        rows.append(
            {
                "stck_cntg_hour": t.strftime("%H%M%S"),
                "stck_prpr": str(int(price)),
                "prdy_vrss": str(abs(int(diff))),
                "prdy_vrss_sign": "2" if diff > 0 else "5" if diff < 0 else "3",
                "cntg_vol": str(rng.randint(1, 300)),
                "tday_rltv": f"{90 + rng.random() * 20:.2f}",
                "prdy_ctrt": f"{diff / prev_close * 100:.2f}",
            }
        )
        t += timedelta(seconds=7)
    rows.reverse()
    return rows


def orderbook(code: str, now: datetime) -> dict:
    rows = ticks_today(code, now)
    last = int(rows[0]["stck_prpr"]) if rows else _base_price(code)
    step = _tick_size(last)
    rng = _rng(code, now.strftime("%Y%m%d%H%M%S"))
    o1: dict[str, str] = {"aspr_acpt_hour": _now_hhmmss(now)}
    ta = tb = 0
    for i in range(1, 11):
        aq, bq = rng.randint(50, 3000), rng.randint(50, 3000)
        o1[f"askp{i}"], o1[f"askp_rsqn{i}"] = str(last + step * i), str(aq)
        o1[f"bidp{i}"], o1[f"bidp_rsqn{i}"] = str(max(step, last - step * (i - 1))), str(bq)
        ta, tb = ta + aq, tb + bq
    o1["total_askp_rsqn"], o1["total_bidp_rsqn"] = str(ta), str(tb)
    return {"output1": o1, "output2": {"antc_cnpr": "0"}}


def investor_rows(code: str, now: datetime) -> list[dict]:
    """최근 30거래일(평일) 투자자별 순매수(최근이 앞). 장중에는 당일 행이 비어 있다(미확정) — 빈 값 처리 시험용."""
    rows: list[dict] = []
    day = now.date()
    if now.weekday() < 5 and now.hour < 18:
        rows.append({"stck_bsop_date": day.strftime("%Y%m%d"), "prsn_ntby_qty": "", "frgn_ntby_qty": "",
                     "orgn_ntby_qty": "", "prsn_ntby_tr_pbmn": "", "frgn_ntby_tr_pbmn": "", "orgn_ntby_tr_pbmn": ""})
        day -= timedelta(days=1)
    while len(rows) < 30:
        if day.weekday() < 5:
            rng = _rng(code, day.strftime("%Y%m%d"), "investor")
            price = _base_price(code)
            p_q, f_q = rng.randint(-50_000, 50_000), rng.randint(-50_000, 50_000)
            o_q = -(p_q + f_q)  # 합계 0이 되도록(모의 데이터)
            rows.append({
                "stck_bsop_date": day.strftime("%Y%m%d"),
                "prsn_ntby_qty": str(p_q), "frgn_ntby_qty": str(f_q), "orgn_ntby_qty": str(o_q),
                "prsn_ntby_tr_pbmn": str(round(p_q * price / 1_000_000)),
                "frgn_ntby_tr_pbmn": str(round(f_q * price / 1_000_000)),
                "orgn_ntby_tr_pbmn": str(round(o_q * price / 1_000_000)),
            })
        day -= timedelta(days=1)
    return rows


class Handler(BaseHTTPRequestHandler):
    server_version = "MockKIS/1.0"
    fixed_now: datetime | None = None

    def _now(self) -> datetime:
        return self.fixed_now or datetime.now(KST)

    def _send(self, status: int, body: dict) -> None:
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        if urlparse(self.path).path == "/oauth2/tokenP" and body.get("grant_type") == "client_credentials":
            self._send(200, {"access_token": "mock-token", "token_type": "Bearer", "expires_in": 86400})
        elif urlparse(self.path).path == "/oauth2/Approval" and body.get("grant_type") == "client_credentials":
            # 실시간(웹소켓) 접속키 — scripts/mock_kis_ws_server.py의 기본 키와 같다(DEC-084)
            self._send(200, {"approval_key": "mock-approval"})
        else:
            self._send(404, {"rt_cd": "1", "msg_cd": "MOCK404", "msg1": "not found"})

    def do_GET(self) -> None:  # noqa: N802
        if self.headers.get("authorization") != "Bearer mock-token":
            self._send(401, {"rt_cd": "1", "msg_cd": "EGW00121", "msg1": "유효하지 않은 token"})
            return
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query, keep_blank_values=True).items()}
        code = q.get("FID_INPUT_ISCD", "")
        ok = {"rt_cd": "0", "msg_cd": "MCA00000", "msg1": "정상처리 되었습니다."}
        now = self._now()
        hour = q.get("FID_INPUT_HOUR_1", "153000")
        if url.path.endswith("inquire-time-itemchartprice"):
            today = now.strftime("%Y%m%d")
            if now.weekday() >= 5 or now.hour < 9:  # 주말·장 시작 전: 당일 분봉 없음
                rows: list[dict] = []
            else:
                rows = [r for r in minute_series(code, today) if r["stck_cntg_hour"] <= min(hour, _now_hhmmss(now))]
            self._send(200, {**ok, "output1": {"stck_prpr": "0"}, "output2": list(reversed(rows))[:30]})
        elif url.path.endswith("inquire-time-dailychartprice"):
            day = q.get("FID_INPUT_DATE_1", now.strftime("%Y%m%d"))
            rows = [r for r in minute_series(code, day) if r["stck_cntg_hour"] <= hour]
            self._send(200, {**ok, "output1": {"stck_prpr": "0"}, "output2": list(reversed(rows))[:120]})
        elif url.path.endswith("inquire-asking-price-exp-ccn"):
            self._send(200, {**ok, **orderbook(code, now)})
        elif url.path.endswith("inquire-ccnl"):
            self._send(200, {**ok, "output": ticks_today(code, now)[:30]})
        elif url.path.endswith("inquire-investor"):
            self._send(200, {**ok, "output": investor_rows(code, now)})
        elif url.path.endswith("inquire-time-itemconclusion"):
            rows = [r for r in ticks_today(code, now) if r["stck_cntg_hour"] <= hour]
            self._send(200, {**ok, "output1": {}, "output2": rows[:30]})
        else:
            self._send(404, {"rt_cd": "1", "msg_cd": "MOCK404", "msg1": "not found"})

    def log_message(self, *args) -> None:  # 조용히
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--port", type=int, default=9100)
    parser.add_argument("--now", help="시각 고정(예: 2026-10-02T11:00, KST). 생략하면 현재 시각")
    args = parser.parse_args()
    if args.now:
        Handler.fixed_now = datetime.fromisoformat(args.now).replace(tzinfo=KST)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"모의 KIS 서버 http://127.0.0.1:{args.port} (실제 시세 아님)", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
