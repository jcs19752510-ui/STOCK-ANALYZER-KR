#!/usr/bin/env python
"""모의 KIS Open API 서버 (DEC-052) — 앱키 없이 개인 로컬 모드 화면·연동을 시험하는 개발 도구.

실제 증권사 서버가 아니다. 한국투자증권 시세 조회 엔드포인트(토큰·분봉(당일/과거)·호가·체결·투자자별 순매수·관심종목 멀티종목 시세·일자별 일봉)와 같은 모양의 응답을
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
import os
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


MULTI_PRICE_MAX = 30
DAILY_PRICE_ROWS = 30


def _is_weekday(d) -> bool:
    return d.weekday() < 5


def daily_price_rows(code: str, now: datetime) -> list[dict]:
    """주식현재가 일자별 모의 행(최근이 앞, 평일만, 최대 30개). 종목·날짜로 결정되는 랜덤워크라 같은 날짜는 항상 같은 값이다.

    - 오늘이 평일이고 장 시작(09:00) 이후이면 오늘 행(진행 중인 봉)을 맨 앞에 둔다.
    - 종목코드 끝 글자가 `9`이면 수정주가가 어긋난 것처럼 종가를 2배로 돌려준다(교차검증 불일치 시험용).
    - 종목코드가 `000000`이면 빈 목록(상장 직후·거래정지 시험용).
    """
    if code == "000000":
        return []
    rows: list[dict] = []
    day = now.date()
    if not (_is_weekday(day) and now.hour >= 9):
        day -= timedelta(days=1)
    while len(rows) < DAILY_PRICE_ROWS:
        if _is_weekday(day):
            ymd = day.strftime("%Y%m%d")
            rng = _rng(code, ymd, "daily")
            close = _base_price(code) * (1 + rng.uniform(-0.03, 0.03))
            close = max(100, round(close / 10) * 10)
            openp = max(100, round(close * (1 + rng.uniform(-0.01, 0.01)) / 10) * 10)
            high = max(close, openp) + 10 * rng.randint(0, 3)
            low = max(10, min(close, openp) - 10 * rng.randint(0, 3))
            if code.endswith("9"):
                close, openp, high, low = close * 2, openp * 2, high * 2, low * 2
            rows.append({
                "stck_bsop_date": ymd, "stck_oprc": str(int(openp)), "stck_hgpr": str(int(high)),
                "stck_lwpr": str(int(low)), "stck_clpr": str(int(close)),
                "acml_vol": str(rng.randint(10_000, 3_000_000)), "prdy_vrss": "0", "prdy_vrss_sign": "3",
                "prdy_ctrt": "0.00", "acml_tr_pbmn": "0", "flng_cls_code": "00", "prtt_rate": "0.00", "mod_yn": "N",
            })
        day -= timedelta(days=1)
    return rows


def multi_price_rows(codes: list[str], now: datetime) -> list[dict]:
    """관심종목 멀티종목 시세 모의 행(필드명은 공식 샘플 COLUMN_MAPPING 기준). 종목·분 단위로 결정되는 값.

    종목코드 `000000`은 값이 빈 행(현재가 없음)을 돌려준다 — 정규화의 '빈 값 버림' 시험용.
    """
    rows = []
    for code in codes:
        if code == "000000":
            rows.append({"inter_shrn_iscd": code, "inter2_prpr": "", "inter2_prdy_vrss": "", "prdy_vrss_sign": "3",
                         "prdy_ctrt": "", "acml_vol": "", "inter2_oprc": "", "inter2_hgpr": "", "inter2_lwpr": ""})
            continue
        prev_close = _base_price(code)
        rng = _rng(code, now.strftime("%Y%m%d%H%M"), "multi")
        step = _tick_size(prev_close)
        price = max(step, round(prev_close * (1 + rng.uniform(-0.05, 0.05)) / step) * step)
        opn = max(step, round(prev_close * (1 + rng.uniform(-0.01, 0.01)) / step) * step)
        high = max(price, opn) + step * rng.randint(0, 3)
        low = max(step, min(price, opn) - step * rng.randint(0, 3))
        diff = price - prev_close
        rows.append({
            "kospi_kosdaq_cls_name": "코스피", "mrkt_trtm_cls_name": "", "hour_cls_code": "0",
            "inter_shrn_iscd": code, "inter_kor_isnm": f"모의{code}",
            "inter2_prpr": str(int(price)), "inter2_prdy_vrss": str(abs(int(diff))),
            "prdy_vrss_sign": "2" if diff > 0 else "5" if diff < 0 else "3",
            "prdy_ctrt": f"{abs(diff) / prev_close * 100:.2f}", "acml_vol": str(rng.randint(1_000, 5_000_000)),
            "inter2_oprc": str(int(opn)), "inter2_hgpr": str(int(high)), "inter2_lwpr": str(int(low)),
            "inter2_prdy_clpr": str(prev_close),
        })
    return rows


PSEARCH_CALLS: dict[str, int] = {}
PSEARCH_CHANGE_EVERY = 3  # seq 0: 호출 3번마다 결과 종목이 하나씩 바뀐다(시간과 무관해 시험이 결정적이다)


def psearch_result(q: dict, ok: dict) -> dict:
    """HTS 조건검색 결과 모의. seq 0: 호출마다 조금씩 바뀌는 결과, seq 1: 0건(증권사는 오류를 돌려준다), seq 2: 100건(한도)."""
    seq = q.get("seq", "")
    if not q.get("user_id") or seq == "":
        return {"rt_cd": "1", "msg_cd": "MOCK400", "msg1": "user_id와 seq가 필요합니다."}
    n = PSEARCH_CALLS[seq] = PSEARCH_CALLS.get(seq, 0) + 1
    if seq == "1":
        return {"rt_cd": "1", "msg_cd": "MOCK_EMPTY", "msg1": "검색 결과가 없습니다."}
    prefix = os.environ.get("MOCK_PSEARCH_CODE_PREFIX", "")  # 예: "T" → T00001…(종단 시험의 DB 시험 데이터 종목과 맞춘다). 기본은 숫자 6자리

    def fmt(i: int) -> str:
        return f"{prefix}{i:0{6 - len(prefix)}d}"

    if seq == "2":
        codes = [fmt(i) for i in range(1, 101)]
    else:
        step = (n - 1) // PSEARCH_CHANGE_EVERY  # 3번 호출마다 한 종목이 들어오고(편입) 한 종목이 빠진다(이탈)
        codes = [fmt(i) for i in range(1 + step, 6 + step)]
    rows = [{"code": c, "name": f"모의{c}", "price": str(10000 + sum(map(ord, c))), "chgrate": "1.25", "acml_vol": "123456"} for c in codes]
    return {**ok, "output2": rows}


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
        elif url.path.endswith("intstock-multprice"):
            indexes = sorted(
                int(k.rsplit("_", 1)[1]) for k in q if k.startswith("FID_INPUT_ISCD_") and k.rsplit("_", 1)[1].isdigit()
            )
            codes = [q[f"FID_INPUT_ISCD_{i}"] for i in indexes if q[f"FID_INPUT_ISCD_{i}"]]
            if not codes or len(codes) > MULTI_PRICE_MAX or (indexes and indexes[-1] > MULTI_PRICE_MAX):
                self._send(200, {"rt_cd": "1", "msg_cd": "MOCK400", "msg1": "종목은 1~30개까지 조회할 수 있습니다."})
            else:
                self._send(200, {**ok, "output": multi_price_rows(codes, now)})
        elif url.path.endswith("inquire-daily-price"):
            if not code or q.get("FID_PERIOD_DIV_CODE") != "D":
                self._send(200, {"rt_cd": "1", "msg_cd": "MOCK400", "msg1": "종목코드와 기간구분(D)이 필요합니다."})
            else:
                self._send(200, {**ok, "output": daily_price_rows(code, now)})
        elif url.path.endswith("psearch-title"):
            if not q.get("user_id"):
                self._send(200, {"rt_cd": "1", "msg_cd": "MOCK400", "msg1": "user_id가 필요합니다."})
            else:
                self._send(200, {**ok, "output2": [
                    {"user_id": q["user_id"], "seq": "0", "grp_nm": "모의그룹", "condition_nm": "모의 변동 조건"},
                    {"user_id": q["user_id"], "seq": "1", "grp_nm": "모의그룹", "condition_nm": "모의 빈 조건"},
                    {"user_id": q["user_id"], "seq": "2", "grp_nm": "모의그룹", "condition_nm": "모의 100건 조건"},
                ]})
        elif url.path.endswith("psearch-result"):
            self._send(200, psearch_result(q, ok))
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
