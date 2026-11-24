"""QQQ 변동성 타깃 전략 계산 (표준 라이브러리만 사용).

- r      = 오늘 QQQ 수정종가 / 어제 수정종가 - 1
- hv     = 최근 20개 r의 모집단 표준편차 × √252
- tv_hv  = hv × √(365/252) × 100   (TradingView HV(20) 표시값)
- w      = min(1, 0.125 / hv)      (= 15 / tv_hv)
- 신호   = 매주 마지막 거래일(보통 금요일) 종가 기준 확정
"""
from __future__ import annotations

import math
from datetime import date, datetime, time, timedelta

HV_WINDOW = 20
ANNUAL = 252
TARGET_VOL = 0.125
SMA_WINDOW = 250
REBALANCE_BAND = 0.10
TV_FACTOR = math.sqrt(365 / 252)
MARKET_CLOSE_ET = time(16, 30)  # 종가 확정으로 보는 시각(여유 포함)


def pstdev(xs: list[float]) -> float:
    n = len(xs)
    m = sum(xs) / n
    return math.sqrt(sum((x - m) ** 2 for x in xs) / n)


def target_weight(hv: float) -> float:
    if hv <= 0:
        return 1.0
    return min(1.0, TARGET_VOL / hv)


def compute_series(rows: list[tuple[date, float, float]]) -> list[dict]:
    """rows: (날짜, 종가, 수정종가) — 날짜 오름차순, 거래일만.

    결측(None/0 이하) 행은 제거하고, 남은 연속 거래일 사이로 수익률을 계산한다.
    """
    clean = sorted(
        {d: (c, a) for d, c, a in rows if a is not None and a > 0 and c is not None and c > 0}.items()
    )
    out = []
    rets: list[float] = []
    closes: list[float] = []
    prev_adj = None
    for d, (close, adj) in clean:
        if prev_adj is not None:
            rets.append(adj / prev_adj - 1)
        prev_adj = adj
        closes.append(close)
        row = {"date": d.isoformat(), "close": round(close, 4), "adjclose": round(adj, 6)}
        if len(rets) >= HV_WINDOW:
            hv = pstdev(rets[-HV_WINDOW:]) * math.sqrt(ANNUAL)
            row["hv"] = round(hv, 6)
            row["tv_hv"] = round(hv * TV_FACTOR * 100, 4)
            row["w"] = round(target_weight(hv), 6)
        if len(closes) >= SMA_WINDOW:
            sma = sum(closes[-SMA_WINDOW:]) / SMA_WINDOW
            row["sma250"] = round(sma, 4)
            row["above_sma"] = close > sma
            row["sma_gap_pct"] = round((close / sma - 1) * 100, 4)
        out.append(row)
    return out


def week_key(d: date) -> tuple[int, int]:
    iso = d.isocalendar()
    return (iso[0], iso[1])


def week_friday(d: date) -> date:
    return d + timedelta(days=4 - d.weekday())


def week_complete(last_trading_day: date, now_et: datetime, has_later_data: bool) -> bool:
    """해당 주가 끝났는지(=신호 확정 가능한지)."""
    if has_later_data:
        return True
    fri = week_friday(last_trading_day)
    return now_et >= datetime.combine(fri, MARKET_CLOSE_ET, tzinfo=now_et.tzinfo)


def weekly_signals(series: list[dict], now_et: datetime) -> list[dict]:
    """주별 마지막 거래일을 신호일로 잡아 확정 신호 목록을 만든다.

    금요일이 휴장이면 그 주 마지막 거래일(예: 목요일)이 신호일이 된다.
    아직 끝나지 않은 이번 주는 제외한다.
    """
    by_week: dict[tuple[int, int], dict] = {}
    order: list[tuple[int, int]] = []
    for row in series:
        if "hv" not in row:
            continue
        k = week_key(date.fromisoformat(row["date"]))
        if k not in by_week:
            order.append(k)
        by_week[k] = row
    out = []
    for i, k in enumerate(order):
        row = by_week[k]
        d = date.fromisoformat(row["date"])
        if not week_complete(d, now_et, has_later_data=i < len(order) - 1):
            continue
        sig = {
            "date": row["date"],
            "weekday": d.weekday(),
            "hv": row["hv"],
            "tv_hv": row["tv_hv"],
            "w": row["w"],
            "close": row["close"],
        }
        for key in ("sma250", "above_sma", "sma_gap_pct"):
            if key in row:
                sig[key] = row[key]
        if out:
            sig["prev_w"] = out[-1]["w"]
            sig["delta_w"] = round(row["w"] - out[-1]["w"], 6)
        out.append(sig)
    return out


def rebalance(qld_value: float, total: float, w: float, band: float = REBALANCE_BAND) -> dict:
    """|실제 - 목표| ≥ band 일 때만 정확히 w로 조정 (웹 화면 로직과 동일)."""
    actual = qld_value / total if total > 0 else 0.0
    diff = actual - w
    act = abs(diff) >= band - 1e-9
    return {
        "actual": actual,
        "target": w,
        "diff": diff,
        "rebalance": act,
        "new_weight": w if act else actual,
        "qld_trade_value": (w * total - qld_value) if act else 0.0,
    }
