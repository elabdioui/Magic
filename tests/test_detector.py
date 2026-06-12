"""Unit tests for detector — no MT5 required."""
import sys
import os
import unittest.mock as mock
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
    Documents the OTE geometry fix introduced when scan_asia_fade was designed.

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


# ── Tier S: OTE fallback entry tests ──────────────────────────────────────────

def _sw(type_: str, price: float):
    """Create a minimal mock Swing for use in scanner monkeypatches."""
    s = mock.MagicMock()
    s.type = type_
    s.price = price
    return s


def _patch_tier_s_indicators(monkeypatch, module, sweep_price=3300.0, swing_h=3400.0,
                              h1_tp_high=3600.0):
    """Apply monkeypatches for all indicator dependencies of scan_golden_setup."""
    monkeypatch.setattr(module, "get_active_killzone", lambda *a, **kw: "NY_AM")
    monkeypatch.setattr(module, "find_swing_liquidity", lambda *a, **kw: [])
    monkeypatch.setattr(module, "detect_sweeps", lambda df, liq, **kw: liq)
    monkeypatch.setattr(module, "determine_bias", lambda *a, **kw: "BULLISH")

    _n = [0]
    def patched_swings(df, **kw):
        _n[0] += 1
        if _n[0] == 2:  # H1 swings — needs high TP target to clear RR gate
            return [_sw("HIGH", h1_tp_high), _sw("LOW", sweep_price)]
        return [_sw("HIGH", swing_h), _sw("LOW", sweep_price)]
    monkeypatch.setattr(module, "find_swings", patched_swings)

    sweep_mock = mock.MagicMock()
    sweep_mock.price = sweep_price
    sweep_mock.sweep_time = pd.Timestamp("2024-01-15 13:30:00", tz="UTC")
    monkeypatch.setattr(module, "get_recent_sweep", lambda liq, stype: sweep_mock)

    sb_mock = mock.MagicMock()
    sb_mock.direction = "BULLISH"
    sb_mock.time = pd.Timestamp("2024-01-15 14:00:00", tz="UTC")
    monkeypatch.setattr(module, "get_recent_structure_break", lambda *a, **kw: sb_mock)

    monkeypatch.setattr(module, "detect_fvg", lambda *a, **kw: [])
    monkeypatch.setattr(module, "filter_unfilled_fvg", lambda fvgs, *a, **kw: fvgs)
    monkeypatch.setattr(module, "get_recent_fvg", lambda *a, **kw: [])
    monkeypatch.setattr(module, "detect_order_blocks", lambda *a, **kw: [])
    monkeypatch.setattr(module, "update_mitigation", lambda obs, *a, **kw: obs)
    monkeypatch.setattr(module, "get_nearest_ob", lambda *a, **kw: None)


def test_tier_s_ote_fallback_entry(monkeypatch):
    """
    Price in OTE, no FVG/OB → signal emitted using OTE band as entry zone.
    Confluences: Bias_H4(2)+Bias_H1(2)+SSL_Sweep(3)+CHoCH_M5(2)+OTE(2) = 11 → capped 10.
    """
    import strategy.tier_s as m
    from strategy.tier_s import scan_golden_setup
    from indicators.fibonacci import compute_fib_from_sweep as _cfib

    # sweep_low=3300, swing_h=3400 → OTE=[3321.4, 3338.2]; h1_tp=3600 for RR>2
    _patch_tier_s_indicators(monkeypatch, m, sweep_price=3300.0, swing_h=3400.0, h1_tp_high=3600.0)

    price = 3330.0  # inside OTE [3321.4, 3338.2]
    rows = [{"open": price, "high": price + 1, "low": price - 1, "close": price}] * 50
    df = _make_df(rows)
    tf = {"M5": df, "M1": df, "H1": df, "H4": df}

    result = scan_golden_setup(tf, "LONG")

    assert result is not None, "Expected signal when price in OTE with no FVG/OB"
    assert result["tier"] == "S"
    assert result["pattern"] == "Golden Setup"
    assert "FVG_M5" not in result["confluences"]
    assert "OB_M5" not in result["confluences"]
    assert any("OTE" in c for c in result["confluences"]), "OTE label must be in confluences"

    fib = _cfib(3300.0, 3400.0, ote_low=0.618, ote_high=0.786)
    assert abs(result["entry_zone_low"] - round(fib.ote_low, 2)) < 0.05
    assert abs(result["entry_zone_high"] - round(fib.ote_high, 2)) < 0.05
    assert result["confluence_score"] >= 7


def test_tier_s_no_entry_zone_skips(monkeypatch):
    """
    Price outside OTE, no FVG/OB → no actionable entry zone → returns None.
    """
    import strategy.tier_s as m
    from strategy.tier_s import scan_golden_setup

    _patch_tier_s_indicators(monkeypatch, m, sweep_price=3300.0, swing_h=3400.0, h1_tp_high=3600.0)

    price = 3350.0  # above OTE upper bound 3338.2 → not in OTE
    rows = [{"open": price, "high": price + 1, "low": price - 1, "close": price}] * 50
    df = _make_df(rows)
    tf = {"M5": df, "M1": df, "H1": df, "H4": df}

    result = scan_golden_setup(tf, "LONG")
    assert result is None, "Expected None when price outside OTE with no FVG/OB"


# ── Tier A: Asia Fade tests ────────────────────────────────────────────────────

def test_asia_fade_long(monkeypatch):
    """
    Synthetic Asia range + sweep below asia_low + close back inside + price in range
    → signal with pattern 'Asia Fade', SL below sweep wick, TP == asia_high,
      'Asia_Sweep' in confluences.
    """
    import strategy.tier_a as m
    from strategy.tier_a import scan_asia_fade

    asia_low = 1900.0
    asia_high = 1950.0
    sweep_wick = 1895.0
    current_price = 1920.0

    monkeypatch.setattr(m, "get_active_killzone", lambda *a, **kw: "LONDON")
    monkeypatch.setattr(m, "get_asia_range", lambda *a, **kw: (asia_high, asia_low))
    monkeypatch.setattr(m, "find_swings", lambda *a, **kw: [_sw("HIGH", 1960.0), _sw("LOW", 1890.0)])
    monkeypatch.setattr(m, "determine_bias", lambda *a, **kw: "BULLISH")
    monkeypatch.setattr(m, "detect_fvg", lambda *a, **kw: [])
    monkeypatch.setattr(m, "filter_unfilled_fvg", lambda fvgs, *a, **kw: fvgs)
    monkeypatch.setattr(m, "get_recent_fvg", lambda *a, **kw: [])

    # Build M5 dataframe: 28 normal + sweep + reintegration + forming
    m5_rows = []
    for _ in range(28):
        m5_rows.append({"open": 1920, "high": 1925, "low": 1918, "close": 1922})
    # sweep candle: wick below asia_low, close below asia_low (close-back in next candle)
    m5_rows.append({"open": 1903, "high": 1905, "low": sweep_wick, "close": 1898})
    # reintegration candle: closes back inside
    m5_rows.append({"open": 1898, "high": 1910, "low": 1897, "close": 1908})
    # forming candle (current)
    m5_rows.append({"open": 1910, "high": 1925, "low": 1908, "close": current_price})

    m5_df = _make_df(m5_rows)
    m15_df = _make_df([{"open": 1920, "high": 1925, "low": 1918, "close": 1922}] * 20)
    h4_df = _make_df([{"open": 1920, "high": 1925, "low": 1918, "close": 1922}] * 30)

    tf = {"M5": m5_df, "M15": m15_df, "H4": h4_df}
    result = scan_asia_fade(tf, "LONG")

    assert result is not None, "Expected Asia Fade signal"
    assert result["pattern"] == "Asia Fade"
    assert result["tier"] == "A"
    assert "Asia_Sweep" in result["confluences"]
    assert result["stop_loss"] < sweep_wick, "SL must be below the sweep wick"
    assert abs(result["take_profit"] - asia_high) < 0.01, "TP must equal asia_high"


def test_asia_fade_range_too_small(monkeypatch):
    """Asia range smaller than ASIA_MIN_RANGE_PIPS → returns None."""
    import strategy.tier_a as m
    from strategy.tier_a import scan_asia_fade

    monkeypatch.setattr(m, "get_active_killzone", lambda *a, **kw: "LONDON")
    # Range = 1.0 pip, threshold = 15 pips = 1.5 → too small
    monkeypatch.setattr(m, "get_asia_range", lambda *a, **kw: (1901.0, 1900.0))

    df = _make_df([{"open": 1900, "high": 1901, "low": 1899, "close": 1900}] * 30)
    tf = {"M5": df, "M15": df, "H4": df}

    result = scan_asia_fade(tf, "LONG")
    assert result is None, "Expected None when Asia range is below minimum"


# ── Stats module tests ─────────────────────────────────────────────────────────

def test_stats_counters(caplog):
    """record/tick smoke test: counters increment, summary logs at the every boundary."""
    import logging
    import stats as stats_mod

    # Reset module state
    stats_mod._counters.clear()
    stats_mod._scan_count = 0

    stats_mod.record("test_scanner", "EMIT")
    stats_mod.record("test_scanner", "no_sweep")
    stats_mod.record("test_scanner", "no_sweep")

    assert stats_mod._counters["test_scanner"]["EMIT"] == 1
    assert stats_mod._counters["test_scanner"]["no_sweep"] == 2

    with caplog.at_level(logging.INFO, logger="stats"):
        for _ in range(119):
            stats_mod.tick(every=120)
        assert not any("SCAN_STATS" in r.message for r in caplog.records), (
            "Summary must NOT fire before the 120th tick"
        )
        stats_mod.tick(every=120)
        assert any("SCAN_STATS" in r.message for r in caplog.records), (
            "Summary MUST fire at the 120th tick"
        )


# ── ORB NY tests ───────────────────────────────────────────────────────────────

import pytz as _pytz
from strategy.orb import scan_orb_ny, _reset_daily_guard

_NY_TZ_TEST = _pytz.timezone("America/New_York")


def _make_orb_m5(candle_specs: list[dict]) -> pd.DataFrame:
    """
    Build a M5 dataframe with explicit NY-timestamped candles.
    Each spec: {"ny_time": "HH:MM", "open": x, "high": x, "low": x, "close": x}
    Date is fixed to 2024-06-12 (a Wednesday in summer, UTC-4).
    Last row is the forming candle (same values as second-to-last, irrelevant).
    """
    date_str = "2024-06-12"
    rows = []
    for spec in candle_specs:
        ny_dt = _NY_TZ_TEST.localize(
            pd.Timestamp(f"{date_str} {spec['ny_time']}:00").to_pydatetime()
        )
        utc_dt = ny_dt.astimezone(_pytz.utc)
        rows.append({
            "time": utc_dt,
            "open":  spec["open"],
            "high":  spec["high"],
            "low":   spec["low"],
            "close": spec["close"],
        })
    df = pd.DataFrame(rows)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df


def _or_candles(or_high=3340.0, or_low=3330.0) -> list[dict]:
    """Six OR candles covering 09:30–09:55 NY."""
    times = ["09:30", "09:35", "09:40", "09:45", "09:50", "09:55"]
    mid = (or_high + or_low) / 2
    return [
        {"ny_time": t, "open": mid, "high": or_high, "low": or_low, "close": mid}
        for t in times
    ]


def test_orb_long_breakout():
    """OR 09:30–10:00 high=3340/low=3330; candle at 10:05 closes 3341 → LONG signal."""
    _reset_daily_guard()
    or_high, or_low = 3340.0, 3330.0
    specs = _or_candles(or_high, or_low)
    # breakout candle (second-to-last = last closed)
    specs.append({"ny_time": "10:05", "open": 3340.5, "high": 3342, "low": 3340, "close": 3341})
    # forming candle (excluded)
    specs.append({"ny_time": "10:10", "open": 3341, "high": 3343, "low": 3340, "close": 3341})

    tf = {"M5": _make_orb_m5(specs)}
    result = scan_orb_ny(tf, "LONG")

    assert result is not None, "Expected LONG ORB signal"
    assert result["tier"] == "ORB"
    assert result["pattern"] == "ORB NY"
    assert result["direction"] == "LONG"
    assert result["stop_loss"] == pytest.approx(or_low, abs=0.01)
    assert result["take_profit"] > or_high
    assert "ORB_Breakout" in result["confluences"]


def test_orb_range_too_small():
    """OR range 0.5 (5 pips for XAUUSD) → None."""
    _reset_daily_guard()
    or_high, or_low = 3330.5, 3330.0  # 0.5 = 5 pips, threshold default=10 pips
    specs = _or_candles(or_high, or_low)
    specs.append({"ny_time": "10:05", "open": 3330.6, "high": 3331, "low": 3330, "close": 3331})
    specs.append({"ny_time": "10:10", "open": 3331, "high": 3332, "low": 3330, "close": 3331})

    tf = {"M5": _make_orb_m5(specs)}
    result = scan_orb_ny(tf, "LONG")
    assert result is None, "Expected None when OR range below minimum"


def test_orb_no_signal_after_cutoff():
    """Breakout candle closed at 12:05 NY → outside window → None."""
    _reset_daily_guard()
    specs = _or_candles()
    # filler candles between 10:05 and 11:55
    for hh_mm in ["10:05", "10:10", "10:15", "10:20", "11:50", "11:55"]:
        specs.append({"ny_time": hh_mm, "open": 3339, "high": 3340, "low": 3338, "close": 3339})
    # breakout at 12:05 NY (past cutoff) — will be last closed candle
    specs.append({"ny_time": "12:05", "open": 3340, "high": 3342, "low": 3339, "close": 3341})
    # forming candle
    specs.append({"ny_time": "12:10", "open": 3341, "high": 3343, "low": 3340, "close": 3341})

    tf = {"M5": _make_orb_m5(specs)}
    result = scan_orb_ny(tf, "LONG")
    assert result is None, "Expected None when last closed candle is past 12:00 NY cutoff"


def test_orb_one_per_day():
    """Second call same NY date same direction → None after first EMIT."""
    _reset_daily_guard()
    specs = _or_candles()
    specs.append({"ny_time": "10:05", "open": 3340.5, "high": 3342, "low": 3340, "close": 3341})
    specs.append({"ny_time": "10:10", "open": 3341, "high": 3343, "low": 3340, "close": 3341})

    tf = {"M5": _make_orb_m5(specs)}

    first = scan_orb_ny(tf, "LONG")
    assert first is not None, "First call must return a signal"

    second = scan_orb_ny(tf, "LONG")
    assert second is None, "Second call same direction same day must return None"


def test_orb_stale_breakout():
    """Breakout happened 3 candles ago; current candle is back inside range → None."""
    _reset_daily_guard()
    specs = _or_candles()
    # breakout happened 3 candles ago (not the most recent closed)
    specs.append({"ny_time": "10:05", "open": 3340.5, "high": 3342, "low": 3340, "close": 3341})
    # subsequent candles back inside range (do NOT break out)
    specs.append({"ny_time": "10:10", "open": 3338, "high": 3339, "low": 3336, "close": 3337})
    specs.append({"ny_time": "10:15", "open": 3337, "high": 3338, "low": 3335, "close": 3336})
    # last closed candle (inside range, no breakout)
    specs.append({"ny_time": "10:20", "open": 3336, "high": 3337, "low": 3334, "close": 3335})
    # forming candle
    specs.append({"ny_time": "10:25", "open": 3335, "high": 3336, "low": 3334, "close": 3335})

    tf = {"M5": _make_orb_m5(specs)}
    result = scan_orb_ny(tf, "LONG")
    assert result is None, "Expected None when breakout candle is not the most recent closed"
