#!/usr/bin/env python
# ruff: noqa: E501
"""한국투자증권 실제 응답 속도·호출 한도 측정 (DEC-102) — **내 PC에서 실제 앱키로 한 번 실행**한다.

읽기 전용(멀티종목 시세 조회만, 주문·계좌 호출 없음). 앱키·시크릿·토큰은 출력하지 않는다.
측정 내용
  1) 응답 지연: 0.5초 간격으로 순서대로 10회 호출 → 중앙값·95%·최대
  2) 호출 간격 단계(0.125 → 0.1 → 0.08 → 0.06초): 단계마다 동시 4건으로 40회 호출해 RATE_LIMITED·오류 여부와 실제 초당 호출 수 확인.
     오류가 나는 단계에서 멈춘다(한도를 넘겨 계속 두드리지 않는다).
  3) 권장 설정(.env에 넣을 두 줄)과 전 종목(2766개, 93호출) 한 바퀴 예상 시간
사용(프로젝트 루트에서):
    py -3.12 scripts/kis_speed_probe.py
    py -3.12 scripts/kis_speed_probe.py --calls 60 --concurrency 4 --aggressive   # 0.06초까지 권장 허용(한도 확대 계정)
환경변수 또는 `.env`: KIS_APP_KEY, KIS_APP_SECRET
종료코드: 0 완료 / 1 설정 오류 / 2 응답 지연 측정 단계에서 실패
"""

from __future__ import annotations

import argparse
import math
import os
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# 시험에 쓰는 대형주 30종목(읽기 전용 시세 조회용)
CODES = [
    "005930", "000660", "373220", "207940", "005380", "000270", "068270", "105560", "055550", "035420",
    "005490", "051910", "006400", "012330", "028260", "066570", "003550", "096770", "034730", "015760",
    "032830", "086790", "000810", "017670", "316140", "009150", "010130", "011200", "018260", "033780",
]
STEPS = (0.125, 0.1, 0.08, 0.06)
TOTAL_CODES = 2766
BATCHES = math.ceil(TOTAL_CODES / 30)  # 93
STEP_REST = 2.0  # 단계 사이 쉬는 시간(초)
SAFE_STEP_CAP = 0.1  # --aggressive 없이는 이보다 빠르게 권장하지 않는다(기본 한도 20건/초의 50%)


def _load_dotenv() -> None:
    env_file = REPO_ROOT / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def percentile(values: list[float], p: float) -> float:
    s = sorted(values)
    return s[min(len(s) - 1, max(0, math.ceil(p / 100 * len(s)) - 1))]


def measure_latency(client, n: int = 10, gap: float = 0.5) -> dict:
    lat: list[float] = []
    errors: list[str] = []
    try:
        client.multi_price(CODES)  # 워밍업: 첫 호출은 토큰 발급이 섞이므로 지연에 넣지 않는다
    except Exception as exc:  # noqa: BLE001
        errors.append(getattr(exc, "code", type(exc).__name__))
    time.sleep(gap)
    for _ in range(n):
        t0 = time.monotonic()
        try:
            client.multi_price(CODES)
            lat.append(time.monotonic() - t0)
        except Exception as exc:  # noqa: BLE001 — 오류 종류만 기록(메시지에 비밀값이 없도록 코드만)
            errors.append(getattr(exc, "code", type(exc).__name__))
        time.sleep(gap)
    out: dict = {"ok": len(lat), "errors": errors}
    if lat:
        out |= {"p50": statistics.median(lat), "p95": percentile(lat, 95), "max": max(lat)}
    return out


def run_step(make_client, interval: float, calls: int, concurrency: int) -> dict:
    """호출 시작 간격 `interval`초로 `calls`회를 동시 `concurrency`건까지 보내 오류와 실제 호출률을 센다."""
    client = make_client(interval)
    errors: list[str] = []
    lock = threading.Lock()

    def one() -> None:
        try:
            client.multi_price(CODES)
        except Exception as exc:  # noqa: BLE001
            with lock:
                errors.append(getattr(exc, "code", type(exc).__name__))

    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=max(concurrency, 8)) as pool:  # 응답이 느려도 우리 쪽 동시 수가 병목이 되지 않게 넉넉히
        futures = []
        for i in range(calls):
            target = t0 + i * interval
            wait = target - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            futures.append(pool.submit(one))
        for f in futures:
            f.result()
    took = time.monotonic() - t0
    rate = calls / took if took > 0 else 0.0
    # KisClient는 한도 오류를 1초 쉬고 한 번 자동 재시도하므로, 오류가 가려져도 호출률이 설정 간격의 85% 아래로 떨어지면 한도 신호로 본다
    limited = bool(errors) or rate < 0.85 / interval
    return {"interval": interval, "calls": calls, "errors": list(errors), "seconds": took, "rate": rate, "limited": limited}


def recommend(results: list[dict], *, aggressive: bool) -> float | None:
    """오류 없이 통과한 가장 빠른 단계를 권장한다(기본은 0.1초보다 빠르게는 권장하지 않는다). 통과한 단계가 없으면 None."""
    passed = [r["interval"] for r in results if not r.get("limited", bool(r["errors"]))]
    if not aggressive:
        passed = [i for i in passed if i >= SAFE_STEP_CAP]
    return min(passed) if passed else None


def probe(make_client, *, calls: int = 40, concurrency: int = 4, aggressive: bool = False, latency_n: int = 10, gap: float = 0.5, out=print) -> int:
    out("[1/3] 응답 지연 측정(순서대로 호출)")
    lat = measure_latency(make_client(0.0), latency_n, gap)  # 클라이언트 간격 대기가 지연에 섞이지 않게 0
    if not lat["ok"]:
        out(f"  모두 실패: {sorted(set(lat['errors']))}  → 앱키·네트워크 확인(kis_smoke_test.py 먼저 실행)")
        return 2
    out(f"  성공 {lat['ok']}/{latency_n}  중앙값 {lat['p50'] * 1000:.0f}ms  95% {lat['p95'] * 1000:.0f}ms  최대 {lat['max'] * 1000:.0f}ms")
    if lat["errors"]:
        out(f"  실패 종류: {sorted(set(lat['errors']))}")

    out(f"[2/3] 호출 간격 단계별 시험(동시 {concurrency}건, 단계당 {calls}회) — 오류가 나면 거기서 멈춘다")
    results: list[dict] = []
    for interval in STEPS:
        r = run_step(make_client, interval, calls, concurrency)
        results.append(r)
        kinds = sorted(set(r["errors"]))
        out(f"  간격 {interval}초: 실제 {r['rate']:.1f}건/초(목표 {1 / interval:.1f}), 오류 {len(r['errors'])}/{calls} {kinds if kinds else ''}{' ← 한도 신호(호출률 저하)' if r['limited'] and not r['errors'] else ''}")
        if r["limited"]:
            out("  → 여기서 한도 신호가 나와 더 빠른 단계는 시험하지 않는다.")
            break
        time.sleep(STEP_REST)  # 단계 사이 한도 창이 비도록 잠시 쉰다

    out("[3/3] 권장 설정")
    rec = recommend(results, aggressive=aggressive)
    if rec is None:
        out("  오류 없이 통과한 단계가 없습니다. KIS_MARKET_MIN_INTERVAL을 0.2 이상으로 키우고 KIS_MARKET_CONCURRENCY=1로 두세요.")
        return 0
    conc = 1 if lat["p50"] <= rec else min(concurrency, max(2, math.ceil(lat["p50"] / rec)))
    cycle = BATCHES * max(rec, 0.0)
    out(f"  .env에 넣을 줄:\n    KIS_MARKET_MIN_INTERVAL={rec}\n    KIS_MARKET_CONCURRENCY={conc}")
    out(f"  전 종목({TOTAL_CODES}개, {BATCHES}호출) 한 바퀴 예상: 약 {cycle:.1f}초 (응답 지연 {lat['p50'] * 1000:.0f}ms는 동시 호출이 가립니다)")
    if not aggressive and any(r["interval"] < SAFE_STEP_CAP and not r["limited"] for r in results):
        out("  (0.1초보다 빠른 단계도 통과했지만 기본 한도의 50%를 넘기지 않으려고 권장하지 않았습니다. 한도 확대 계정이면 --aggressive)")
    return 0


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--calls", type=int, default=40)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--aggressive", action="store_true")
    args = ap.parse_args(argv)
    _load_dotenv()
    os.environ["LOCAL_INTRADAY_ENABLED"] = "true"
    from services.public_api.intraday import config as cfg
    from services.public_api.intraday.kis_client import KisClient

    try:
        settings = cfg.get_settings()
    except cfg.IntradayConfigError as exc:
        print(f"[설정 오류] {exc}")
        return 1
    if not settings.configured:
        print("[설정 오류] KIS_APP_KEY / KIS_APP_SECRET 이 설정되지 않았습니다(.env 확인).")
        return 1
    return probe(lambda interval: KisClient(settings, min_interval=interval), calls=max(5, args.calls), concurrency=max(1, min(8, args.concurrency)), aggressive=args.aggressive)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
