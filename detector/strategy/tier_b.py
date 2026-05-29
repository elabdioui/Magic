"""Tier B setups: Breaker+Fib, BOS+FVG retest."""
import logging
import pandas as pd

from indicators import (
    detect_fvg, filter_unfilled_fvg, get_recent_fvg,
    detect_order_blocks, update_mitigation, get_nearest_ob,
    find_swings, determine_bias, detect_structure_breaks,
    compute_fib_from_sweep,
)
from strategy.killzone import get_active_killzone
from config import cfg

log = logging.getLogger(__name__)


def scan_breaker_fib(
    tf_data: dict[str, pd.DataFrame],
    direction: str = "LONG",
) -> dict | None:
    """
    Breaker Block + Fib confluence:
    - Bullish OB on M5 that has been violated → becomes bearish breaker
    - Price retraces into breaker zone + OTE
    """
    killzone = get_active_killzone()
    if killzone is None:
        return None

    m5 = tf_data.get("M5")
    h4 = tf_data.get("H4")
    if m5 is None or h4 is None or m5.empty:
        return None

    h4_swings = find_swings(h4, lookback=cfg.SWING_LOOKBACK)
    h4_bias = determine_bias(h4_swings)
    expected = "BULLISH" if direction == "LONG" else "BEARISH"
    if h4_bias != expected:
        return None

    current_price = m5.iloc[-1]["close"]

    m5_obs = detect_order_blocks(m5, lookback=cfg.OB_LOOKBACK)
    m5_obs = update_mitigation(m5_obs, m5)

    # Breaker = mitigated OB that has flipped
    opp_dir = "BEARISH" if direction == "LONG" else "BULLISH"
    breakers = [o for o in m5_obs if o.is_breaker and o.type == opp_dir]
    if not breakers:
        return None

    nearest_breaker = min(breakers, key=lambda o: abs(o.mid - current_price))

    m5_swings = find_swings(m5, lookback=cfg.SWING_LOOKBACK)
    if direction == "LONG":
        swing_h = max((s.price for s in m5_swings if s.type == "HIGH"), default=None)
        if swing_h is None:
            return None
        fib = compute_fib_from_sweep(nearest_breaker.bottom, swing_h)
    else:
        swing_l = min((s.price for s in m5_swings if s.type == "LOW"), default=None)
        if swing_l is None:
            return None
        from indicators.fibonacci import compute_fib_from_sweep_bearish
        fib = compute_fib_from_sweep_bearish(nearest_breaker.top, swing_l)

    in_ote = fib.is_in_ote(current_price)
    if not in_ote:
        return None

    confluences = ["Bias_H4", "Breaker_M5"]
    if in_ote:
        confluences.append(f"OTE_{cfg.OTE_LOW}")

    score = min(10, len(confluences) * 2)
    if score < cfg.MIN_SCORE_B:
        return None

    if direction == "LONG":
        sl = nearest_breaker.bottom - 3 * 0.10
        tp = max((s.price for s in m5_swings if s.type == "HIGH"), default=current_price * 1.003)
    else:
        sl = nearest_breaker.top + 3 * 0.10
        tp = min((s.price for s in m5_swings if s.type == "LOW"), default=current_price * 0.997)

    mid = (nearest_breaker.top + nearest_breaker.bottom) / 2
    rr = abs(tp - mid) / max(abs(mid - sl), 0.01)
    if rr < 1.5:
        return None

    return {
        "tier": "B",
        "direction": direction,
        "pattern": "Breaker + OTE",
        "killzone": killzone,
        "entry_zone_low": round(nearest_breaker.bottom, 2),
        "entry_zone_high": round(nearest_breaker.top, 2),
        "stop_loss": round(sl, 2),
        "take_profit": round(tp, 2),
        "bias_h4": h4_bias,
        "bias_h1": expected,
        "confluences": confluences,
        "confluence_score": score,
        "estimated_winrate": 0.52,
    }


def scan_bos_fvg(
    tf_data: dict[str, pd.DataFrame],
    direction: str = "LONG",
) -> dict | None:
    """
    BOS + FVG Retest:
    - BOS confirms direction on M5
    - FVG left by the BOS impulse
    - Price retests the FVG
    """
    killzone = get_active_killzone()
    if killzone is None:
        return None

    m5 = tf_data.get("M5")
    h4 = tf_data.get("H4")
    if m5 is None or h4 is None or m5.empty:
        return None

    h4_swings = find_swings(h4, lookback=cfg.SWING_LOOKBACK)
    h4_bias = determine_bias(h4_swings)
    expected = "BULLISH" if direction == "LONG" else "BEARISH"
    if h4_bias != expected:
        return None

    m5_swings = find_swings(m5, lookback=cfg.SWING_LOOKBACK)
    m5_bias = determine_bias(m5_swings)
    breaks = detect_structure_breaks(m5, m5_swings, m5_bias)  # type: ignore[arg-type]
    bos_list = [b for b in breaks if b.type == "BOS" and b.direction == expected]
    if not bos_list:
        return None

    current_price = m5.iloc[-1]["close"]
    m5_fvgs = detect_fvg(m5.iloc[-30:], min_size_pips=cfg.FVG_MIN_SIZE_PIPS)
    fvg_dir = "BULLISH" if direction == "LONG" else "BEARISH"
    m5_fvgs = filter_unfilled_fvg(m5_fvgs, current_price)
    recent_fvgs = get_recent_fvg(m5_fvgs, fvg_dir, n=2)

    if not recent_fvgs:
        return None

    best_fvg = recent_fvgs[-1]
    in_fvg = best_fvg.bottom <= current_price <= best_fvg.top
    if not in_fvg:
        return None

    confluences = ["Bias_H4", "BOS_M5", "FVG_M5"]
    score = 6

    if direction == "LONG":
        sl = best_fvg.bottom - 3 * 0.10
        tp = max((s.price for s in m5_swings if s.type == "HIGH"), default=current_price * 1.003)
    else:
        sl = best_fvg.top + 3 * 0.10
        tp = min((s.price for s in m5_swings if s.type == "LOW"), default=current_price * 0.997)

    mid = (best_fvg.top + best_fvg.bottom) / 2
    rr = abs(tp - mid) / max(abs(mid - sl), 0.01)
    if rr < 1.5:
        return None

    return {
        "tier": "B",
        "direction": direction,
        "pattern": "BOS + FVG Retest",
        "killzone": killzone,
        "entry_zone_low": round(best_fvg.bottom, 2),
        "entry_zone_high": round(best_fvg.top, 2),
        "stop_loss": round(sl, 2),
        "take_profit": round(tp, 2),
        "bias_h4": h4_bias,
        "bias_h1": expected,
        "confluences": confluences,
        "confluence_score": score,
        "estimated_winrate": 0.50,
    }
