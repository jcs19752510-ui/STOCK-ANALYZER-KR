#!/usr/bin/env python
# ruff: noqa: E501
"""모의 공공데이터포털(금융위원회_주식시세정보) 서버 — 일일 배치 종단 시험·화면 시험용 개발 도구.

실제 서버가 아니다. 실제 API와 같은 요청 파라미터(serviceKey, resultType=json, basDt, numOfRows, pageNo)와 응답 봉투
(`response.header.resultCode/resultMsg`, `body.items.item`, `numOfRows/pageNo/totalCount`)로 가짜 시세를 돌려준다.
- `--unpublished YYYY-MM-DD,...`: 해당 거래일은 아직 배포 전(0건)으로 응답 — +1영업일 지연을 흉내 낸다.
- 라이브러리로 쓸 때는 `start_server()`가 (서버, 통계)를 돌려준다. 통계는 basDt별 호출 횟수.
사용: python scripts/mock_gov_data_server.py --port 9300
환경변수: GOV_DATA_PORTAL_BASE_URL=http://127.0.0.1:9300/ GOV_DATA_PORTAL_SERVICE_KEY=mock
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import threading
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

STOCKS = [(f"{100000 + i:06d}", f"모의종목{i:02d}", "KOSPI" if i % 3 else "KOSDAQ") for i in range(30)]


def _rng(*parts: str) -> random.Random:
    return random.Random(int(hashlib.sha256("|".join(parts).encode()).hexdigest()[:12], 16))


def make_item(code: str, name: str, market: str, bas_dt: str) -> dict:
    rng = _rng(code, bas_dt)
    base = 5000 + int(hashlib.sha256(code.encode()).hexdigest()[:4], 16) % 40000
    # 날짜마다 조금씩 변하는 값(전일 대비 등락이 생기도록 날짜 번호를 섞는다)
    drift = 1 + (int(bas_dt) % 997) / 20000
    close = round(base * drift)
    return {
        "basDt": bas_dt,
        "srtnCd": code,
        "isinCd": f"KR7{code}003",
        "itmsNm": name,
        "mrktCtg": "코스피" if market == "KOSPI" else "코스닥",
        "clpr": str(close),
        "vs": "0",
        "fltRt": "0",
        "mkp": str(round(close * 0.99)),
        "hipr": str(round(close * 1.02)),
        "lopr": str(round(close * 0.97)),
        "trqu": str(rng.randint(10_000, 500_000)),
        "trPrc": str(close * rng.randint(10_000, 500_000)),
        "lstgStCnt": "1000000",
        "mrktTotAmt": str(close * 1_000_000),
    }


def make_handler(unpublished: set[str], stats: Counter, service_key: str | None):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
            bas_dt = q.get("basDt", "")
            if service_key and q.get("serviceKey") != service_key:
                self._send(200, {"response": {"header": {"resultCode": "30", "resultMsg": "SERVICE KEY IS NOT REGISTERED ERROR."}}})
                return
            stats[bas_dt] += 1
            page, rows = int(q.get("pageNo", "1")), int(q.get("numOfRows", "10"))
            items = [] if bas_dt in unpublished else [make_item(c, n, m, bas_dt) for c, n, m in STOCKS]
            total = len(items)
            chunk = items[(page - 1) * rows : page * rows]
            body = {
                "numOfRows": rows,
                "pageNo": page,
                "totalCount": total,
                "items": ({"item": chunk} if chunk else ""),
            }
            self._send(200, {"response": {"header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."}, "body": body}})

        def _send(self, status: int, payload: dict) -> None:
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *args) -> None:
            pass

    return Handler


def start_server(port: int = 0, unpublished: set[str] | None = None, service_key: str | None = None):
    """백그라운드 스레드로 서버를 띄운다. (서버, 호출 통계, 미배포 날짜 집합) 반환 — 집합을 바꾸면 즉시 반영된다."""
    unpub = unpublished if unpublished is not None else set()
    stats: Counter = Counter()
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(unpub, stats, service_key))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, stats, unpub


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=9300)
    parser.add_argument("--unpublished", default="", help="아직 배포 전인 거래일(YYYY-MM-DD, 쉼표 구분)")
    args = parser.parse_args()
    unpub = {d.replace("-", "") for d in args.unpublished.split(",") if d.strip()}
    server, _, _ = start_server(args.port, unpub)
    print(f"모의 공공데이터 서버 http://127.0.0.1:{server.server_address[1]}/ (실제 데이터 아님)", flush=True)
    threading.Event().wait()


if __name__ == "__main__":
    main()
