"""본인 전용 증권사(HTS) 조건검색 결과 API (DEC-088). **내 PC 전용**, 기본 꺼짐, 소유자(관리자)만. 계약서: docs/stock-detail/09-psearch-api-contract.md

- `GET /api/v1/local/psearch/conditions` — 내 HTS에 서버저장한 조건 목록(60초 캐시).
- `GET /api/v1/local/psearch/results?seq=0` — 조건 하나의 현재 결과 종목. 조건별로 `KIS_PSEARCH_CACHE_SECONDS`(기본 5, 2~60) 동안 재사용하고,
  동시 요청이 몰려도 증권사 호출은 한 번(조건별 잠금)이다. 직전 결과와 비교해 편입 시각(`entered_at`)·변화(`changes`)를 기록한다.
접근 통제는 `local_realtime.require_owner`를 그대로 쓴다. 증권사 클라이언트는 `shared_intraday_service`의 인스턴스(토큰·호출 간격 공유).
HTS ID·앱키는 응답·로그·오류 메시지에 나오지 않는다(증권사 문구는 비밀값을 가린 뒤에만 싣는다).
"""

# ruff: noqa: E501
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, Depends, Query, Response

from services.public_api.api.local_intraday import shared_intraday_service
from services.public_api.api.local_market import _not_configured
from services.public_api.api.local_realtime import require_owner
from services.public_api.db.session import get_session_factory
from services.public_api.db.stock_repository import lookup_stock_names
from services.public_api.errors import ApiError
from services.public_api.intraday import config as cfg
from services.public_api.intraday.kis_client import KisError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/local/psearch", tags=["local-psearch"])

SEQ_RE = re.compile(r"[0-9A-Za-z]{1,10}")
CODE_RE = re.compile(r"[0-9A-Za-z]{6}")
CODE_KEYS = ("code", "stck_shrn_iscd", "mksc_shrn_iscd", "jong_code", "stock_code")  # 계약서 §4 (scripts/kis_psearch_smoke_test.py와 같은 순서)
NAME_KEYS = ("name", "hts_kor_isnm", "stock_name")
MAX_ITEMS = 100
MAX_CHANGES = 20
MAX_SEQS = 20
CONDITIONS_TTL = 60.0
CACHE_DEFAULT, CACHE_MIN, CACHE_MAX = 5.0, 2.0, 60.0
MASTER_TTL = 3600.0
MASTER_MAX = 5000
MASTER_RETRY_AFTER = 30.0  # 마스터 읽기가 실패하면 이 시간 동안 다시 묻지 않는다(요청마다 DB를 치지 않게)
EMPTY_MESSAGE_MAX = 120
_PROVIDER_PREFIX = "증권사가 요청을 거절했습니다."


# ── 로그 마스킹: httpx가 INFO로 요청 주소(쿼리의 user_id=HTS ID)를 남기지 않게 한다 ─────────────────
class _RedactUserId(logging.Filter):
    _RE = re.compile(r"(user_id=)[^&\s'\"]*")

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = self._RE.sub(r"\1***", record.getMessage())
            record.args = None
        except Exception:  # noqa: BLE001 — 로그 처리 때문에 요청이 실패하면 안 된다
            pass
        return True


for _name in ("httpx", "httpcore"):
    logging.getLogger(_name).addFilter(_RedactUserId())


# ── 주입 가능한 의존: 시계·캐시 시간·종목 마스터 ──────────────────────────────────────────────────
def _env_cache_seconds() -> float:
    raw = os.environ.get("KIS_PSEARCH_CACHE_SECONDS", "").strip()
    try:
        value = float(raw) if raw else CACHE_DEFAULT
    except ValueError:
        return CACHE_DEFAULT
    if value != value:  # NaN
        return CACHE_DEFAULT
    return min(CACHE_MAX, max(CACHE_MIN, value))


_clock: Callable[[], float] = time.time
_cache_seconds: Callable[[], float] = _env_cache_seconds


def set_clock(clock: Callable[[], float] | None) -> None:
    """시계(epoch 초)를 바꾼다(시험용 주입). None이면 `time.time`."""
    global _clock
    _clock = clock or time.time


def set_cache_seconds(provider: Callable[[], float] | None) -> None:
    """결과 캐시 시간을 바꾼다(시험용 주입, 범위 보정 없음). None이면 환경변수 `KIS_PSEARCH_CACHE_SECONDS`(2~60, 기본 5)."""
    global _cache_seconds
    _cache_seconds = provider or _env_cache_seconds


def load_master(codes: list[str]) -> dict[str, tuple[str, str]]:
    """DB(`public_serving.stock_master`, `api_service`는 SELECT 권한)에서 코드 → (이름, 시장)을 읽는다(동기 — 스레드에서 실행)."""
    session = get_session_factory()()
    try:
        return lookup_stock_names(session, codes)
    finally:
        session.close()


_master_loader: Callable[[list[str]], dict[str, tuple[str, str]]] = load_master


def set_master_loader(loader: Callable[[list[str]], dict[str, tuple[str, str]]] | None) -> None:
    """종목 마스터 읽기 함수를 바꾼다(시험용 주입). None이면 DB 읽기."""
    global _master_loader
    _master_loader = loader or load_master


# ── 상태 ───────────────────────────────────────────────────────────────────────────────────────
@dataclass
class _Entry:
    """조건(seq) 하나의 캐시·추적 상태. 요청 처리는 `lock` 아래에서만 바꾼다."""

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    has_result: bool = False
    rows: list[tuple[str, str | None]] = field(default_factory=list)  # (코드, 증권사 행의 이름)
    entered: dict[str, float] = field(default_factory=dict)  # 지금 결과에 있는 종목 → 처음 본 시각
    changes: list[dict[str, Any]] = field(default_factory=list)
    fields: list[str] = field(default_factory=list)
    capped: bool = False
    empty: bool = False
    empty_message: str | None = None
    fetched_at: float = 0.0
    stale: bool = False
    fail_until: float = 0.0  # 호출이 실패하면 캐시 시간 동안 다시 부르지 않는다(한도 초과를 키우지 않기 위해)
    fail_error: ApiError | None = None


_entries: OrderedDict[str, _Entry] = OrderedDict()  # 최근에 쓴 순서(맨 뒤가 최신)
_conditions: dict[str, Any] = {"key": None, "at": 0.0, "data": None, "fail_until": 0.0, "fail_error": None}
_conditions_lock: asyncio.Lock | None = None
_master_cache: OrderedDict[str, tuple[float, str | None, str | None]] = OrderedDict()  # 코드 → (읽은 시각, 이름, 시장)
_master_fail_until = 0.0


def reset_psearch_state() -> None:
    """테스트 전용: 캐시·추적 상태를 모두 버린다."""
    global _conditions_lock, _master_fail_until
    _entries.clear()
    _conditions.update(key=None, at=0.0, data=None, fail_until=0.0, fail_error=None)
    _conditions_lock = None
    _master_cache.clear()
    _master_fail_until = 0.0


# ── 비밀값 가리기·오류 변환 ───────────────────────────────────────────────────────────────────────
def _mask(text: str, settings: cfg.IntradaySettings) -> str:
    for secret in (settings.hts_id, settings.app_key, settings.app_secret):
        if secret:
            text = text.replace(secret, "***")
    return text


def _provider_detail(exc: KisError, settings: cfg.IntradaySettings) -> str:
    text = _mask(" ".join(str(exc.message).split()), settings)
    if text.startswith(_PROVIDER_PREFIX):
        text = text[len(_PROVIDER_PREFIX):].strip()
    return text[:EMPTY_MESSAGE_MAX]


def _api_error(exc: Exception, settings: cfg.IntradaySettings, *, conditions: bool = False) -> ApiError:
    code = getattr(exc, "code", None)
    if code == "RATE_LIMITED":
        return ApiError(status_code=429, code="RATE_LIMITED", message="증권사 호출 한도를 초과했습니다. 잠시 후 다시 시도하세요.")
    if conditions and code == "UPSTREAM_ERROR" and isinstance(exc, KisError):
        return ApiError(status_code=502, code="PSEARCH_REJECTED", message=f"증권사가 조건 목록 조회를 거절했습니다. {_provider_detail(exc, settings)}".strip())
    if isinstance(exc, KisError):
        detail = _mask(" ".join(str(exc.message).split()), settings)[:EMPTY_MESSAGE_MAX]
        return ApiError(status_code=502, code="UPSTREAM_UNAVAILABLE", message=detail or "증권사에서 응답을 받지 못했습니다.")
    return ApiError(status_code=502, code="UPSTREAM_UNAVAILABLE", message="증권사에서 응답을 받지 못했습니다.")  # 예상 밖 예외: 내용은 싣지 않는다


def _require_ready(settings: cfg.IntradaySettings) -> str:
    if not settings.configured:
        raise _not_configured()
    if not settings.hts_id:
        raise ApiError(status_code=503, code="PSEARCH_NOT_CONFIGURED", message="HTS ID가 설정되지 않았습니다. .env의 KIS_HTS_ID를 확인하세요.")
    return settings.hts_id


def _rows_of(body: dict[str, Any]) -> list[dict[str, Any]]:
    out = body.get("output2")
    return [r for r in out if isinstance(r, dict)] if isinstance(out, list) else []


# ── 조건 목록 ─────────────────────────────────────────────────────────────────────────────────
@router.get("/conditions")
async def psearch_conditions(response: Response, settings: cfg.IntradaySettings = Depends(require_owner)) -> dict[str, Any]:
    global _conditions_lock
    hts_id = _require_ready(settings)
    response.headers["Cache-Control"] = "no-store"
    if _conditions_lock is None:
        _conditions_lock = asyncio.Lock()
    key = (hts_id, settings.app_key, settings.base_url)  # 설정이 바뀌면 캐시를 쓰지 않는다
    async with _conditions_lock:
        now = _clock()
        c = _conditions
        if c["key"] == key and c["data"] is not None and 0 <= now - c["at"] < CONDITIONS_TTL:
            return {"data": c["data"], "error": None}
        if c["key"] == key and c["fail_error"] is not None and now < c["fail_until"]:
            raise c["fail_error"]
        client = shared_intraday_service(settings).client
        try:
            body = await asyncio.to_thread(client.psearch_titles, hts_id, low_priority=True)
        except Exception as exc:  # noqa: BLE001 — 증권사·네트워크 예외 종류는 다양하다. 비밀값을 가린 오류로 바꾼다
            err = _api_error(exc, settings, conditions=True)
            logger.warning("조건 목록 조회 실패(%s)", getattr(exc, "code", type(exc).__name__))
            _conditions.update(key=key, fail_until=now + CONDITIONS_TTL / 6, fail_error=err)  # 10초간 같은 오류(증권사를 두드리지 않는다)
            raise err from exc
        items: list[dict[str, str]] = []
        for row in _rows_of(body):
            seq = str(row.get("seq", "")).strip()
            if SEQ_RE.fullmatch(seq):
                items.append({"seq": seq, "group": str(row.get("grp_nm") or "").strip(), "name": str(row.get("condition_nm") or "").strip()})
        data = {"conditions": items, "fetched_at": round(now, 3)}
        _conditions.update(key=key, at=now, data=data, fail_until=0.0, fail_error=None)
        return {"data": data, "error": None}


# ── 결과 ──────────────────────────────────────────────────────────────────────────────────────
def _entry_for(seq: str) -> _Entry:
    entry = _entries.get(seq)
    if entry is None:
        entry = _entries[seq] = _Entry()
        while len(_entries) > MAX_SEQS:
            _entries.popitem(last=False)  # 가장 오래 안 쓴 조건부터 버린다
    else:
        _entries.move_to_end(seq)
    return entry


def _parse_rows(body: dict[str, Any]) -> tuple[list[tuple[str, str | None]], list[str], bool]:
    """(코드·이름 목록, 필드 이름, 한도 도달). 코드가 없는 행은 버리고 중복은 처음 한 번만 남긴다."""
    seen: dict[str, str | None] = {}
    fields: list[str] = []
    for row in _rows_of(body):
        if not fields:
            fields = [str(k) for k in row]
        code = None
        for k in CODE_KEYS:
            v = row.get(k)
            if v is not None and str(v).strip():
                code = str(v).strip()
                break
        if code is None:
            for v in row.values():
                t = str(v).strip()
                if len(t) == 6 and t.isalnum() and t.upper() == t:
                    code = t
                    break
        if code is None or not CODE_RE.fullmatch(code):
            continue
        code = code.upper()
        if code in seen:
            continue
        name = None
        for k in NAME_KEYS:
            v = row.get(k)
            if v is not None and str(v).strip():
                name = str(v).strip()
                break
        seen[code] = name
    rows = list(seen.items())
    capped = len(rows) >= MAX_ITEMS
    return rows[:MAX_ITEMS], fields, capped


def _apply(entry: _Entry, rows: list[tuple[str, str | None]], at: float, *, fields: list[str], capped: bool, empty: bool, empty_message: str | None) -> None:
    """새 결과를 반영한다: 편입 시각 갱신, 직전 결과와 달라졌으면 변화 기록(첫 조회는 기록하지 않음)."""
    new_codes = [c for c, _ in rows]
    old = entry.entered
    if entry.has_result:
        new_set = set(new_codes)
        added = [c for c in new_codes if c not in old]
        removed = [c for c in old if c not in new_set]
        if added or removed:
            entry.changes.insert(0, {"at": round(at, 3), "added": added, "removed": removed})
            del entry.changes[MAX_CHANGES:]
    entry.entered = {c: old.get(c, at) for c in new_codes}
    entry.rows = rows
    if fields and not entry.fields:
        entry.fields = fields  # 첫 비어 있지 않은 응답 기준
    entry.capped = capped
    entry.empty = empty
    entry.empty_message = empty_message
    entry.fetched_at = at
    entry.has_result = True
    entry.stale = False
    entry.fail_until = 0.0
    entry.fail_error = None


async def _refresh(entry: _Entry, seq: str, hts_id: str, settings: cfg.IntradaySettings, ttl: float) -> None:
    """캐시가 낡았으면 증권사를 한 번 부른다(호출하는 쪽이 `entry.lock`을 잡고 있다)."""
    now = _clock()
    if entry.has_result and 0 <= now - entry.fetched_at < ttl:
        return
    if entry.fail_until and now < entry.fail_until:  # 방금 실패했다: 같은 결과(이전 결과 stale 또는 같은 오류)를 돌려준다
        if entry.fail_error is not None and not entry.has_result:
            raise entry.fail_error
        return
    client = shared_intraday_service(settings).client
    try:
        body = await asyncio.to_thread(client.psearch_result, hts_id, seq, low_priority=True)
    except KisError as exc:
        # HTTP 200인 업무 거절(rt_cd≠0)만 0건으로 본다. HTTP 4xx/5xx(서버 장애·인증 오류)는 0건이 아니라 실패다 → 이전 결과 유지(stale)
        if exc.code == "UPSTREAM_ERROR" and getattr(exc, "http_status", None) in (None, 200):  # 증권사는 0건을 오류로 돌려준다(조건 키 오류와 같은 코드일 수 있어 문구를 그대로 보여 준다)
            message = _provider_detail(exc, settings) or None
            _apply(entry, [], _clock(), fields=[], capped=False, empty=True, empty_message=message)
            return
        _on_failure(entry, exc, settings, ttl)
        return
    except Exception as exc:  # noqa: BLE001
        _on_failure(entry, exc, settings, ttl)
        return
    rows, fields, capped = _parse_rows(body)
    _apply(entry, rows, _clock(), fields=fields, capped=capped, empty=not rows, empty_message=None)


def _on_failure(entry: _Entry, exc: Exception, settings: cfg.IntradaySettings, ttl: float) -> None:
    err = _api_error(exc, settings)
    logger.warning("조건검색 결과 조회 실패(%s)", getattr(exc, "code", type(exc).__name__))
    entry.fail_until = _clock() + ttl
    entry.fail_error = err
    if entry.has_result:
        entry.stale = True
        return
    raise err from exc


async def _enrich(codes: list[str]) -> dict[str, tuple[str | None, str | None]]:
    """코드 → (이름, 시장). 메모리에 1시간·최대 5,000건 캐시하고, 읽기에 실패하면 null로 계속한다."""
    global _master_fail_until
    now = _clock()
    for code in [c for c in codes if c in _master_cache and not 0 <= now - _master_cache[c][0] < MASTER_TTL]:
        _master_cache.pop(code, None)  # 만료됐거나 시계가 거꾸로 간 항목
    missing = [c for c in codes if c not in _master_cache]
    fresh: dict[str, tuple[str | None, str | None]] = {}  # 이번에 읽은 값(보관 한도에 밀려 캐시에서 빠져도 이번 응답에는 쓴다)
    if missing and now >= _master_fail_until:
        try:
            found = await asyncio.to_thread(_master_loader, missing)
            for code in missing:
                name, market = (found.get(code) or (None, None)) if isinstance(found, dict) else (None, None)
                fresh[code] = (str(name) if name else None, str(market) if market else None)
                _master_cache[code] = (now, *fresh[code])
                _master_cache.move_to_end(code)
            while len(_master_cache) > MASTER_MAX:
                _master_cache.popitem(last=False)
        except Exception as exc:  # noqa: BLE001 — DB 오류 종류는 다양하다. 이름·시장 없이 계속한다
            _master_fail_until = now + MASTER_RETRY_AFTER
            fresh = {}
            logger.warning("종목 마스터 읽기 실패(%s), 이름·시장 없이 계속", type(exc).__name__)
    return {c: fresh[c] if c in fresh else (_master_cache[c][1], _master_cache[c][2]) if c in _master_cache else (None, None) for c in codes}


@router.get("/results")
async def psearch_results(
    response: Response,
    seq: str = Query("", description="조건 키값(영숫자 1~10자)"),
    settings: cfg.IntradaySettings = Depends(require_owner),
) -> dict[str, Any]:
    if not SEQ_RE.fullmatch(seq):
        raise ApiError(status_code=400, code="INVALID_SEQ", message="조건 키값(seq)은 영숫자 1~10자여야 합니다.")
    hts_id = _require_ready(settings)
    response.headers["Cache-Control"] = "no-store"
    ttl = _cache_seconds()
    entry = _entry_for(seq)
    async with entry.lock:  # 같은 조건의 동시 요청은 한 번만 증권사를 부르고 같은 결과를 받는다
        await _refresh(entry, seq, hts_id, settings, ttl)
        now = _clock()
        rows = list(entry.rows)
        snapshot = {
            "capped": entry.capped, "empty": entry.empty, "empty_message": entry.empty_message,
            "changes": [{"at": c["at"], "added": list(c["added"]), "removed": list(c["removed"])} for c in entry.changes],
            "fields": list(entry.fields), "fetched_at": round(entry.fetched_at, 3),
            "age_seconds": round(max(0.0, now - entry.fetched_at), 3), "stale": entry.stale,
            "entered": dict(entry.entered),
        }
    info = await _enrich([c for c, _ in rows])
    items = [
        {"code": code, "name": row_name or info[code][0], "market": info[code][1], "entered_at": round(snapshot["entered"][code], 3)}
        for code, row_name in rows
    ]
    snapshot.pop("entered")
    data = {"seq": seq, "items": items, "count": len(items), **snapshot, "cache_ttl_seconds": ttl}
    return {"data": data, "error": None}
