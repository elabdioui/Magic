"""Tier A setups: OB Retest + London Open Sweep."""
import logging
import pandas as pd

from indicators import (
    detect_fvg, filter_unfilled_fvg, get_recent_fvg,
    detect_order_blocks, update_mitigation, get_nearest_ob,
    find_swings, determine_bias,
    find_swing_liquidity, detect_sweeps, get_recent_sweep,
)
from strategy.killzone import get_active_killzone
from config import cfg

log = logging.getLogger(__name__)


def scan_ob_retest(
    tf_data: dict[str, pd.DataFrame],
    direction: str = "LONG",
) -> dict | None:
    """
    OB Retest setup:
    - H4 bullish bias
    - H1 OB unmitigated
    - Price returns to H1 OB zone
    - M5 confirmation: BOS or FVG
    """
    h1 = tf_data.get("H1")
    h4 = tf_data.get("H4")
    m5 = tf_data.get("M5")
    if h1 is None or h4 is None or m5 is None or h1.empty or m5.empty:
        return None

    killzone = get_active_killzone()
    if killzone is None:
        return None

    h4_swings = find_swings(h4, lookback=cfg.SWING_LOOKBACK)
    h4_bias = determine_bias(h4_swings)
    expected = "BULLISH" if direction == "LONG" else "BEARISH"
    if h4_bias != expected:
        return None

    current_price = m5.iloc[-1]["close"]

    # H1 OB near current price
    h1_obs = detect_order_blocks(h1, lookback=cfg.OB_LOOKBACK)
    h1_obs = update_mitigation(h1_obs, h1)
    ob_dir = "BULLISH" if direction == "LONG" else "BEARISH"
    ob = get_nearest_ob(h1_obs, current_price, ob_dir)
    if ob is None:
        return None

    # Price must be inside or just touching the OB
    margin = (ob.top - ob.bottom) * 0.3
    in_zone = (ob.bottom - margin) <= current_price <= (ob.top + margin)
    if not in_zone:
        return None

    # M5 FVG as confirmation
    m5_fvgs = detect_fvg(m5.iloc[-20:], min_size_pips=cfg.FVG_MIN_SIZE_PIPS)
    fvg_dir = "BULLISH" if direction == "LONG" else "BEARISH"
    m5_fvgs = filter_unfilled_fvg(m5_fvgs, current_price)
    recent_fvgs = get_recent_fvg(m5_fvgs, fvg_dir, n=2)

    confluences = ["Bias_H4", "OB_H1"]
    if recent_fvgs:
        confluences.append("FVG_M5")

    score = min(10, len(confluences) * 2)
    if score < cfg.MIN_SCORE_A:
        return None

    h1_swings = find_swings(h1, lookback=cfg.SWING_LOOKBACK)
    if direction == "LONG":
        target_tp = max((s.price for s in h1_swings if s.type == "HIGH"), default=current_price * 1.004)
        sl = ob.bottom - 3 * 0.10
    else:
        target_tp = min((s.price for s in h1_swings if s.type == "LOW"), default=current_price * 0.996)
        sl = ob.top + 3 * 0.10

    mid_entry = (ob.top + ob.bottom) / 2
    rr = abs(target_tp - mid_entry) / abs(mid_entry - sl)
    if rr < 1.5:
        return None

    return {
        "tier": "A",
        "direction": direction,
        "pattern": "OB Retest H1",
        "killzone": killzone,
        "entry_zone_low": round(ob.bottom, 2),
        "entry_zone_high": round(ob.top, 2),
        "stop_loss": round(sl, 2),
        "take_profit": round(target_tp, 2),
        "bias_h4": h4_bias,
        "bias_h1": expected,
        "confluences": confluences,
        "confluence_score": score,
        "estimated_winrate": 0.62,
    }


def scan_london_sweep(
    tf_data: dict[str, pd.DataFrame],
    direction: str = "LONG",
) -> dict | None:
    """
    London Open Sweep:
    - London killzone only
    - Sweep of Asia range high/low
    - FVG forms post-sweep
    """
    killzone = get_active_killzone()
    if killzone != "LONDON":
        return None

    m15 = tf_data.get("M15")
    m5 = tf_data.get("M5")
    h4 = tf_data.get("H4")
    if m15 is None or m5 is None or h4 is None or m15.empty:
        return None

    h4_swings = find_swings(h4, lookback=cfg.SWING_LOOKBACK)
    h4_bias = determine_bias(h4_swings)
    expected = "BULLISH" if direction == "LONG" else "BEARISH"
    if h4_bias != expected:
        return None

    # Asia range = last 8 hours before London (roughly M15 candles 0–32)
    asia_df = m15.iloc[-50:-18] if len(m15) >= 50 else m15.iloc[:-5]
    asia_high = asia_df["high"].max()
    asia_low = asia_df["low"].min()

    current_price = m5.iloc[-1]["close"]

    if direction == "LONG":
        # Expect sweep of Asia low (SSL)
        swept = m5.iloc[-10:]["low"].min() < asia_low and current_price > asia_low
        if not swept:
            return None
        sweep_extreme = asia_low
    else:
        swept = m5.iloc[-10:]["high"].max() > asia_high and current_price < asia_high
        if not swept:
            return None
        sweep_extreme = asia_high

    m5_fvgs = detect_fvg(m5.iloc[-20:], min_size_pips=cfg.FVG_MIN_SIZE_PIPS)
    fvg_dir = "BULLISH" if direction == "LONG" else "BEARISH"
    m5_fvgs = filter_unfilled_fvg(m5_fvgs, current_price)
    recent_fvgs = get_recent_fvg(m5_fvgs, fvg_dir, n=2)

    if not recent_fvgs:
        return None

    best_fvg = recent_fvgs[-1]
    confluences = ["Bias_H4", "Asia_Sweep", "FVG_M5"]
    score = 6

    if direction == "LONG":
        sl = sweep_extreme - 3 * 0.10
        target_tp = asia_high
    else:
        sl = sweep_extreme + 3 * 0.10
        target_tp = asia_low

    mid = (best_fvg.top + best_fvg.bottom) / 2
    rr = abs(target_tp - mid) / abs(mid - sl)
    if rr < 1.5:
        return None

    return {
        "tier": "A",
        "direction": direction,
        "pattern": "London Open Sweep",
        "killzone": killzone,
        "entry_zone_low": round(best_fvg.bottom, 2),
        "entry_zone_high": round(best_fvg.top, 2),
        "stop_loss": round(sl, 2),
        "take_profit": round(target_tp, 2),
        "bias_h4": h4_bias,
        "bias_h1": expected,
        "confluences": confluences,
        "confluence_score": score,
        "estimated_winrate": 0.60,
    }
