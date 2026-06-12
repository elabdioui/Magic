"""
Tier S — Golden Setup NY AM (and London variant).

Rules (LONG example):
  1. H4 bias BULLISH (HH/HL)
  2. H1 bias BULLISH (HH/HL)
  3. M5: sweep of recent SSL
  4. M5: CHoCH to BULLISH immediately after sweep
  5. OTE (0.618–0.786) and FVG/OB are SOFT confluences; entry zone falls back to OTE band
  6. SL = below the sweep low (+ small buffer)
  7. TP = next BSL (swing high) at minimum 1:2 RR
"""
import logging
from datetime import datetime

import pandas as pd

import stats
from indicators import (
    detect_fvg, filter_unfilled_fvg, get_recent_fvg,
    detect_order_blocks, update_mitigation, get_nearest_ob,
    find_swings, determine_bias, get_recent_choch, get_recent_structure_break,
    find_swing_liquidity, detect_sweeps, get_recent_sweep,
    compute_fib_from_sweep,
)
from indicators.fibonacci import compute_fib_from_sweep_bearish
from strategy.killzone import get_active_killzone
from strategy.scoring import _score_confluences, _safe_rr
from config import cfg

log = logging.getLogger(__name__)

_SCANNER = "scan_golden_setup"


def _to_comparable_dt(value) -> datetime | None:
    """
    Normalize a time value (pandas.Timestamp, numpy.datetime64, or datetime)
    into a timezone-aware UTC python datetime so comparisons never raise
    on tz-aware vs tz-naive mismatch.

    BUGFIX: the original code compared choch.time <= sweep_time directly.
    Depending on the data source one side could be tz-naive and the other
    tz-aware, raising TypeError which was swallowed by the caller's try/except,
    silently dropping valid signals.
    """
    if value is None:
        return None
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts.to_pydatetime()


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


def scan_golden_setup(
    tf_data: dict[str, pd.DataFrame],
    direction: str = "LONG",  # "LONG" | "SHORT"
) -> dict | None:
    """
    Returns a signal dict if Tier S criteria met, else None.
    direction is pre-determined by the caller based on session bias.

    OTE and FVG/OB are now SOFT confluences.  Entry zone priority:
      1. FVG (price inside)
      2. Fresh OB (price inside ± margin)
      3. OTE band fallback (price must be inside OTE)
    A setup with no FVG, no OB, and price outside OTE has no actionable entry
    and is skipped.
    """
    m5 = tf_data.get("M5")
    m1 = tf_data.get("M1")
    h1 = tf_data.get("H1")
    h4 = tf_data.get("H4")

    if m5 is None or h1 is None or h4 is None or m5.empty or h1.empty or h4.empty:
        stats.record(_SCANNER, "no_data")
        return None

    # Hard gate 1: active killzone
    killzone = get_active_killzone()
    if killzone is None:
        stats.record(_SCANNER, "no_killzone")
        return None

    # Hard gate 2: H4 bias
    h4_swings = find_swings(h4, lookback=cfg.SWING_LOOKBACK)
    h4_bias = determine_bias(h4_swings)
    expected_bias = "BULLISH" if direction == "LONG" else "BEARISH"
    if h4_bias != expected_bias:
        log.debug("H4 bias %s ≠ %s — Tier S skip", h4_bias, expected_bias)
        stats.record(_SCANNER, "h4_bias_mismatch")
        return None

    # Hard gate 3: H1 bias
    h1_swings = find_swings(h1, lookback=cfg.SWING_LOOKBACK)
    h1_bias = determine_bias(h1_swings)
    if h1_bias != expected_bias:
        log.debug("H1 bias %s ≠ %s — Tier S skip", h1_bias, expected_bias)
        stats.record(_SCANNER, "h1_bias_mismatch")
        return None

    # Hard gate 4: M5 recent SSL sweep (LONG) or BSL sweep (SHORT)
    m5_swings = find_swings(m5, lookback=cfg.SWING_LOOKBACK)
    liq_levels = find_swing_liquidity(m5_swings, equal_threshold_pips=cfg.LIQUIDITY_EQUAL_THRESHOLD)
    liq_levels = detect_sweeps(m5, liq_levels, lookback_candles=20)

    sweep_type = "SSL" if direction == "LONG" else "BSL"
    recent_sweep = get_recent_sweep(liq_levels, sweep_type)  # type: ignore[arg-type]
    if recent_sweep is None:
        log.debug("No %s sweep found on M5 — Tier S skip", sweep_type)
        stats.record(_SCANNER, "no_sweep")
        return None

    # Hard gate 5: M5 structural shift in trade direction AFTER the sweep.
    choch = get_recent_structure_break(m5, m5_swings, expected_bias, lookback_candles=15)
    if choch is None:
        log.debug("No %s structure break on M5 — Tier S skip", expected_bias)
        stats.record(_SCANNER, "no_structure_break")
        return None

    # BUGFIX: normalize both datetimes before comparing (see _to_comparable_dt).
    sweep_dt = _to_comparable_dt(recent_sweep.sweep_time)
    choch_dt = _to_comparable_dt(choch.time)
    if sweep_dt is not None and choch_dt is not None and choch_dt <= sweep_dt:
        log.debug("CHoCH (%s) not after sweep (%s) — temporal order violated, Tier S skip",
                  choch_dt, sweep_dt)
        stats.record(_SCANNER, "temporal_order")
        return None

    # ── Soft zone 1: FVG on M5/M1 (last 30 candles) ────────────────────────
    m5_fvgs = detect_fvg(m5.iloc[-30:], min_size_pips=cfg.FVG_MIN_SIZE_PIPS)
    fvg_dir = "BULLISH" if direction == "LONG" else "BEARISH"
    current_price = m5.iloc[-1]["close"]
    m5_fvgs = filter_unfilled_fvg(m5_fvgs, current_price)
    recent_fvgs = get_recent_fvg(m5_fvgs, fvg_dir, n=3)

    # ── Soft zone 2: OB on M5 — mitigation on CLOSED candles only ───────────
    m5_obs = detect_order_blocks(m5.iloc[-50:], lookback=cfg.OB_LOOKBACK)
    m5_closed = m5.iloc[:-1]
    m5_obs = update_mitigation(m5_obs, m5_closed, lookback=len(m5_closed))
    ob_dir = "BULLISH" if direction == "LONG" else "BEARISH"
    nearest_ob = get_nearest_ob(m5_obs, current_price, ob_dir)

    # ── OTE fib (needed for both the confluence label and the fallback entry) ─
    if direction == "LONG":
        swing_h = max((s.price for s in m5_swings if s.type == "HIGH"), default=None)
        sweep_low = recent_sweep.price
        if swing_h is None:
            log.debug("No M5 swing HIGH — Tier S skip")
            stats.record(_SCANNER, "no_swing")
            return None
        fib = compute_fib_from_sweep(sweep_low, swing_h, ote_low=cfg.OTE_LOW, ote_high=cfg.OTE_HIGH)
    else:
        swing_l = min((s.price for s in m5_swings if s.type == "LOW"), default=None)
        sweep_high = recent_sweep.price
        if swing_l is None:
            log.debug("No M5 swing LOW — Tier S skip")
            stats.record(_SCANNER, "no_swing")
            return None
        fib = compute_fib_from_sweep_bearish(sweep_high, swing_l, ote_low=cfg.OTE_LOW, ote_high=cfg.OTE_HIGH)

    in_ote = fib.is_in_ote(current_price)

    # ── Entry zone: FVG > OB > OTE fallback ─────────────────────────────────
    entry_low: float | None = None
    entry_high: float | None = None
    entry_tag: str | None = None

    if recent_fvgs:
        best_fvg = recent_fvgs[-1]
        if best_fvg.bottom <= current_price <= best_fvg.top:
            entry_low, entry_high = best_fvg.bottom, best_fvg.top
            entry_tag = "FVG_M5"

    if entry_tag is None and nearest_ob is not None:
        margin = (nearest_ob.top - nearest_ob.bottom) * 0.3
        if (nearest_ob.bottom - margin) <= current_price <= (nearest_ob.top + margin):
            entry_low, entry_high = nearest_ob.bottom, nearest_ob.top
            entry_tag = "OB_M5"

    if entry_tag is None:
        # OTE fallback: current price must be inside the OTE band
        if not in_ote:
            log.debug("No entry zone — Tier S skip")
            stats.record(_SCANNER, "no_entry_zone")
            return None
        entry_low = fib.ote_low
        entry_high = fib.ote_high

    # ── Confluences (all soft except entry zone gate above) ──────────────────
    confluences = [
        "Bias_H4", "Bias_H1",
        f"{sweep_type}_Sweep",
        "CHoCH_M5",
    ]
    if entry_tag is not None:
        confluences.append(entry_tag)
    if in_ote:
        ote_label = (
            f"OTE_{cfg.OTE_LOW}"
            if abs(current_price - fib.level(cfg.OTE_LOW)) < abs(current_price - fib.level(cfg.OTE_HIGH))
            else f"OTE_{cfg.OTE_HIGH}"
        )
        confluences.append(ote_label)

    # Hard gate 7: score
    score = _score_confluences(confluences)
    if score < cfg.MIN_SCORE_S:
        log.debug("Score %d < MIN_SCORE_S %d — Tier S skip", score, cfg.MIN_SCORE_S)
        stats.record(_SCANNER, "score_below_min")
        return None

    # Hard gate 6: SL / TP then worst-case RR
    sweep_extreme = recent_sweep.price
    if direction == "LONG":
        target_tp = max((s.price for s in h1_swings if s.type == "HIGH"), default=current_price * 1.005)
    else:
        target_tp = min((s.price for s in h1_swings if s.type == "LOW"), default=current_price * 0.995)

    sl, tp = _compute_sl_tp(direction, entry_low, entry_high, sweep_extreme, target_tp)

    entry_ref = entry_high if direction == "LONG" else entry_low
    rr = _safe_rr(tp, entry_ref, sl)
    if rr is None or rr < cfg.MIN_RR_S:
        log.debug("Edge RR %.2f < MIN_RR_S %.1f — Tier S skip", rr or 0, cfg.MIN_RR_S)
        stats.record(_SCANNER, "rr_below_min")
        return None

    stats.record(_SCANNER, "EMIT")
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
