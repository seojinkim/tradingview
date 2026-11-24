"""QQQ/QLD/SGOV 일봉을 받아 지표를 계산하고 data/*.json 으로 저장한다.

데이터 소스: Yahoo Finance chart API → 실패 시 Stooq CSV.
둘 다 실패하면 기존 데이터를 유지하고 "stale": true 로 표시한다.
표준 라이브러리만 사용 (pip 설치 불필요).
"""
from __future__ import annotations

import csv
import io
import json
import os
import sys
import time as _time
import urllib.request
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(__file__))
import strategy  # noqa: E402

ET = ZoneInfo("America/New_York")
KST = ZoneInfo("Asia/Seoul")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
TICKERS = ["QQQ", "QLD", "SGOV"]
UA = "Mozilla/5.0"  # 상세 브라우저 UA는 Yahoo가 429로 거부하는 경우가 있음
HISTORY_DAYS = 2 * 252 + 10  # 화면 차트용 약 2년치


def http_get(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def parse_yahoo(raw: bytes) -> list[tuple[date, float, float]]:
    j = json.loads(raw)
    res = j["chart"]["result"][0]
    tz = ZoneInfo(res["meta"].get("exchangeTimezoneName") or "America/New_York")
    ts = res.get("timestamp") or []
    closes = res["indicators"]["quote"][0].get("close") or []
    adj_list = res["indicators"].get("adjclose") or [{}]
    adjs = adj_list[0].get("adjclose") or closes
    rows = []
    for t, c, a in zip(ts, closes, adjs):
        if c is None:
            continue
        d = datetime.fromtimestamp(t, tz).date()
        rows.append((d, float(c), float(a if a is not None else c)))
    if len(rows) < 30:
        raise ValueError(f"Yahoo: 데이터 부족 ({len(rows)}행)")
    return rows


def parse_stooq(raw: bytes) -> list[tuple[date, float, float]]:
    text = raw.decode("utf-8", "replace")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or "Close" not in reader.fieldnames:
        raise ValueError("Stooq: CSV 형식 아님")
    rows = []
    for r in reader:
        try:
            d = date.fromisoformat(r["Date"])
            c = float(r["Close"])
        except (ValueError, KeyError, TypeError):
            continue
        rows.append((d, c, c))  # Stooq 종가는 분할·배당 조정값
    if len(rows) < 30:
        raise ValueError(f"Stooq: 데이터 부족 ({len(rows)}행)")
    return rows


def fetch_yahoo(sym: str) -> list[tuple[date, float, float]]:
    last = None
    for host in ("query1", "query2"):
        url = f"https://{host}.finance.yahoo.com/v8/finance/chart/{sym}?range=3y&interval=1d&events=div%2Csplit"
        for attempt in range(2):
            try:
                return parse_yahoo(http_get(url))
            except Exception as e:  # noqa: BLE001
                last = e
                _time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Yahoo 실패: {last}")


def fetch_stooq(sym: str) -> list[tuple[date, float, float]]:
    d1 = (date.today().replace(year=date.today().year - 3)).strftime("%Y%m%d")
    url = f"https://stooq.com/q/d/l/?s={sym.lower()}.us&i=d&d1={d1}"
    return parse_stooq(http_get(url))


def drop_unfinished_bar(rows, now_et: datetime):
    """장중에 실행되면 아직 확정되지 않은 오늘 봉을 버린다."""
    if rows and rows[-1][0] >= now_et.date() and now_et.time() < strategy.MARKET_CLOSE_ET:
        return rows[:-1]
    return rows


def fetch(sym: str, now_et: datetime):
    errors = []
    for name, fn in (("yahoo", fetch_yahoo), ("stooq", fetch_stooq)):
        try:
            rows = drop_unfinished_bar(fn(sym), now_et)
            return rows, name, errors
        except Exception as e:  # noqa: BLE001
            errors.append(f"{sym}/{name}: {e}")
    return None, None, errors


def load_json(path: str, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path: str, obj) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, path)


def build(now_utc: datetime | None = None) -> int:
    now_utc = now_utc or datetime.now(timezone.utc)
    now_et = now_utc.astimezone(ET)
    os.makedirs(DATA_DIR, exist_ok=True)
    latest_path = os.path.join(DATA_DIR, "latest.json")
    history_path = os.path.join(DATA_DIR, "history.json")
    old_latest = load_json(latest_path, {})
    old_history = load_json(history_path, {})

    fetched, sources, errors = {}, {}, []
    for sym in TICKERS:
        rows, src, errs = fetch(sym, now_et)
        errors += errs
        if rows:
            fetched[sym], sources[sym] = rows, src
        print(f"{sym}: {src or '실패'} {len(rows) if rows else 0}행", file=sys.stderr)

    generated = now_utc.isoformat(timespec="seconds")
    if "QQQ" not in fetched:
        # 핵심 데이터 실패 → 기존 데이터 유지
        latest = old_latest or {}
        latest.update({
            "stale": True,
            "last_attempt": generated,
            "errors": errors,
        })
        latest.setdefault("last_success", None)
        write_json(latest_path, latest)
        if not old_history:
            write_json(history_path, {"daily": [], "weekly": []})
        print("QQQ 데이터 수집 실패 — 기존 데이터 유지(stale)", file=sys.stderr)
        return 0

    series = strategy.compute_series(fetched["QQQ"])
    weekly = strategy.weekly_signals(series, now_et)
    today = series[-1]

    prices = {}
    old_prices = old_latest.get("prices", {})
    partial_stale = False
    for sym in TICKERS:
        if sym in fetched:
            d, c, _ = fetched[sym][-1]
            prices[sym] = {"date": d.isoformat(), "close": round(c, 4), "source": sources[sym]}
        elif sym in old_prices:
            prices[sym] = dict(old_prices[sym], stale=True)
            partial_stale = True
        else:
            partial_stale = True

    signal = weekly[-1] if weekly else None
    latest = {
        "generated_at": generated,
        "generated_at_kst": now_utc.astimezone(KST).strftime("%Y-%m-%d %H:%M"),
        "last_success": generated,
        "data_date": today["date"],
        "stale": partial_stale,
        "errors": errors,
        "sources": sources,
        "prices": prices,
        "today": {**today, "leverage": round(today["w"] * 2, 6)},
        "signal": signal and {**signal, "leverage": round(signal["w"] * 2, 6)},
        "params": {
            "hv_window": strategy.HV_WINDOW,
            "target_vol": strategy.TARGET_VOL,
            "band": strategy.REBALANCE_BAND,
            "sma_window": strategy.SMA_WINDOW,
        },
    }
    daily = [
        {k: r[k] for k in ("date", "close", "tv_hv", "w", "sma250", "above_sma") if k in r}
        for r in series[-HISTORY_DAYS:]
        if "tv_hv" in r
    ]
    history = {"generated_at": generated, "daily": daily, "weekly": weekly[-110:]}
    write_json(latest_path, latest)
    write_json(history_path, history)
    print(f"완료: {today['date']} TV HV {today['tv_hv']:.2f}, w {today['w']:.1%}; "
          f"신호 {signal and signal['date']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(build())
