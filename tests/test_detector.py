"""Unit tests for detector — no MT5 required."""
import sys
import os
from datetime import datetime, timezone

import pandas as pd
import pytest

# Make detector importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "detector"))


# ── FVG tests ──────────────────────────────────────────────────────────────────

from indicators.fvg import detect_fvg, FVG


def _make_df(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df["time"] = pd.to_datetime(df.get("time", [datetime.now(tz=timezone.utc)] * len(df)))
    return df


def test_bullish_fvg_detected():
    df = _make_df([
        {"open": 100, "high": 101, "low": 99,  "close": 100},  # c1
        {"open": 101, "high": 105, "low": 100, "close": 104},  # c2 impulse up
        {"open": 104, "high": 106, "low": 102, "close": 105},  # c3 — low 102 > c1 high 101 ✓
    ])
    fvgs = detect_fvg(df, min_size_pips=1.0)
    assert len(fvgs) == 1
    assert fvgs[0].type == "BULLISH"
    assert fvgs[0].bottom == pytest.approx(101.0)
    assert fvgs[0].top == pytest.approx(102.0)


def test_bearish_fvg_detected():
    df = _make_df([
        {"open": 105, "high": 106, "low": 104, "close": 105},  # c1
        {"open": 104, "high": 104, "low": 100, "close": 101},  # c2 impulse down
        {"open": 101, "high": 103, "low": 100, "close": 100},  # c3 — high 103 < c1 low 104 ✓
    ])
    fvgs = detect_fvg(df, min_size_pips=1.0)
    assert len(fvgs) == 1
    assert fvgs[0].type == "BEARISH"


def test_no_fvg_when_candles_overlap():
    df = _make_df([
        {"open": 100, "high": 103, "low": 99,  "close": 102},
        {"open": 102, "high": 105, "low": 101, "close": 104},
        {"open": 104, "high": 106, "low": 102, "close": 105},  # c3 low 102 == c1 high 103 — no gap
    ])
    fvgs = detect_fvg(df, min_size_pips=1.0)
    assert len(fvgs) == 0


def test_fvg_too_small_filtered():
    df = _make_df([
        {"open": 100, "high": 100.5, "low": 99, "close": 100},
        {"open": 100.5, "high": 103, "low": 100, "close": 102},
        {"open": 102, "high": 104, "low": 100.7, "close": 103},  # gap = 0.2 pips
    ])
    fvgs = detect_fvg(df, min_size_pips=3.0)
    assert len(fvgs) == 0


# ── Structure tests ────────────────────────────────────────────────────────────

from indicators.structure import find_swings, determine_bias


def _trending_up_df(n: int = 30) -> pd.DataFrame:
    # Explicit HH/HL zigzag so find_swings(lookback=3) detects clear pivots.
    # Monotonic series have no local extrema — no swings → NEUTRAL bias.
    heights = [
        102, 100, 98, 96, 94,    # declining to swing low 1
        92,                      # swing low 1  (index 5)
        95, 98, 101, 104, 107,   # rising
        110,                     # swing high 1 (index 11)
        107, 104, 101, 98,       # pullback
        96,                      # swing low 2  (index 16, HL: 96 > 92)
        99, 102, 105, 108, 111,
        114,                     # swing high 2 (index 22, HH: 114 > 110)
        111, 108, 105,
    ]
    rows = [{"open": h, "high": h + 2, "low": h - 2, "close": h} for h in heights]
    return _make_df(rows)


def _trending_down_df(n: int = 30) -> pd.DataFrame:
    # Explicit LH/LL zigzag so find_swings(lookback=3) detects clear pivots.
    heights = [
        98, 100, 102, 104, 106,  # rising to swing high 1
        108,                     # swing high 1 (index 5)
        105, 102, 99, 96, 93,    # dropping
        90,                      # swing low 1  (index 11)
        93, 96, 99, 102,         # bounce
        104,                     # swing high 2 (index 16, LH: 104 < 108)
        101, 98, 95, 92, 89,
        86,                      # swing low 2  (index 22, LL: 86 < 90)
        89, 92, 95,
    ]
    rows = [{"open": h, "high": h + 2, "low": h - 2, "close": h} for h in heights]
    return _make_df(rows)


def test_bullish_bias_detected():
    df = _trending_up_df()
    swings = find_swings(df, lookback=3)
    bias = determine_bias(swings)
    assert bias == "BULLISH"


def test_bearish_bias_detected():
    df = _trending_down_df()
    swings = find_swings(df, lookback=3)
    bias = determine_bias(swings)
    assert bias == "BEARISH"


# ── Fibonacci tests ────────────────────────────────────────────────────────────

from indicators.fibonacci import FibLevels, compute_fib_from_sweep


def test_ote_zone_bullish():
    fib = compute_fib_from_sweep(sweep_low=1800.0, swing_high=1900.0)
    # OTE zone for BULLISH retracement (range=100):
    #   upper bound (0.618): 1900 - 61.8 = 1838.2
    #   lower bound (0.786): 1900 - 78.6 = 1821.4
    # 1840.0 is ABOVE the zone (59% retracement — too shallow) — original test was wrong.
    assert fib.is_in_ote(1830.0)         # 70% retracement — inside OTE ✓
    assert not fib.is_in_ote(1870.0)     # 30% retracement — above OTE (too shallow)
    assert not fib.is_in_ote(1810.0)     # 90% retracement — below OTE (too deep)


def test_equilibrium():
    fib = FibLevels(swing_high=2000, swing_low=1800, direction="BULLISH")
    assert fib.equilibrium == pytest.approx(1900.0)


# ── Killzone tests ─────────────────────────────────────────────────────────────

from strategy.killzone import get_active_killzone
import pytz


def test_ny_am_killzone():
    dt = datetime(2024, 1, 15, 14, 30, tzinfo=pytz.utc)  # 14:30 UTC = NY AM
    kz = get_active_killzone(dt)
    assert kz == "NY_AM"


def test_london_killzone():
    dt = datetime(2024, 1, 15, 8, 0, tzinfo=pytz.utc)   # 08:00 UTC = London
    kz = get_active_killzone(dt)
    assert kz == "LONDON"


def test_outside_killzone():
    dt = datetime(2024, 1, 15, 11, 30, tzinfo=pytz.utc)  # 11:30 UTC = dead zone
    kz = get_active_killzone(dt)
    assert kz is None


# ── Webhook signing test ───────────────────────────────────────────────────────

from webhook import _sign


def test_hmac_sign_deterministic():
    payload = b'{"tier": "S", "direction": "LONG"}'
    sig1 = _sign(payload, "test-secret-key-32chars-abcdefgh")
    sig2 = _sign(payload, "test-secret-key-32chars-abcdefgh")
    assert sig1 == sig2


def test_hmac_sign_different_secret():
    payload = b'{"tier": "S"}'
    sig1 = _sign(payload, "secret-aaa")
    sig2 = _sign(payload, "secret-bbb")
    assert sig1 != sig2
