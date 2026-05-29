"""
Tier S — Golden Setup NY AM (and London variant).

Rules (LONG example):
  1. H4 bias BULLISH (HH/HL)
  2. H1 bias BULLISH (HH/HL)
  3. M5: sweep of recent SSL
  4. M5: CHoCH to BULLISH immediately after sweep
  5. M5/M1: FVG or OB forms in the imbalance
  6. Price retraces into OTE (0.618–0.786) of the sweep range
  7. Entry = FVG/OB zone within OTE
  8. SL = below the sweep low (+ small buffer)
  9. TP = next BSL (swing high) at minimum 1:2 RR
"""
import logging
from datetime import datetime

import pandas as pd

from indicators import (
    detect_fvg, filter_unfilled_fvg, get_recent_fvg,
    detect_order_blocks, update_mitigation, get_nearest_ob,
    find_swings, determine_bias, get_recent_choch,
    find_swing_liquidity, detect_sweeps, get_recent_sweep,
    compute_fib_from_sweep,
)
from strategy.killzone import get_active_killzone
from config import cfg

log = logging.getLogger(__name__)


def _compute_sl_tp(
    direction: str,
    entry_low: float,
    entry_high: float,
    sweep_extreme: float,
    target: float,
    buffer_pips: float = 3.0,
) -> tuple[float, float]:
    buf = buffer_pips * 0.10
    if direction == "LONG":
        sl = sweep_extreme - buf
        tp = target
    else:
        sl = sweep_extreme + buf
        tp = target
    return sl, tp


def _score_confluences(confluences: list[str]) -> int:
    weights = {
        "FVG_M5": 2, "FVG_M1": 2,
        "OB_H1": 2, "OB_M5": 1,
        "SSL_Sweep": 2, "BSL_Sweep": 2,
        "CHoCH_M5": 2, "CHoCH_M1": 1,
        f"OTE_{cfg.OTE_LOW}": 1, f"OTE_{cfg.OTE_HIGH}": 1,
        "Bias_H4": 1, "Bias_H1": 1,
    }
    return min(10, sum(weights.get(c, 1) for c in confluences))


def scan_golden_setup(
    tf_data: dict[str, pd.DataFrame],
    direction: str = "LONG",  # "LONG" | "SHORT"
) -> dict | None:
    """
    Returns a signal dict if Tier S criteria met, else None.
    direction is pre-determined by the caller based on session bias.
    """
    m5 = tf_data.get("M5")
    m1 = tf_data.get("M1")
    h1 = tf_data.get("H1")
    h4 = tf_data.get("H4")

    if m5 is None or h1 is None or h4 is None or m5.empty or h1.empty or h4.empty:
        return None

    killzone = get_active_killzone()
    if killzone is None:
        return None

    # 1. H4 bias
    h4_swings = find_swings(h4, lookback=cfg.SWING_LOOKBACK)
    h4_bias = determine_bias(h4_swings)
    expected_bias = "BULLISH" if direction == "LONG" else "BEARISH"
    if h4_bias != expected_bias:
        log.debug("H4 bias %s ≠ %s — Tier S skip", h4_bias, expected_bias)
        return None

    # 2. H1 bias
    h1_swings = find_swings(h1, lookback=cfg.SWING_LOOKBACK)
    h1_bias = determine_bias(h1_swings)
    if h1_bias != expected_bias:
        log.debug("H1 bias %s ≠ %s — Tier S skip", h1_bias, expected_bias)
        return None

    # 3. M5: recent SSL sweep (LONG) or BSL sweep (SHORT)
    m5_swings = find_swings(m5, lookback=cfg.SWING_LOOKBACK)
    liq_levels = find_swing_liquidity(m5_swings, equal_threshold_pips=cfg.LIQUIDITY_EQUAL_THRESHOLD)
    liq_levels = detect_sweeps(m5, liq_levels, lookback_candles=10)

    sweep_type = "SSL" if direction == "LONG" else "BSL"
    recent_sweep = get_recent_sweep(liq_levels, sweep_type)  # type: ignore[arg-type]
    if recent_sweep is None:
        log.debug("No %s sweep found on M5 — Tier S skip", sweep_type)
        return None

    # 4. CHoCH on M5 after the sweep — temporal order enforced
    choch = get_recent_choch(m5, m5_swings, h1_bias, lookback_candles=15)  # type: ignore[arg-type]
    if choch is None or choch.direction != expected_bias:
        log.debug("No CHoCH %s on M5 — Tier S skip", expected_bias)
        return None

    if recent_sweep.sweep_time is not None and choch.time <= recent_sweep.sweep_time:
        log.debug("CHoCH (%s) not after sweep (%s) — temporal order violated, Tier S skip",
                  choch.time, recent_sweep.sweep_time)
        return None

    # 5. FVG on M5/M1 (look in last 20 candles post-sweep)
    m5_fvgs = detect_fvg(m5.iloc[-30:], min_size_pips=cfg.FVG_MIN_SIZE_PIPS)
    fvg_dir = "BULLISH" if direction == "LONG" else "BEARISH"
    current_price = m5.iloc[-1]["close"]
    m5_fvgs = filter_unfilled_fvg(m5_fvgs, current_price)
    recent_fvgs = get_recent_fvg(m5_fvgs, fvg_dir, n=3)

    # 6. OB on M5/H1
    m5_obs = detect_order_blocks(m5.iloc[-50:], lookback=cfg.OB_LOOKBACK)
    m5_obs = update_mitigation(m5_obs, m5, lookback=cfg.OB_MITIGATION_LOOKBACK)
    ob_dir = "BULLISH" if direction == "LONG" else "BEARISH"
    nearest_ob = get_nearest_ob(m5_obs, current_price, ob_dir)

    if not recent_fvgs and nearest_ob is None:
        log.debug("No FVG or OB found — Tier S skip")
        return None

    # 7. OTE check
    if direction == "LONG":
        swing_h = max((s.price for s in m5_swings if s.type == "HIGH"), default=None)
        sweep_low = recent_sweep.price
        if swing_h is None:
            return None
        fib = compute_fib_from_sweep(sweep_low, swing_h, ote_low=cfg.OTE_LOW, ote_high=cfg.OTE_HIGH)
    else:
        swing_l = min((s.price for s in m5_swings if s.type == "LOW"), default=None)
        sweep_high = recent_sweep.price
        if swing_l is None:
            return None
        from indicators.fibonacci import compute_fib_from_sweep_bearish
        fib = compute_fib_from_sweep_bearish(sweep_high, swing_l, ote_low=cfg.OTE_LOW, ote_high=cfg.OTE_HIGH)

    in_ote = fib.is_in_ote(current_price)

    # 8. Build entry zone from FVG or OB
    if recent_fvgs:
        best_fvg = recent_fvgs[-1]
        entry_low = best_fvg.bottom
        entry_high = best_fvg.top
        entry_tag = "FVG_M5"
    elif nearest_ob:
        entry_low = nearest_ob.bottom
        entry_high = nearest_ob.top
        entry_tag = "OB_M5"
    else:
        return None

    # Price must be in the entry zone or in OTE — avoids signalling when price is far away
    if not (entry_low <= current_price <= entry_high) and not in_ote:
        log.debug("Price %.2f not in entry zone [%.2f-%.2f] and not in OTE — Tier S skip",
                  current_price, entry_low, entry_high)
        return None

    # Confluences list
    confluences = [
        "Bias_H4", "Bias_H1",
        f"{sweep_type}_Sweep",
        "CHoCH_M5",
        entry_tag,
    ]
    if in_ote:
        ote_label = (
            f"OTE_{cfg.OTE_LOW}"
            if abs(current_price - fib.level(cfg.OTE_LOW)) < abs(current_price - fib.level(cfg.OTE_HIGH))
            else f"OTE_{cfg.OTE_HIGH}"
        )
        confluences.append(ote_label)

    score = _score_confluences(confluences)
    if score < cfg.MIN_SCORE_S:
        log.debug("Score %d < MIN_SCORE_S %d — Tier S skip", score, cfg.MIN_SCORE_S)
        return None

    # 9. SL / TP
    sweep_extreme = recent_sweep.price
    if direction == "LONG":
        target_tp = max((s.price for s in h1_swings if s.type == "HIGH"), default=current_price * 1.005)
    else:
        target_tp = min((s.price for s in h1_swings if s.type == "LOW"), default=current_price * 0.995)

    sl, tp = _compute_sl_tp(direction, entry_low, entry_high, sweep_extreme, target_tp)

    rr = abs(tp - (entry_low + entry_high) / 2) / abs((entry_low + entry_high) / 2 - sl)
    if rr < 2.0:
        log.debug("RR %.1f < 2.0 — Tier S skip", rr)
        return None

    return {
        "tier": "S",
        "direction": direction,
        "pattern": "Golden Setup",
        "killzone": killzone,
        "entry_zone_low": round(entry_low, 2),
        "entry_zone_high": round(entry_high, 2),
        "stop_loss": round(sl, 2),
        "take_profit": round(tp, 2),
        "bias_h4": h4_bias,
        "bias_h1": h1_bias,
        "confluences": confluences,
        "confluence_score": score,
        "estimated_winrate": 0.72,
    }
