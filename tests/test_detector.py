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
    # 4 candles required: c1/c2/c3 form the FVG, c4 is the current forming candle (excluded).
    df = _make_df([
        {"open": 100, "high": 101, "low": 99,  "close": 100},  # c1
        {"open": 101, "high": 105, "low": 100, "close": 104},  # c2 impulse up
        {"open": 104, "high": 106, "low": 102, "close": 105},  # c3 — low 102 > c1 high 101 ✓
        {"open": 105, "high": 107, "low": 104, "close": 106},  # c4 forming (excluded)
    ])
    fvgs = detect_fvg(df, min_size_pips=1.0)
    assert len(fvgs) == 1
    assert fvgs[0].type == "BULLISH"
    assert fvgs[0].bottom == pytest.approx(101.0)
    assert fvgs[0].top == pytest.approx(102.0)


def test_bearish_fvg_detected():
    # 4 candles required: c1/c2/c3 form the FVG, c4 is the current forming candle (excluded).
    df = _make_df([
        {"open": 105, "high": 106, "low": 104, "close": 105},  # c1
        {"open": 104, "high": 104, "low": 100, "close": 101},  # c2 impulse down
        {"open": 101, "high": 103, "low": 100, "close": 100},  # c3 — high 103 < c1 low 104 ✓
        {"open": 100, "high": 101, "low": 99,  "close": 100},  # c4 forming (excluded)
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


# ── Structure break / CHoCH regression tests ──────────────────────────────────

from indicators.structure import (
    find_swings, detect_structure_breaks, get_recent_choch,
    get_recent_structure_break, Swing,
)


def _make_trending_df_with_break() -> tuple[pd.DataFrame, list[Swing]]:
    """
    200 candles of a BULLISH trend followed by a clear bullish structure break
    in the last 10 candles.  The final swing high is broken by the last candle.

    Layout (prices):
      candles 0-189: zigzag around 3300 — establishes swings with positional
                     indices 0-189 in the FULL df.
      candle 190:    swing high at 3320 (the level that will be broken)
      candles 191-198: retrace to ~3310
      candle 199:    closes at 3325, breaking above the 3320 swing high → BOS/break
    """
    rows = []
    base = 3300.0
    # Build 190 candles of zigzag
    for i in range(190):
        wave = 5.0 * (1 if (i // 5) % 2 == 0 else -1)
        p = base + wave + i * 0.01  # slight upward drift
        rows.append({"open": p, "high": p + 2, "low": p - 2, "close": p})
    # candle 190: local swing high at 3320
    rows.append({"open": 3318, "high": 3322, "low": 3316, "close": 3319})
    # candles 191-198: retrace
    for j in range(8):
        p = 3310.0 - j * 0.1
        rows.append({"open": p, "high": p + 1, "low": p - 1, "close": p})
    # candle 199: breaks above 3320 closing at 3325
    rows.append({"open": 3320, "high": 3326, "low": 3319, "close": 3325})

    df = _make_df(rows)
    swings = find_swings(df, lookback=3)
    return df, swings


def test_structure_break_in_bias_direction_detected():
    """
    Regression for Tier S contradiction: with H1 bias BULLISH the old code called
    get_recent_choch(df, swings, bias="BULLISH"). Because detect_structure_breaks
    labels a break in the direction of current_bias as BOS (not CHoCH), the result
    was always None when bias was already aligned — making Tier S step 4 impossible.

    get_recent_structure_break ignores the BOS/CHoCH label and should find the break.
    """
    df, swings = _make_trending_df_with_break()

    # New function: must find the bullish break in the last 15 candles.
    sb = get_recent_structure_break(df, swings, "BULLISH", lookback_candles=15)
    assert sb is not None, "get_recent_structure_break should detect the bullish break"
    assert sb.direction == "BULLISH"

    # Old function with bias="BULLISH": documents the original bug — it returned None
    # because the break was labeled BOS, not CHoCH.
    old_result = get_recent_choch(df, swings, "BULLISH", lookback_candles=15)
    assert old_result is None, (
        "get_recent_choch(bias='BULLISH') should return None when the break is a BOS "
        "(break in bias direction) — this documents the Tier S logical impossibility"
    )


def test_get_recent_choch_index_alignment():
    """
    Regression for the slicing bug: the old code did df.iloc[-lookback:] before
    calling detect_structure_breaks, but swing.index values are positional indices
    into the FULL df. After slicing, loop index i ∈ [0, lookback) while swing.index
    values are ≥ 150+, so swings never became 'active' and breaks were never detected.

    The fixed version runs on the full df and filters by candle_idx afterwards.

    Strategy: build a 200-candle df with a clear swing HIGH at index ~155 (well into
    the full df), then a bullish break of that swing in the last 10 candles.
    Use bias="NEUTRAL" so the break is labeled CHoCH regardless of direction.
    """
    rows = []
    # candles 0-149: flat at 3300 — no swings, just filler to push indices up
    for _ in range(150):
        rows.append({"open": 3300, "high": 3302, "low": 3298, "close": 3300})
    # candles 150-152: rise to swing high candidate
    rows.append({"open": 3300, "high": 3305, "low": 3299, "close": 3304})
    rows.append({"open": 3304, "high": 3308, "low": 3303, "close": 3307})
    # candle 152: isolated swing HIGH — higher than neighbours on both sides
    rows.append({"open": 3307, "high": 3315, "low": 3306, "close": 3308})  # idx=152, high=3315
    # candles 153-155: drop away so pivot is confirmed
    rows.append({"open": 3308, "high": 3310, "low": 3305, "close": 3306})
    rows.append({"open": 3306, "high": 3308, "low": 3303, "close": 3304})
    rows.append({"open": 3304, "high": 3306, "low": 3301, "close": 3302})
    # candles 156-188: flat below 3315 — keeps the swing intact
    for _ in range(33):
        rows.append({"open": 3302, "high": 3304, "low": 3300, "close": 3302})
    # candles 189-197: gradual rise toward the swing high (approaching but not breaking)
    for j in range(9):
        p = 3302.0 + j * 1.2
        rows.append({"open": p, "high": p + 1, "low": p - 0.5, "close": p + 0.5})
    # candle 198: prev_close < 3315
    rows.append({"open": 3312, "high": 3314, "low": 3311, "close": 3313})
    # candle 199: bullish break — prev_close (3313) ≤ 3315 < close (3318) → CHoCH/BOS
    rows.append({"open": 3314, "high": 3320, "low": 3313, "close": 3318})

    df = _make_df(rows)
    swings = find_swings(df, lookback=3)

    # Verify the swing at idx=152 is detected
    swing_highs = [s for s in swings if s.type == "HIGH"]
    assert any(s.price >= 3314 for s in swing_highs), (
        "Expected a swing HIGH >= 3314 to be detected at index ~152"
    )

    # Fixed get_recent_choch: must find the CHoCH (bias=NEUTRAL → all breaks are CHoCH)
    choch = get_recent_choch(df, swings, "NEUTRAL", lookback_candles=15)
    assert choch is not None, "Fixed get_recent_choch must detect the break in last 15 candles"
    assert choch.direction == "BULLISH"
    assert choch.candle_idx >= 185, f"Expected break near end, got candle_idx={choch.candle_idx}"

    # lookback=5 must not return a break that happened at index ~199 (it should, 199>=195)
    # but a break at index 152 must be excluded by lookback=15
    choch_tight = get_recent_choch(df, swings, "NEUTRAL", lookback_candles=5)
    if choch_tight is not None:
        assert choch_tight.candle_idx >= 195, (
            f"lookback=5 must only return very recent breaks, got idx={choch_tight.candle_idx}"
        )


def test_sfp_ote_geometry():
    """
    Documents the OTE geometry fix for scan_sfp_asia.

    Setup: leg low=3300, leg high=3320 (range=20).
    BULLISH OTE zone: 0.618–0.786 retracement FROM swing_high DOWN.
      upper bound (0.618): 3320 - 20*0.618 = 3307.64
      lower bound (0.786): 3320 - 20*0.786 = 3304.28
    """
    from indicators.fibonacci import compute_fib_from_sweep, compute_fib_from_sweep_bearish

    leg_low, leg_high = 3300.0, 3320.0

    # Correct anchoring: leg_low → leg_high
    fib = compute_fib_from_sweep(leg_low, leg_high, ote_low=0.618, ote_high=0.786)
    assert fib.is_in_ote(3305.0), "3305.0 should be inside OTE [3304.28, 3307.64]"
    assert not fib.is_in_ote(3298.0), "3298.0 is below the sweep low — outside OTE"
    assert not fib.is_in_ote(3315.0), "3315.0 is too shallow a retracement — above OTE"

    # Old (broken) anchoring: fib from asia_low=3306 to swing_h=3320 (range=14).
    # OTE zone: [3320-14*0.786, 3320-14*0.618] = [3308.996, 3311.348]
    # The sweep_wick (< 3306 by definition) can never be >= 3308.996 → always False.
    fib_old = compute_fib_from_sweep(3306.0, 3320.0, ote_low=0.618, ote_high=0.786)
    # Any wick below asia_low (3306) should fail the old check
    for wick in [3305.0, 3303.0, 3298.0]:
        assert not fib_old.is_in_ote(wick), (
            f"OLD anchoring: sweep_wick={wick} (below asia_low=3306) must fail "
            f"is_in_ote — documents why the original check was dead"
        )


def test_ob_not_excluded_by_forming_candle():
    """
    Regression for the touched/retest contradiction in scan_ob_retest.

    A bullish OB at [3300, 3305] should remain untouched (and be returned by
    get_nearest_ob) when only CLOSED candles are used for mitigation — even if the
    forming (last) candle enters the zone.
    """
    from indicators.order_block import OrderBlock, update_mitigation, get_nearest_ob
    from datetime import datetime, timezone

    ob_bottom, ob_top = 3300.0, 3305.0
    ob = OrderBlock(
        type="BULLISH",
        top=ob_top,
        bottom=ob_bottom,
        mid=(ob_top + ob_bottom) / 2,
        time=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )

    # Build H1 df: closed candles stay above the OB zone; forming candle enters it.
    closed_rows = [
        {"open": 3310, "high": 3315, "low": 3308, "close": 3312},  # above OB
        {"open": 3312, "high": 3316, "low": 3309, "close": 3313},  # above OB
        {"open": 3313, "high": 3317, "low": 3310, "close": 3311},  # above OB
    ]
    forming_row = {"open": 3306, "high": 3307, "low": 3301, "close": 3303}  # inside OB

    all_rows = closed_rows + [forming_row]
    df_full = _make_df(all_rows)
    df_closed = df_full.iloc[:-1]

    # Mitigation on CLOSED candles only — OB must remain untouched
    obs = [ob]
    obs = update_mitigation(obs, df_closed, lookback=len(df_closed))
    assert not obs[0].touched, "OB must not be touched when only closed candles are used"

    result = get_nearest_ob(obs, price=3303.0, direction="BULLISH")
    assert result is not None, "get_nearest_ob must return the OB when it is untouched"

    # Sanity check: if the forming candle IS included, touched becomes True and OB is excluded.
    obs2 = [OrderBlock(
        type="BULLISH", top=ob_top, bottom=ob_bottom,
        mid=(ob_top + ob_bottom) / 2,
        time=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )]
    obs2 = update_mitigation(obs2, df_full, lookback=len(df_full))
    assert obs2[0].touched, "Including the forming candle must set touched=True"
    assert get_nearest_ob(obs2, price=3303.0, direction="BULLISH") is None
