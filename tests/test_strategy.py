import csv
import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest import mock
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

import fetch_data  # noqa: E402
import strategy  # noqa: E402

ET = ZoneInfo("America/New_York")
KST = ZoneInfo("Asia/Seoul")


def load_fixture():
    with open(os.path.join(HERE, "fixtures", "qqq_yahoo_2026H2.csv")) as f:
        return [(date.fromisoformat(r["date"]), float(r["close"]), float(r["adjclose"]))
                for r in csv.DictReader(f)]


def by_date(series):
    return {r["date"]: r for r in series}


def synthetic(start: date, n: int, skip=()):
    """평일만 n개 거래일 생성 (skip 날짜는 휴장)."""
    rows, d, i, px = [], start, 0, 100.0
    while len(rows) < n:
        if d.weekday() < 5 and d not in skip:
            px *= 1 + (0.01 if i % 2 == 0 else -0.008)
            rows.append((d, px, px))
            i += 1
        d += timedelta(days=1)
    return rows


class TestKnownValues(unittest.TestCase):
    """실제 QQQ 수정종가(Yahoo) 기준 검증값."""

    @classmethod
    def setUpClass(cls):
        cls.s = by_date(strategy.compute_series(load_fixture()))

    def check(self, d, hv_pct, tv, w_pct):
        r = self.s[d]
        self.assertAlmostEqual(r["hv"] * 100, hv_pct, delta=0.1)
        self.assertAlmostEqual(r["tv_hv"], tv, delta=0.1)
        self.assertAlmostEqual(r["w"] * 100, w_pct, delta=0.5)
        # w = 12.5% / hv. "15 / TV HV"는 근사(정확히는 12.5×√(365/252)=15.04)
        self.assertAlmostEqual(r["w"], min(1, 0.125 / r["hv"]), places=5)
        self.assertAlmostEqual(r["w"] * 100, 15 / r["tv_hv"] * 100, delta=0.15)

    def test_2026_11_20_friday(self):
        self.check("2026-11-20", 38.8, 46.7, 32)

    def test_2026_11_23_monday(self):
        self.check("2026-11-23", 46.8, 56.3, 27)


class TestWeeklySignal(unittest.TestCase):
    def test_confirmed_signal_is_friday_monday_not_confirmed(self):
        series = strategy.compute_series(load_fixture())
        now = datetime(2026, 11, 24, 8, 10, tzinfo=KST).astimezone(ET)
        sigs = strategy.weekly_signals(series, now)
        self.assertEqual(sigs[-1]["date"], "2026-11-20")
        self.assertAlmostEqual(sigs[-1]["w"] * 100, 32, delta=0.5)
        self.assertIn("delta_w", sigs[-1])
        self.assertTrue(all(date.fromisoformat(s["date"]).weekday() == 4 or
                            date.fromisoformat(s["date"]).weekday() < 4 for s in sigs))

    def test_friday_holiday_uses_last_trading_day(self):
        good_friday = date(2026, 4, 3)
        rows = synthetic(date(2026, 1, 5), 70, skip={good_friday})
        series = strategy.compute_series(rows)
        now = datetime(2026, 4, 20, 20, 0, tzinfo=ET)
        sigs = {s["date"]: s for s in strategy.weekly_signals(series, now)}
        self.assertIn("2026-04-02", sigs)       # 목요일이 신호일
        self.assertNotIn("2026-04-03", sigs)
        self.assertEqual(sigs["2026-04-02"]["weekday"], 3)

    def test_friday_holiday_confirmed_on_friday_evening(self):
        good_friday = date(2026, 4, 3)
        rows = [r for r in synthetic(date(2026, 1, 5), 70, skip={good_friday})
                if r[0] <= date(2026, 4, 2)]
        series = strategy.compute_series(rows)
        before = datetime(2026, 4, 3, 10, 0, tzinfo=ET)
        after = datetime(2026, 4, 3, 19, 10, tzinfo=ET)  # 토요일 08:10 KST
        self.assertNotEqual(strategy.weekly_signals(series, before)[-1]["date"], "2026-04-02")
        self.assertEqual(strategy.weekly_signals(series, after)[-1]["date"], "2026-04-02")

    def test_incomplete_week_excluded(self):
        rows = [r for r in synthetic(date(2026, 1, 5), 60) if r[0] <= date(2026, 3, 25)]  # 수요일
        series = strategy.compute_series(rows)
        now = datetime(2026, 3, 25, 19, 0, tzinfo=ET)
        self.assertEqual(strategy.weekly_signals(series, now)[-1]["date"], "2026-03-20")


class TestDataHandling(unittest.TestCase):
    def test_missing_values_dropped(self):
        rows = synthetic(date(2026, 1, 5), 40)
        broken = list(rows)
        broken[10] = (broken[10][0], None, None)
        broken.insert(5, rows[5])  # 중복 행
        s = strategy.compute_series(broken)
        self.assertEqual(len(s), 39)
        self.assertNotIn(rows[10][0].isoformat(), by_date(s))
        self.assertTrue(all(r.get("hv", 0) >= 0 for r in s))

    def test_hv_needs_21_prices(self):
        s = strategy.compute_series(synthetic(date(2026, 1, 5), 21))
        self.assertNotIn("hv", s[19])
        self.assertIn("hv", s[20])

    def test_sma250(self):
        s = strategy.compute_series(synthetic(date(2025, 1, 6), 260))
        self.assertNotIn("sma250", s[248])
        self.assertIn("sma250", s[249])
        last = s[-1]
        self.assertEqual(last["above_sma"], last["close"] > last["sma250"])

    def test_drop_unfinished_bar(self):
        rows = synthetic(date(2026, 1, 5), 30)
        d = rows[-1][0]
        intraday = datetime.combine(d, datetime.min.time(), ET).replace(hour=11)
        self.assertEqual(len(fetch_data.drop_unfinished_bar(rows, intraday)), 29)
        evening = intraday.replace(hour=18)
        self.assertEqual(len(fetch_data.drop_unfinished_bar(rows, evening)), 30)

    def test_parse_stooq(self):
        lines = ["Date,Open,High,Low,Close,Volume"]
        lines += [f"{(date(2026,1,1)+timedelta(days=i)).isoformat()},1,1,1,{100+i},10" for i in range(40)]
        rows = fetch_data.parse_stooq("\n".join(lines).encode())
        self.assertEqual(len(rows), 40)
        self.assertEqual(rows[0][2], 100.0)
        with self.assertRaises(ValueError):
            fetch_data.parse_stooq(b"No data")

    def test_parse_yahoo_with_nulls(self):
        ts = [int(datetime(2026, 1, 5, 14, 30, tzinfo=timezone.utc).timestamp()) + 86400 * i for i in range(40)]
        closes = [100 + i for i in range(40)]
        closes[3] = None
        raw = json.dumps({"chart": {"result": [{
            "meta": {"exchangeTimezoneName": "America/New_York"},
            "timestamp": ts,
            "indicators": {"quote": [{"close": closes}], "adjclose": [{"adjclose": closes}]},
        }]}}).encode()
        rows = fetch_data.parse_yahoo(raw)
        self.assertEqual(len(rows), 39)


class TestRebalance(unittest.TestCase):
    def test_hold_when_within_band(self):
        r = strategy.rebalance(65, 100, 0.58)
        self.assertFalse(r["rebalance"])
        self.assertAlmostEqual(r["new_weight"], 0.65)

    def test_adjust_to_exact_target(self):
        r = strategy.rebalance(65, 100, 0.54)
        self.assertTrue(r["rebalance"])
        self.assertAlmostEqual(r["new_weight"], 0.54)
        self.assertAlmostEqual(r["qld_trade_value"], -11)

    def test_exact_10pp_triggers(self):
        self.assertTrue(strategy.rebalance(65, 100, 0.55)["rebalance"])


class TestStaleFallback(unittest.TestCase):
    def test_all_sources_fail_keeps_old_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = {"stale": False, "last_success": "2026-11-21T23:10:00+00:00",
                   "today": {"date": "2026-11-21", "tv_hv": 46.7}}
            with open(os.path.join(tmp, "latest.json"), "w") as f:
                json.dump(old, f)
            with mock.patch.object(fetch_data, "DATA_DIR", tmp), \
                 mock.patch.object(fetch_data, "fetch_yahoo", side_effect=RuntimeError("down")), \
                 mock.patch.object(fetch_data, "fetch_stooq", side_effect=RuntimeError("down")):
                fetch_data.build(datetime(2026, 11, 24, 23, 10, tzinfo=timezone.utc))
            with open(os.path.join(tmp, "latest.json")) as f:
                new = json.load(f)
            self.assertTrue(new["stale"])
            self.assertEqual(new["last_success"], old["last_success"])
            self.assertEqual(new["today"]["tv_hv"], 46.7)
            self.assertTrue(new["errors"])

    def test_yahoo_fails_stooq_used(self):
        rows = load_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(fetch_data, "DATA_DIR", tmp), \
                 mock.patch.object(fetch_data, "fetch_yahoo", side_effect=RuntimeError("down")), \
                 mock.patch.object(fetch_data, "fetch_stooq", return_value=rows):
                fetch_data.build(datetime(2026, 11, 23, 23, 10, tzinfo=timezone.utc))
            with open(os.path.join(tmp, "latest.json")) as f:
                new = json.load(f)
            self.assertFalse(new["stale"])
            self.assertEqual(new["sources"]["QQQ"], "stooq")
            self.assertEqual(new["signal"]["date"], "2026-11-20")
            self.assertEqual(new["today"]["date"], "2026-11-23")


if __name__ == "__main__":
    unittest.main()
