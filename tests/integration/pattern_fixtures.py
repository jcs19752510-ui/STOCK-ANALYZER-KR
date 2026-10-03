"""패턴 스크리닝 테스트 픽스처 — 종목 T00001~T00010, 각 130거래일 (05-test-plan §1-1).

시드 고정(`random.Random`)이라 결정론적이다. 임시 DB(`pg_temp_db.temp_database()`)에만 적재하며
개발 DB에는 절대 넣지 않는다. UNIT-14(배치 통합)·UNIT-16(API) 테스트가 같은 픽스처를 쓴다.

각 종목의 설계 의도와 기대 상태는 `EXPECTED`에 있고, 기준 구현(오라클)과 맞는지는
`test_pattern_derivation_db.py::test_fixture_series_match_design_intent`가 검증한다.
가격은 정수(원), 시계열은 **최신순**(0번 = 대상 거래일)으로 반환한다.
"""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import text

TARGET_DATE = date(2026, 9, 30)  # 수요일(평일). 130거래일 = 직전 평일 130개
N_DAYS = 130
BASE_PRICE = 10000
BASE_VOLUME = 100000


@dataclass(frozen=True)
class FixtureStock:
    code: str
    name: str
    market: str  # 상장시장(KOSPI/KOSDAQ)
    market_cap_krw: int
    closes: list[int]  # 최신순
    volumes: list[int]  # 최신순


def trading_dates(target: date = TARGET_DATE, n: int = N_DAYS) -> list[date]:
    """target부터 과거로 n개 평일(최신순). 픽스처에서는 평일 = 거래일로 취급."""
    out: list[date] = []
    d = target
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out


def _noisy(
    rnd: random.Random, n: int, level: float, amp_old: float, amp_mid: float, amp_new: float
):
    """오래된 → 최신 순서의 가격. 최근일수록 노이즈 진폭이 줄어든다(변동성 수축)."""
    out = []
    for t in range(n):
        amp = amp_old if t < n - 30 else amp_mid if t < n - 10 else amp_new
        out.append(level * (1 + rnd.uniform(-amp, amp)))
    return out


def _volumes(
    rnd: random.Random, n: int, tail_mult: float = 1.0, tail_days: int = 0
) -> list[float]:
    vols = [BASE_VOLUME * (1 + rnd.uniform(-0.2, 0.2)) for _ in range(n)]
    for i in range(1, tail_days + 1):
        vols[n - i] *= tail_mult
    return vols


def _finish(prices: list[float], vols: list[float]) -> tuple[list[int], list[int]]:
    """오래된→최신 float 시계열을 정수 반올림 후 최신순으로 뒤집는다."""
    return [round(p) for p in prices][::-1], [round(v) for v in vols][::-1]


def _ideal(seed: int):
    """T00001 기본형: 횡보 → 수렴 → 60일선 근접(소폭 아래) → 점진적 거래량 증가."""
    rnd = random.Random(seed)
    n = N_DAYS
    prices = _noisy(rnd, n, BASE_PRICE, 0.02, 0.01, 0.003)
    for i in range(10):  # 최근 10일: 60일선 아래로 서서히 내려옴(최대 -1.2%)
        prices[n - 10 + i] *= 1 - 0.012 * (i + 1) / 10
    return prices, _volumes(rnd, n, tail_mult=1.3, tail_days=5)


def build_stocks() -> dict[str, FixtureStock]:
    n = N_DAYS
    spec: dict[str, tuple[list[float], list[float]]] = {}

    spec["T00001"] = _ideal(1)

    rnd = random.Random(2)  # T00002: 80일 +30% 이상 상승 추세
    spec["T00002"] = (
        [7000 * (1 + 1.0 * t / (n - 1)) * (1 + rnd.uniform(-0.004, 0.004)) for t in range(n)],
        _volumes(rnd, n),
    )

    rnd = random.Random(3)  # T00003: 최근 25일 급한 상승으로 이평선이 넓게 벌어짐
    p = _noisy(rnd, n, BASE_PRICE, 0.01, 0.01, 0.01)
    for i in range(25):
        p[n - 25 + i] *= 1.01 ** (i + 1)
    spec["T00003"] = (p, _volumes(rnd, n))

    rnd = random.Random(4)  # T00004: 종가가 60일선 약 +9~10% 위
    p = _noisy(rnd, n, BASE_PRICE, 0.005, 0.005, 0.005)
    for i in range(12):
        p[n - 12 + i] *= 1 + 0.11 * (i + 1) / 12
    spec["T00004"] = (p, _volumes(rnd, n))

    rnd = random.Random(5)  # T00005: 최근 8일 돌파 후 60일선 약 +12% 위
    p = _noisy(rnd, n, BASE_PRICE, 0.005, 0.005, 0.005)
    for i in range(8):
        p[n - 8 + i] *= 1 + 0.13 * (i + 1) / 8
    spec["T00005"] = (p, _volumes(rnd, n))

    prices, vols = _ideal(6)  # T00006: 이상형 + 오늘 거래량 8배
    vols[n - 1] *= 8
    spec["T00006"] = (prices, vols)

    prices, vols = _ideal(7)  # T00007: 10거래일 전 +12% 급등 + 거래량 6배(이후 가격 수준 유지)
    day = n - 1 - 10
    for t in range(day, n):
        prices[t] *= 1.12
    vols[day] *= 6
    spec["T00007"] = (prices, vols)

    rnd = random.Random(8)  # T00008: 시세 50거래일뿐
    spec["T00008"] = (_noisy(rnd, 50, BASE_PRICE, 0.01, 0.01, 0.01), _volumes(rnd, 50))

    rnd = random.Random(9)  # T00009: 40거래일 전 -50% 단절(액면분할 의심)
    p = _noisy(rnd, n, BASE_PRICE, 0.01, 0.01, 0.01)
    for t in range(n - 40):  # 그 이전(더 과거)을 2배로 → 최신순 index 40에서 -50%
        p[t] *= 2
    spec["T00009"] = (p, _volumes(rnd, n))

    spec["T00010"] = ([float(BASE_PRICE)] * n, [float(BASE_VOLUME)] * n)  # 완전 평탄

    stocks: dict[str, FixtureStock] = {}
    for i, (code, (prices, vols)) in enumerate(spec.items(), start=1):
        closes, volumes = _finish(prices, vols)
        stocks[code] = FixtureStock(
            code=code,
            name=f"픽스처{i:02d}",
            market="KOSPI" if i % 2 else "KOSDAQ",
            market_cap_krw=100_000_000_000 * i,  # 1,000억원 × i
            closes=closes,
            volumes=volumes,
        )
    return stocks


ALL_CONDS = ("c1", "c2", "c3", "c4", "c5", "c9")

# 기대 상태(기본 임계값 기준). conds에 없는 조건은 단정하지 않는다.
# 값 None = '산정 불가(null)'임을 단정.
EXPECTED: dict[str, dict] = {
    "T00001": {"status": "OK", "conds": {"c1": True, "c2": True, "c3": True, "c4": True,
                                          "c5": True, "c9": True}},
    "T00002": {"status": "OK", "conds": {"c1": False}},
    "T00003": {"status": "OK", "conds": {"c2": False}},
    "T00004": {"status": "OK", "conds": {"c3": False}},
    "T00005": {"status": "OK", "conds": {"c4": False}},
    "T00006": {"status": "OK", "conds": {"c5": False}},
    "T00007": {"status": "OK", "conds": {"c9": False}},
    "T00008": {"status": "INSUFFICIENT_HISTORY", "conds": dict.fromkeys(ALL_CONDS)},
    "T00009": {"status": "SUSPECT_PRICE_JUMP", "conds": dict.fromkeys(ALL_CONDS)},
    # 가격·거래량 완전 평탄: 변동성 수축비·거래량 이상치가 NULL → c2·c5는 3값 논리로 null
    "T00010": {"status": "OK", "conds": {"c1": True, "c2": None, "c3": True, "c4": False,
                                          "c5": None, "c9": True}},
}


def seed_fixture(engine, *, stocks: dict[str, FixtureStock] | None = None) -> uuid.UUID:
    """임시 DB에 stock_master·raw_ohlcv·raw_fundamentals를 적재한다. 반환: 적재 batch_run_id."""
    stocks = stocks or build_stocks()
    dates = trading_dates()
    batch_id = uuid.uuid4()
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO public_serving.batch_run"
                "(batch_run_id,run_type,status,validation_passed)"
                " VALUES (:i,'ingest','SUCCESS',true)"
            ),
            {"i": batch_id},
        )
        c.execute(
            text(
                "INSERT INTO public_serving.stock_master(stock_code,name,market,is_active)"
                " VALUES (:c,:n,:m,true)"
            ),
            [{"c": s.code, "n": s.name, "m": s.market} for s in stocks.values()],
        )
        ohlcv = []
        for s in stocks.values():
            for i, (close, vol) in enumerate(zip(s.closes, s.volumes, strict=True)):
                ohlcv.append(
                    {
                        "c": s.code,
                        "d": dates[i],
                        "o": close,
                        "h": round(close * 1.01),
                        "l": round(close * 0.99),
                        "cl": close,
                        "v": vol,
                        "tv": close * vol,
                        "b": batch_id,
                    }
                )
        c.execute(
            text(
                "INSERT INTO raw_internal.raw_ohlcv"
                "(stock_code,trade_date,market,open,high,low,close,volume,trading_value,"
                "ingested_at,source_batch_id)"
                " VALUES (:c,:d,'KRX',:o,:h,:l,:cl,:v,:tv,now(),:b)"
            ),
            ohlcv,
        )
        c.execute(
            text(
                "INSERT INTO raw_internal.raw_fundamentals"
                "(stock_code,trade_date,per,pbr,market_cap,ingested_at,source_batch_id)"
                " VALUES (:c,:d,NULL,NULL,:mc,now(),:b)"
            ),
            [
                {"c": s.code, "d": TARGET_DATE, "mc": s.market_cap_krw, "b": batch_id}
                for s in stocks.values()
            ],
        )
    return batch_id
