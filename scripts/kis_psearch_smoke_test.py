#!/usr/bin/env python
# ruff: noqa: E501
"""한국투자증권 HTS 조건검색(서버 저장 조건) 연동 확인 도구 (DEC-087) — **장중에 내 PC에서 실제 앱키로 실행**한다.

목적: 내가 HTS에서 만들어 "서버저장"한 조건검색식의 결과를 Open API로 반복 조회해,
  ① 조건 목록이 오는지 ② 결과 종목이 오는지(응답 필드 이름·값 모양) ③ **장중에 결과가 실제로 바뀌는지(편입·이탈)**, 바뀌는 데 걸리는 시간,
  ④ 호출 지연·한도 오류·100건 한도에 걸리는지를 눈으로 확인한다. 이 결과로 사이트에 "증권사 조건검색" 화면을 만들지, 어떤 주기로 갱신할지 정한다.
이 저장소의 자동 시험은 모의 서버만 쓰며 개발 환경에서는 증권사로 나갈 수 없으므로, 실제 응답 확인은 이 도구로만 가능하다.
읽기 전용이다(주문·계좌 호출 없음). 앱키·시크릿·토큰·HTS ID는 어떤 출력에도 나오지 않는다(출력 직전에 가린다).

준비(한 번): HTS(eFriend Plus) [0110] 조건검색에서 조건식을 만들고 **서버저장**한다. `.env`에 KIS_APP_KEY, KIS_APP_SECRET, KIS_HTS_ID(내 HTS 로그인 ID)를 넣는다.

사용(프로젝트 루트에서):
    py -3.12 scripts\\kis_psearch_smoke_test.py --list-only                 # 조건 목록만 확인(장 시간 밖에도 가능)
    py -3.12 scripts\\kis_psearch_smoke_test.py --seq 0 --seconds 300        # 0번 조건을 5분간 5초마다 조회하며 편입·이탈 관찰
    py -3.12 scripts\\kis_psearch_smoke_test.py --seq 0 --seq 1 --interval 3 --out psearch-report.json
종료코드: 0 정상(결과를 받았고 장중 변화도 확인) / 1 실패(설정·인증·응답 이상) / 2 확인필요(변화 없음·장 시간 밖·결과 0건 등)
"""

from __future__ import annotations

import argparse
import json
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

from services.public_api.intraday import config as cfg  # noqa: E402
from services.public_api.intraday.kis_client import KisClient, KisError  # noqa: E402

KST = timezone(timedelta(hours=9))
HTS_ID_ENV = "KIS_HTS_ID"
MAX_SECONDS = 1800.0
DEFAULT_SECONDS = 120.0
MIN_INTERVAL = 1.0
DEFAULT_INTERVAL = 5.0
MAX_SEQS = 5
RESULT_CAP = 100  # 증권사 문서: 조건당 최대 100건
CODE_KEYS = ("code", "stck_shrn_iscd", "mksc_shrn_iscd", "jong_code", "stock_code")
NAME_KEYS = ("name", "hts_kor_isnm", "stock_name")
PRICE_KEYS = ("price", "stck_prpr")
RATE_KEYS = ("chgrate", "prdy_ctrt")
MARKET_OPEN_HHMM = (8, 0)
MARKET_CLOSE_HHMM = (20, 0)
PRINT_EVERY = 6  # 변화가 없을 때 이 횟수마다 한 줄 출력


def mask(text: str, secrets: set[str]) -> str:
    for s in sorted((s for s in secrets if s), key=len, reverse=True):
        text = text.replace(s, "***")
    return text


def _load_dotenv() -> None:
    env_file = REPO_ROOT / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def in_market_hours(now: datetime) -> bool:
    now = now.astimezone(KST)
    return now.weekday() < 5 and MARKET_OPEN_HHMM <= (now.hour, now.minute) < MARKET_CLOSE_HHMM


def _first(row: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for k in keys:
        if k in row and row[k] not in (None, ""):
            return row[k]
    return None


def row_code(row: dict[str, Any]) -> str | None:
    """종목코드 필드를 찾는다. 알려진 이름이 없으면 6자리 영숫자 값을 가진 첫 필드를 쓴다(필드 이름은 보고서에 그대로 나온다)."""
    v = _first(row, CODE_KEYS)
    if v is not None:
        return str(v).strip()
    for val in row.values():
        t = str(val).strip()
        if len(t) == 6 and t.isalnum() and t.upper() == t:
            return t
    return None


@dataclass
class SeqStats:
    seq: str
    title: str = ""
    polls: int = 0
    ok_polls: int = 0
    empty_polls: int = 0  # 증권사가 0건을 오류로 돌려준 횟수
    errors: dict[str, int] = field(default_factory=dict)
    latencies: list[float] = field(default_factory=list)
    counts: list[int] = field(default_factory=list)
    fields: list[str] = field(default_factory=list)
    sample: dict[str, Any] | None = None
    code_field_found: bool = True
    cap_hit: bool = False
    last_codes: set[str] | None = None
    changes: list[dict[str, Any]] = field(default_factory=list)  # {at(초), added, removed, count}
    first_ok_at: float | None = None
    last_empty_message: str = ""


def _sanitize(text: object, secrets: set[str], limit: int = 120) -> str:
    return mask(" ".join(str(text).split()), secrets)[:limit]


def _titles(body: dict[str, Any]) -> list[dict[str, Any]]:
    rows = body.get("output2") or body.get("output") or []
    return [r for r in rows if isinstance(r, dict)]


def _poll_once(
    client: Any, user_id: str, st: SeqStats, t0: float, clock: Callable[[], float], secrets: set[str], say: Callable[[str], None], poll_no: int
) -> None:
    st.polls += 1
    started = clock()
    try:
        body = client.psearch_result(user_id, st.seq)
    except KisError as exc:
        st.latencies.append(clock() - started)
        if exc.code == "UPSTREAM_ERROR" and getattr(exc, "http_status", None) in (None, 200):
            # 증권사 문서: 결과 0건이면 오류를 돌려준다(HTTP 200의 업무 거절). HTTP 4xx/5xx는 0건이 아니라 장애·인증 오류다. 다른 거절(조건 키 오류 등)과 같은 코드라 메시지를 함께 보여 준다.
            st.empty_polls += 1
            st.last_empty_message = _sanitize(exc, secrets)
            if st.last_codes:  # 직전까지 있던 종목이 모두 빠졌다
                st.changes.append({"at": round(clock() - t0, 1), "added": [], "removed": sorted(st.last_codes), "count": 0})
                say(f"  [{_stamp(clock)}] seq={st.seq} 0건(오류 응답) — 이탈 {len(st.last_codes)}건: {_join(sorted(st.last_codes))}")
                st.last_codes = set()
            elif poll_no == 1 or poll_no % PRINT_EVERY == 0:
                say(f"  [{_stamp(clock)}] seq={st.seq} 증권사 응답: {st.last_empty_message}")
        else:
            st.errors[exc.code] = st.errors.get(exc.code, 0) + 1
            say(f"  [{_stamp(clock)}] seq={st.seq} 오류 {exc.code}: {_sanitize(exc, secrets)}")
        return
    except Exception as exc:  # noqa: BLE001 — 한 번의 이상이 전체 관찰을 끊지 않게 한다
        st.latencies.append(clock() - started)
        st.errors[type(exc).__name__] = st.errors.get(type(exc).__name__, 0) + 1
        say(f"  [{_stamp(clock)}] seq={st.seq} 예외 {type(exc).__name__}: {_sanitize(exc, secrets)}")
        return
    st.latencies.append(clock() - started)
    rows = [r for r in (body.get("output2") or body.get("output") or []) if isinstance(r, dict)]
    st.ok_polls += 1
    if st.first_ok_at is None:
        st.first_ok_at = clock() - t0
    if rows and not st.fields:
        st.fields = list(rows[0].keys())
        st.sample = {k: _sanitize(v, secrets, 40) for k, v in rows[0].items()}
    codes = [row_code(r) for r in rows]
    if rows and any(c is None for c in codes):
        st.code_field_found = False
    cur = {c for c in codes if c}
    st.counts.append(len(rows))
    if len(rows) >= RESULT_CAP:
        st.cap_hit = True
    if st.last_codes is None:
        st.last_codes = cur
        say(f"  [{_stamp(clock)}] seq={st.seq} 첫 결과 {len(rows)}건 ({st.latencies[-1]:.2f}초): {_join(sorted(cur))}")
        return
    added, removed = sorted(cur - st.last_codes), sorted(st.last_codes - cur)
    if added or removed:
        st.changes.append({"at": round(clock() - t0, 1), "added": added, "removed": removed, "count": len(cur)})
        say(f"  [{_stamp(clock)}] seq={st.seq} {len(cur)}건 — 편입 {len(added)}건 {_join(added)} / 이탈 {len(removed)}건 {_join(removed)}")
    elif poll_no % PRINT_EVERY == 0:
        say(f"  [{_stamp(clock)}] seq={st.seq} {len(cur)}건 변화 없음 ({st.latencies[-1]:.2f}초)")
    st.last_codes = cur


def _stamp(clock: Callable[[], float]) -> str:
    return datetime.fromtimestamp(clock(), tz=KST).strftime("%H:%M:%S")


def _join(items: list[str], limit: int = 8) -> str:
    if not items:
        return "-"
    return ",".join(items[:limit]) + (f" 외 {len(items) - limit}" if len(items) > limit else "")


def _pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    vs = sorted(values)
    return vs[min(len(vs) - 1, int(round(q * (len(vs) - 1))))]


def run_check(
    client: Any,
    user_id: str,
    seqs: list[str],
    seconds: float,
    interval: float,
    *,
    list_only: bool = False,
    out_path: Path | None = None,
    secrets: set[str] | None = None,
    say: Callable[[str], None] = print,
    clock: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    secrets = set(secrets or ())
    secrets.add(user_id)
    now = datetime.fromtimestamp(clock(), tz=KST)
    market = in_market_hours(now)
    say(f"HTS 조건검색 연동 확인 — 현재 {now:%Y-%m-%d %H:%M:%S} (KST) · {'장 시간(08:00~20:00)' if market else '장 시간 밖(평일 08:00~20:00 아님): 결과는 오지만 장중 변화는 확인할 수 없습니다'}")

    # ── 1. 조건 목록 ───────────────────────────────────────────────────
    try:
        titles = _titles(client.psearch_titles(user_id))
    except KisError as exc:
        say(f"[실패] 조건 목록 조회: {exc.code} — {_sanitize(exc, secrets)}")
        say("  확인: ① .env의 KIS_HTS_ID가 내 HTS 로그인 ID인가 ② 앱키 계정과 HTS ID가 같은 고객인가 ③ HTS [0110]에서 조건을 '서버저장'했는가")
        return 1
    except Exception as exc:  # noqa: BLE001
        say(f"[실패] 조건 목록 조회 중 예외 {type(exc).__name__}: {_sanitize(exc, secrets)}")
        return 1
    say(f"조건 목록 {len(titles)}건:")
    for t in titles:
        say(f"  seq={t.get('seq', '?')}  그룹={_sanitize(t.get('grp_nm', ''), secrets, 30)}  조건명={_sanitize(t.get('condition_nm', ''), secrets, 40)}")
    if not titles:
        say("[확인필요] 조건이 하나도 없습니다. HTS(eFriend Plus) [0110] 조건검색에서 조건을 만들고 '서버저장'을 누른 뒤 다시 실행하세요.")
        return 2
    title_by_seq = {str(t.get("seq")): _sanitize(t.get("condition_nm", ""), secrets, 40) for t in titles}
    if list_only:
        say("완료(--list-only). 관찰하려면 --seq 번호를 지정해 다시 실행하세요.")
        return 0

    chosen = seqs or [str(titles[0].get("seq"))]
    for s in chosen:
        if s not in title_by_seq:
            say(f"[경고] seq={s} 는 조건 목록에 없습니다(그래도 조회는 시도합니다).")
    stats = {s: SeqStats(seq=s, title=title_by_seq.get(s, "")) for s in chosen}

    # ── 2. 반복 조회 ───────────────────────────────────────────────────
    say(f"조회 시작: seq={','.join(chosen)} · {interval:g}초 간격 · 최대 {seconds:g}초 (Ctrl+C로 중단하면 지금까지의 결과를 요약합니다)")
    t0 = clock()
    poll_no = 0
    try:
        while True:
            poll_no += 1
            for s in chosen:
                _poll_once(client, user_id, stats[s], t0, clock, secrets, say, poll_no)
            if clock() - t0 + interval > seconds:
                break
            sleep(interval)
    except KeyboardInterrupt:
        say("중단됨 — 지금까지의 결과를 요약합니다.")
    elapsed = clock() - t0
    return _report(say, stats, elapsed, interval, market, out_path, secrets)


def _report(say: Callable[[str], None], stats: dict[str, SeqStats], elapsed: float, interval: float, market: bool, out_path: Path | None, secrets: set[str]) -> int:
    problems: list[str] = []
    notices: list[str] = []
    say("")
    say(f"──── 요약 (관찰 {elapsed:.0f}초, 조회 간격 {interval:g}초) ────")
    any_ok = any(st.ok_polls for st in stats.values())
    any_change = False
    for st in stats.values():
        lat = st.latencies
        say(f"[seq={st.seq} {st.title}] 조회 {st.polls}회: 결과 수신 {st.ok_polls} · 0건(오류 응답) {st.empty_polls} · 기타 오류 {sum(st.errors.values())}")
        if lat:
            say(f"  응답 시간: 중앙값 {statistics.median(lat):.2f}초 · 95% {_pct(lat, 0.95):.2f}초 · 최대 {max(lat):.2f}초")
        if st.counts:
            say(f"  결과 종목 수: 최소 {min(st.counts)} · 최대 {max(st.counts)}")
        if st.fields:
            say(f"  응답 필드({len(st.fields)}개): {', '.join(st.fields)}")
            say(f"  첫 행 예시: {json.dumps(st.sample, ensure_ascii=False)}")
            if not any(k in st.fields for k in CODE_KEYS):
                notices.append(f"seq={st.seq}: 종목코드 필드 이름이 예상({'/'.join(CODE_KEYS)})과 달라 값 모양으로 추정했습니다 — 위 필드 목록을 확인하세요.")
            if not st.code_field_found:
                problems.append(f"seq={st.seq}: 종목코드를 찾지 못한 행이 있습니다.")
        if st.errors:
            say(f"  오류 종류: {', '.join(f'{k} {v}회' for k, v in sorted(st.errors.items()))}")
            if "RATE_LIMITED" in st.errors:
                notices.append(f"seq={st.seq}: 호출 한도(RATE_LIMITED)에 걸렸습니다 — --interval을 늘려 다시 확인하세요.")
        if st.cap_hit:
            notices.append(f"seq={st.seq}: 결과가 {RESULT_CAP}건 한도에 닿았습니다. 증권사가 조건당 {RESULT_CAP}건까지만 주므로 조건을 더 좁혀야 전체를 볼 수 있습니다.")
        if st.empty_polls and not st.ok_polls:
            notices.append(f"seq={st.seq}: 결과가 계속 0건(증권사 응답: {st.last_empty_message or '-'}). 조건이 장중에 아직 맞는 종목이 없거나, 조건 키(seq)가 잘못됐을 수 있습니다.")
        if st.changes:
            any_change = True
            first = st.changes[0]
            gaps = [round(b["at"] - a["at"], 1) for a, b in zip(st.changes, st.changes[1:], strict=False)]
            say(f"  ★ 결과가 {len(st.changes)}번 바뀜(첫 변화 {first['at']:g}초 뒤" + (f", 변화 사이 간격 {', '.join(f'{g:g}' for g in gaps[:6])}초" if gaps else "") + ") — 장중 편입·이탈이 API 조회로 반영됩니다.")
        elif st.ok_polls:
            say("  결과가 바뀌지 않았습니다.")
    if not any_ok:
        problems.append("결과를 한 번도 받지 못했습니다(위 오류 확인).")
    elif not any_change:
        if market:
            notices.append("관찰 시간 동안 결과가 바뀌지 않았습니다. 조건에 변동이 적을 수 있으니 --seconds를 늘리거나 변동이 큰 조건(예: 등락률·거래량 급증)으로 다시 확인하세요.")
        else:
            notices.append("장 시간 밖이라 변화를 확인할 수 없습니다. 평일 08:00~20:00(한국시간)에 다시 실행하세요.")
    if out_path is not None:
        report = {
            "generated_at": datetime.now(KST).isoformat(timespec="seconds"),
            "elapsed_seconds": round(elapsed, 1), "interval_seconds": interval, "market_hours": market,
            "sequences": {
                s.seq: {
                    "title": s.title, "polls": s.polls, "ok_polls": s.ok_polls, "empty_polls": s.empty_polls, "errors": s.errors,
                    "latency_median": round(statistics.median(s.latencies), 3) if s.latencies else None,
                    "latency_max": round(max(s.latencies), 3) if s.latencies else None,
                    "counts_min": min(s.counts) if s.counts else None, "counts_max": max(s.counts) if s.counts else None,
                    "fields": s.fields, "sample_row": s.sample, "cap_hit": s.cap_hit, "changes": s.changes,
                }
                for s in stats.values()
            },
        }
        try:
            out_path.write_text(mask(json.dumps(report, ensure_ascii=False, indent=2), secrets), encoding="utf-8")
            say(f"보고서 저장: {out_path}")
        except OSError as exc:
            notices.append(f"보고서를 저장하지 못했습니다: {exc.strerror or exc}")
    for n in notices:
        say(f"[확인필요] {n}")
    for p in problems:
        say(f"[실패] {p}")
    if problems:
        return 1
    if notices:
        say("완료(확인필요 있음).")
        return 2
    say("완료. HTS 조건검색 결과를 API로 받을 수 있고 장중 변화도 확인됐습니다.")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="한국투자증권 HTS 조건검색 결과 연동 확인 — 장중에 실행하세요.")
    ap.add_argument("--hts-id", default=None, help=f"HTS 로그인 ID(생략하면 환경변수/.env의 {HTS_ID_ENV})")
    ap.add_argument("--seq", action="append", default=[], help=f"관찰할 조건 키값(여러 번 지정 가능, 최대 {MAX_SEQS}개; 생략하면 목록의 첫 조건)")
    ap.add_argument("--list-only", action="store_true", help="조건 목록만 확인하고 끝낸다")
    ap.add_argument("--seconds", type=float, default=DEFAULT_SECONDS, help=f"관찰 시간(초, 기본 {DEFAULT_SECONDS:g}, 최대 {MAX_SECONDS:g})")
    ap.add_argument("--interval", type=float, default=DEFAULT_INTERVAL, help=f"조회 간격(초, 기본 {DEFAULT_INTERVAL:g}, 최소 {MIN_INTERVAL:g})")
    ap.add_argument("--out", default=None, help="요약을 JSON 파일로 저장(비밀값은 가려짐)")
    return ap


def main(argv: list[str] | None = None, env: dict[str, str] | None = None, client_factory: Callable[[cfg.IntradaySettings], Any] | None = None, **run_kw: Any) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    try:
        args = _build_parser().parse_args(argv)
    except SystemExit as exc:  # argparse의 오류 종료 코드 2는 "확인필요"와 겹치므로 1로 바꾼다
        return 0 if exc.code == 0 else 1
    if not (0 < args.seconds <= MAX_SECONDS):
        print(f"[설정 오류] --seconds는 0보다 크고 {MAX_SECONDS:g} 이하여야 합니다.")
        return 1
    if args.interval < MIN_INTERVAL:
        print(f"[설정 오류] --interval은 {MIN_INTERVAL:g}초 이상이어야 합니다(증권사 호출 한도 보호).")
        return 1
    if len(args.seq) > MAX_SEQS or any((not s.strip()) or len(s) > 10 or not s.isalnum() for s in args.seq):
        print(f"[설정 오류] --seq는 영숫자 조건 키값이며 최대 {MAX_SEQS}개까지 지정할 수 있습니다.")
        return 1
    if env is None:
        _load_dotenv()
        env = dict(os.environ)
    env = dict(env)
    env[cfg.ENABLED_ENV] = "true"
    hts_id = (args.hts_id or env.get(HTS_ID_ENV) or "").strip()
    if not hts_id:
        print(f"[설정 오류] HTS ID가 없습니다. .env에 {HTS_ID_ENV}=내HTS아이디 를 넣거나 --hts-id 로 지정하세요.")
        return 1
    try:
        settings = cfg.get_settings(env)
    except cfg.IntradayConfigError as exc:
        print(f"[설정 오류] {exc}")
        return 1
    if not settings.configured:
        print("[설정 오류] KIS_APP_KEY / KIS_APP_SECRET 이 설정되지 않았습니다(.env 확인).")
        return 1
    client = (client_factory or KisClient)(settings)
    secrets = {s for s in (settings.app_key, settings.app_secret, hts_id) if s}
    out_path = Path(args.out) if args.out else None
    return run_check(client, hts_id, [s.strip() for s in args.seq], args.seconds, args.interval, list_only=args.list_only, out_path=out_path, secrets=secrets, **run_kw)


if __name__ == "__main__":
    raise SystemExit(main())
