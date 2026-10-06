#!/usr/bin/env python
"""모의 KIS 실시간(웹소켓) 서버 (DEC-084) — 앱키 없이 실시간 화면·연동을 시험하는 개발 도구.

실제 증권사 서버가 아니다. 구독 요청(`tr_type` 1/2, `H0UNCNT0`·`H0UNASP0`)에 응답하고, 구독한 종목의 **가짜** 체결·호가를 보낸다.
접속키 발급은 `scripts/mock_kis_server.py`의 `POST /oauth2/Approval`이 맡는다(같은 키 `mock-approval`).

사용(둘 다 띄운다):
    python scripts/mock_kis_server.py --port 9100
    python scripts/mock_kis_ws_server.py --port 9101
    # API 서버 환경변수
    LOCAL_INTRADAY_ENABLED=true KIS_APP_KEY=mock KIS_APP_SECRET=mock \
    KIS_BASE_URL=http://127.0.0.1:9100 KIS_WS_URL=ws://127.0.0.1:9101 KIS_ALLOW_CUSTOM_BASE_URL=true \
    python scripts/run_public_api.py

시험 코드는 이 파일의 `MockKisWsServer`를 직접 쓴다(`emit`으로 원하는 체결을 보내고, `drop_all`로 연결 끊김을 흉내낸다).
"""

# ruff: noqa: E501
from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from websockets.asyncio.server import ServerConnection, serve

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from mock_kis_server import _base_price, _tick_size  # noqa: E402

from services.public_api.realtime import protocol as proto  # noqa: E402

KST = timezone(timedelta(hours=9))
APPROVAL_KEY = "mock-approval"


def record(fields: tuple[str, ...], values: Mapping[str, Any]) -> list[str]:
    return [str(values.get(name, "")) for name in fields]


def frame(tr_id: str, records: list[list[str]]) -> str:
    flat = "^".join("^".join(r) for r in records)
    return f"0|{tr_id}|{len(records):03d}|{flat}"


def trade_values(code: str, hhmmss: str, price: int, volume: int, acml: int, *, date: str = "20261006", prev_close: int | None = None) -> dict[str, Any]:
    prev = prev_close if prev_close is not None else price
    diff = price - prev
    return {
        "mksc_shrn_iscd": code, "stck_cntg_hour": hhmmss, "stck_prpr": price,
        "prdy_vrss_sign": "2" if diff > 0 else "5" if diff < 0 else "3", "prdy_vrss": abs(diff),
        "prdy_ctrt": f"{(diff / prev * 100) if prev else 0:.2f}",
        "stck_oprc": prev, "stck_hgpr": max(price, prev), "stck_lwpr": min(price, prev),
        "askp1": price + _tick_size(price), "bidp1": price - _tick_size(price),
        "cntg_vol": volume, "acml_vol": acml, "acml_tr_pbmn": acml * price, "cttr": "100.00",
        "cntg_cls_code": "1", "bsop_date": date, "trht_yn": "N", "vi_stnd_prc": 0,
    }


def book_values(code: str, hhmmss: str, price: int, *, seed: int = 0) -> dict[str, Any]:
    tick = _tick_size(price)
    rng = random.Random(seed + price)
    v: dict[str, Any] = {"mksc_shrn_iscd": code, "bsop_hour": hhmmss, "hour_cls_code": "0"}
    total_a = total_b = 0
    for i in range(1, 11):
        v[f"askp{i}"] = price + tick * i
        v[f"bidp{i}"] = price - tick * (i - 1)
        qa, qb = rng.randint(10, 5000), rng.randint(10, 5000)
        v[f"askp_rsqn{i}"], v[f"bidp_rsqn{i}"] = qa, qb
        total_a, total_b = total_a + qa, total_b + qb
    v["total_askp_rsqn"], v["total_bidp_rsqn"] = total_a, total_b
    return v


class MockKisWsServer:
    def __init__(self, *, approval_key: str = APPROVAL_KEY, ping_interval: float | None = None, auto: bool = False, tick_interval: float = 0.5, max_subscribe: int = proto.SUBSCRIBE_LIMIT) -> None:
        self.approval_key = approval_key
        self.ping_interval = ping_interval
        self.auto = auto
        self.tick_interval = tick_interval
        self.max_subscribe = max_subscribe
        self._conns: dict[ServerConnection, set[tuple[str, str]]] = {}
        self._server: Any = None
        self._tasks: list[asyncio.Task[None]] = []
        self.received: list[dict[str, Any]] = []  # 받은 구독 요청(접속키 제외)
        self.pongs = 0
        self.connect_count = 0
        self.ignore_subscribe = False  # 구독 응답을 보내지 않는 장애 흉내

    @property
    def subscriptions(self) -> set[tuple[str, str]]:
        return set().union(*self._conns.values()) if self._conns else set()

    async def start(self, host: str = "127.0.0.1", port: int = 0) -> int:
        self._server = await serve(self._handler, host, port, ping_interval=None)
        if self.auto:
            self._tasks.append(asyncio.create_task(self._auto_loop()))
        if self.ping_interval:
            self._tasks.append(asyncio.create_task(self._ping_loop()))
        return self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def drop_all(self) -> None:
        """연결을 모두 끊는다(재연결 시험)."""
        for ws in list(self._conns):
            await ws.close()

    async def emit(self, tr_id: str, values: Mapping[str, Any]) -> None:
        """해당 종목·TR을 구독한 연결에 레코드 한 건을 보낸다."""
        fields = proto.FIELDS_BY_TR[tr_id]
        code = str(values["mksc_shrn_iscd"])
        msg = frame(tr_id, [record(fields, values)])
        for ws, subs in list(self._conns.items()):
            if (tr_id, code) in subs:
                await ws.send(msg)

    async def emit_raw(self, text: str) -> None:
        for ws in list(self._conns):
            await ws.send(text)

    async def _handler(self, ws: ServerConnection) -> None:
        self.connect_count += 1
        self._conns[ws] = set()
        try:
            async for message in ws:
                await self._on_message(ws, message)
        except Exception:
            pass
        finally:
            self._conns.pop(ws, None)

    async def _on_message(self, ws: ServerConnection, message: Any) -> None:
        try:
            req = json.loads(message)
            header, tr_input = req["header"], req["body"]["input"]
            tr_id, code, tr_type = tr_input["tr_id"], tr_input["tr_key"], header["tr_type"]
        except (ValueError, KeyError, TypeError):
            return
        self.received.append({"tr_type": tr_type, "tr_id": tr_id, "tr_key": code, "custtype": header.get("custtype")})
        if self.ignore_subscribe:
            return

        def reply(rt_cd: str, msg_cd: str, msg: str) -> str:
            return json.dumps({"header": {"tr_id": tr_id, "tr_key": code, "encrypt": "N"}, "body": {"rt_cd": rt_cd, "msg_cd": msg_cd, "msg1": msg}})

        if header.get("approval_key") != self.approval_key:
            await ws.send(reply("1", "OPSP0011", "invalid approval : NOT FOUND"))
            return
        subs = self._conns[ws]
        if tr_type == "1":
            if (tr_id, code) in subs:
                await ws.send(reply("1", "OPSP0002", "ALREADY IN SUBSCRIBE"))
            elif len(self.subscriptions) >= self.max_subscribe:
                await ws.send(reply("1", "OPSP0008", "MAX SUBSCRIBE OVER"))
            else:
                subs.add((tr_id, code))
                await ws.send(reply("0", "OPSP0000", "SUBSCRIBE SUCCESS"))
        elif tr_type == "2":
            subs.discard((tr_id, code))
            await ws.send(reply("0", "OPSP0001", "UNSUBSCRIBE SUCCESS"))

    async def _ping_loop(self) -> None:
        while True:
            await asyncio.sleep(self.ping_interval or 1)
            for ws in list(self._conns):
                try:
                    await ws.send(json.dumps({"header": {"tr_id": "PINGPONG", "datetime": datetime.now(KST).strftime("%Y%m%d%H%M%S")}}))
                except Exception:
                    pass

    async def _auto_loop(self) -> None:
        """구독한 종목마다 가짜 체결·호가를 주기적으로 보낸다(화면 시험용)."""
        state: dict[str, dict[str, int]] = {}
        rng = random.Random(7)
        while True:
            await asyncio.sleep(self.tick_interval)
            now = datetime.now(KST).strftime("%H%M%S")
            for code in {c for _, c in self.subscriptions}:
                st = state.setdefault(code, {"price": _base_price(code), "prev": _base_price(code), "acml": rng.randint(10_000, 500_000)})
                tick = _tick_size(st["price"])
                st["price"] = max(tick, st["price"] + rng.choice((-1, 0, 0, 1)) * tick)
                vol = rng.randint(1, 300)
                st["acml"] += vol
                await self.emit(proto.TR_TRADE, trade_values(code, now, st["price"], vol, st["acml"], date=datetime.now(KST).strftime("%Y%m%d"), prev_close=st["prev"]))
                await self.emit(proto.TR_BOOK, book_values(code, now, st["price"], seed=st["acml"]))


async def _amain(port: int, host: str, ping: float) -> None:
    server = MockKisWsServer(auto=True, ping_interval=ping)
    actual = await server.start(host, port)
    print(f"[mock-kis-ws] ws://{host}:{actual} (접속키 {APPROVAL_KEY}) — 실제 시세가 아닙니다.", flush=True)
    await asyncio.Event().wait()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=9101)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--ping", type=float, default=10.0, help="PINGPONG 전송 간격(초)")
    args = ap.parse_args()
    try:
        asyncio.run(_amain(args.port, args.host, args.ping))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
