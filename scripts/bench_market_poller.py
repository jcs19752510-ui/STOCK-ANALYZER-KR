"""전 종목 시세 순환 속도 측정(모의 증권사 + 응답 지연 주입). 실제 `KisClient`·`MarketSnapshotPoller` 코드를 그대로 쓴다.

사용: python scripts/bench_market_poller.py --latency 0.15 --interval 0.1 [--codes 2766] [--cycles 2] [--client-interval 0.12]
출력: JSON 한 줄(한 바퀴 실측 초, 실측 호출률, 이론값). 실제 KIS 응답이 아니므로 '코드가 만드는 상한'을 확인하는 용도다.
"""

# ruff: noqa: E501
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import mock_kis_server as mock  # noqa: E402
from services.public_api.intraday.config import IntradaySettings, client_min_interval  # noqa: E402
from services.public_api.intraday.kis_client import KisClient  # noqa: E402
from services.public_api.realtime.market import MarketSnapshotPoller, PollerConfig, make_kis_fetcher  # noqa: E402


def make_handler(latency: float):
    class SlowHandler(mock.Handler):
        def do_GET(self) -> None:  # noqa: N802
            time.sleep(latency)
            super().do_GET()

    return SlowHandler


async def measure(args: argparse.Namespace, settings: IntradaySettings) -> dict:
    # 운영 경로(local_intraday.py)와 같은 계산: KIS_MARKET_MIN_INTERVAL이 0.12보다 작으면 클라이언트 간격도 같이 낮춘다.
    client_interval = args.client_interval if args.client_interval is not None else client_min_interval({"KIS_MARKET_MIN_INTERVAL": str(args.interval)})
    client = KisClient(settings, min_interval=client_interval)
    codes = [f"{i:06d}" for i in range(1, args.codes + 1)]
    cfg = PollerConfig(min_interval=args.interval, jitter_ratio=0.1, concurrency=args.concurrency)
    poller = MarketSnapshotPoller(make_kis_fetcher(client), codes, cfg)
    times = []
    for _ in range(args.cycles):
        t0 = time.monotonic()
        calls0 = poller.calls_total
        ok = await poller.run_cycle()
        dt = time.monotonic() - t0
        times.append({"seconds": round(dt, 2), "calls": poller.calls_total - calls0, "ok": ok})
    best = min(t["seconds"] for t in times)
    calls = times[0]["calls"]
    return {
        "latency_s": args.latency,
        "poller_interval_s": args.interval,
        "client_interval_s": client_interval,
        "concurrency": args.concurrency,
        "codes": args.codes,
        "calls_per_cycle": calls,
        "cycles": times,
        "measured_cycle_s": best,
        "measured_calls_per_s": round(calls / best, 2),
        "theory_cycle_s": round(calls * args.interval, 2),
        "quotes": len(poller.snapshot()),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--latency", type=float, default=0.0, help="요청당 응답 지연(초)")
    ap.add_argument("--interval", type=float, default=0.125, help="KIS_MARKET_MIN_INTERVAL")
    ap.add_argument("--client-interval", type=float, default=None, help="KisClient 내부 호출 간격(기본: 운영과 같은 0.12)")
    ap.add_argument("--concurrency", type=int, default=4, help="KIS_MARKET_CONCURRENCY (1=직렬, 이전 동작)")
    ap.add_argument("--codes", type=int, default=2766)
    ap.add_argument("--cycles", type=int, default=2)
    args = ap.parse_args()

    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(args.latency))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    tmp = Path(tempfile.mkdtemp(prefix="bench-kis-"))
    settings = IntradaySettings(
        enabled=True,
        app_key="bench-key",
        app_secret="bench-secret",
        base_url=f"http://127.0.0.1:{server.server_address[1]}",
        allowed_networks=(),
        token_cache_path=tmp / "token.json",
    )
    result = asyncio.run(measure(args, settings))
    server.shutdown()
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
