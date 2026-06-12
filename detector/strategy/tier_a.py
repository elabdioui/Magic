"""Tier A setups: OB Retest + Asia Fade."""
import logging
import pandas as pd
import pytz

import stats
from indicators import (
    detect_fvg, filter_unfilled_fvg, get_recent_fvg,
    detect_order_blocks, update_mitigation, get_nearest_ob,
    find_swings, determine_bias,
    find_swing_liquidity, detect_sweeps, get_recent_sweep,
    compute_fib_from_sweep, compute_fib_from_sweep_bearish,
)
from strategy.killzone import get_active_killzone
from strategy.scoring import _score_confluences, _safe_rr
from config import cfg

log = logging.getLogger(__name__)

_NY_TZ = pytz.timezone("America/New_York")

_PIP = 0.10  # XAUUSD pip unit


def get_asia_range(m15: pd.DataFrame) -> tuple[float | None, float | None]:
    """
    Compute the Asia session range using TIMESTAMPS, not row indices.

    Asia session = 20:00–00:00 New York time (authoritative project definition),
    converted to UTC with DST handled by pytz.

    BUGFIX: the original code used m15.iloc[-50:-18], a fixed index slice that
    breaks whenever MT5 has data gaps (weekends, maintenance) and ignores DST.
    That could point at completely wrong candles and produce a false Asia range.

    Returns (asia_high, asia_low), or (None, None) if no candles fall in the window.
    Requires a tz-aware 'time' column in UTC (as produced by mt5_client.get_ohlc).
    """
    if m15 is None or m15.empty or "time" not in m15.columns:
        return None, None

    times = pd.to_datetime(m15["time"], utc=True)

    # Reference "now" = latest candle time, in NY tz
    now_utc = times.iloc[-1]
    now_ny = now_utc.tz_convert(_NY_TZ)

    # Asia open = 20:00 NY of the relevant day
    asia_start_ny = now_ny.replace(hour=20, minute=0, second=0, microsecond=0)
    if now_ny.hour < 20:
        # Before 20:00 NY → Asia session started the previous calendar day
        asia_start_ny = asia_start_ny - pd.Timedelta(days=1)
    asia_end_ny = asia_start_ny + pd.Timedelta(hours=4)  # 00:00 NY next

    asia_start_utc = asia_start_ny.tz_convert("UTC")
    asia_end_utc = asia_end_ny.tz_convert("UTC")

    mask = (times >= asia_start_utc) & (times < asia_end_utc)
    asia_df = m15[mask.values]
    if asia_df.empty:
        log.debug("Asia range empty for window %s–%s UTC", asia_start_utc, asia_end_utc)
        return None, None

    return float(asia_df["high"].max()), float(asia_df["low"].min())


def _avg_volume(df: pd.DataFrame, lookback: int) -> float | None:
    """Mean volume of the `lookback` candles BEFORE the last one. None if unavailable."""
    if "volume" not in df.columns or len(df) < lookback + 1:
        return None
    window = df["volume"].iloc[-(lookback + 1):-1]
    if window.empty:
        return None
    return float(window.mean())


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
    _S = "scan_ob_retest"
    h1 = tf_data.get("H1")
    h4 = tf_data.get("H4")
    m5 = tf_data.get("M5")
    if h1 is None or h4 is None or m5 is None or h1.empty or m5.empty or h4.empty:
        stats.record(_S, "no_data")
        return None

    killzone = get_active_killzone()
    if killzone is None:
        log.debug("No killzone — OB Retest skip")
        stats.record(_S, "no_killzone")
        return None

    h4_swings = find_swings(h4, lookback=cfg.SWING_LOOKBACK)
    h4_bias = determine_bias(h4_swings)
    expected = "BULLISH" if direction == "LONG" else "BEARISH"
    if h4_bias != expected:
        log.debug("H4 bias %s ≠ %s — OB Retest skip", h4_bias, expected)
        stats.record(_S, "h4_bias_mismatch")
        return None

    current_price = m5.iloc[-1]["close"]

    # H1 OB near current price — mitigation scans full H1 df to avoid treating
    # yesterday's invalidated OBs as fresh (default lookback=5 only covers 5h).
    h1_obs = detect_order_blocks(h1, lookback=cfg.OB_LOOKBACK)
    # BUGFIX: mitigation is evaluated on CLOSED candles only (exclude the forming
    # candle). Otherwise the forming candle entering the OB sets touched=True and
    # get_nearest_ob excludes the very OB whose retest we are trying to signal.
    h1_closed = h1.iloc[:-1]
    h1_obs = update_mitigation(h1_obs, h1_closed, lookback=len(h1_closed))
    ob_dir = "BULLISH" if direction == "LONG" else "BEARISH"
    ob = get_nearest_ob(h1_obs, current_price, ob_dir)
    if ob is None:
        log.debug("No H1 OB near price — OB Retest skip")
        stats.record(_S, "no_ob")
        return None

    # Price must be inside or just touching the OB
    margin = (ob.top - ob.bottom) * 0.3
    in_zone = (ob.bottom - margin) <= current_price <= (ob.top + margin)
    if not in_zone:
        log.debug("Price %.2f outside OB zone — OB Retest skip", current_price)
        stats.record(_S, "price_outside_ob")
        return None

    # M5 FVG as confirmation
    m5_fvgs = detect_fvg(m5.iloc[-20:], min_size_pips=cfg.FVG_MIN_SIZE_PIPS)
    fvg_dir = "BULLISH" if direction == "LONG" else "BEARISH"
    m5_fvgs = filter_unfilled_fvg(m5_fvgs, current_price)
    recent_fvgs = get_recent_fvg(m5_fvgs, fvg_dir, n=2)

    confluences = ["Bias_H4", "OB_H1"]
    if recent_fvgs:
        confluences.append("FVG_M5")

    score = _score_confluences(confluences)
    if score < cfg.MIN_SCORE_A:
        log.debug("Score %d < MIN_SCORE_A %d — OB Retest skip", score, cfg.MIN_SCORE_A)
        stats.record(_S, "score_below_min")
        return None

    h1_swings = find_swings(h1, lookback=cfg.SWING_LOOKBACK)
    h1_bias = determine_bias(h1_swings)
    if direction == "LONG":
        target_tp = max((s.price for s in h1_swings if s.type == "HIGH"), default=current_price * 1.004)
        sl = ob.bottom - 3 * 0.10
    else:
        target_tp = min((s.price for s in h1_swings if s.type == "LOW"), default=current_price * 0.996)
        sl = ob.top + 3 * 0.10

    entry_ref = ob.top if direction == "LONG" else ob.bottom
    rr = _safe_rr(target_tp, entry_ref, sl)
    if rr is None or rr < cfg.MIN_RR:
        log.debug("RR %.2f < MIN_RR %.1f — OB Retest skip", rr or 0, cfg.MIN_RR)
        stats.record(_S, "rr_below_min")
        return None

    stats.record(_S, "EMIT")
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
        "bias_h1": h1_bias,
        "confluences": confluences,
        "confluence_score": score,
        "estimated_winrate": 0.62,
    }


def scan_asia_fade(
    tf_data: dict[str, pd.DataFrame],
    direction: str = "LONG",
) -> dict | None:
    """
    Asia Fade: sweep of Asia session extreme, then fade back inside the range.

    Hard gates:
      1. Active killzone in {LONDON, NY_AM}
      2. Asia range >= ASIA_MIN_RANGE_PIPS
      3. Sweep of Asia extreme in last 20 closed M5 candles + close back inside
      4. Current price back inside Asia range
      5. Worst-case RR >= MIN_RR_A
      6. score >= MIN_SCORE_A

    Soft confluences (never gate):
      Asia_Sweep, Bias_H4, SFP_Wick (M15), Volume_Spike (M15), FVG_M5
    """
    _S = "scan_asia_fade"

    # Hard gate 1
    killzone = get_active_killzone()
    if killzone not in ("LONDON", "NY_AM"):
        stats.record(_S, "no_killzone")
        return None

    m15 = tf_data.get("M15")
    m5 = tf_data.get("M5")
    h4 = tf_data.get("H4")
    if m15 is None or m5 is None or h4 is None or m15.empty or m5.empty or h4.empty:
        stats.record(_S, "no_data")
        return None

    # Hard gate 2: Asia range size
    asia_high, asia_low = get_asia_range(m15)
    if asia_high is None or asia_low is None:
        log.debug("No valid Asia range — Asia Fade skip")
        stats.record(_S, "no_asia_range")
        return None

    if (asia_high - asia_low) < cfg.ASIA_MIN_RANGE_PIPS * _PIP:
        log.debug("Asia range %.2f < %.1f pips — Asia Fade skip",
                  asia_high - asia_low, cfg.ASIA_MIN_RANGE_PIPS)
        stats.record(_S, "range_too_small")
        return None

    current_price = float(m5.iloc[-1]["close"])
    m5_closed = m5.iloc[:-1]
    lookback = min(20, len(m5_closed))
    recent_m5 = m5_closed.iloc[-lookback:]

    # Hard gate 3: sweep of Asia extreme (last 20 closed M5) + close back inside
    found_sweep = False
    sweep_extreme: float | None = None
    close_back = False

    for i in range(len(recent_m5)):
        row = recent_m5.iloc[i]
        if direction == "LONG" and row["low"] < asia_low:
            found_sweep = True
            if sweep_extreme is None:
                sweep_extreme = float(row["low"])
            else:
                sweep_extreme = min(sweep_extreme, float(row["low"]))
        elif direction == "SHORT" and row["high"] > asia_high:
            found_sweep = True
            if sweep_extreme is None:
                sweep_extreme = float(row["high"])
            else:
                sweep_extreme = max(sweep_extreme, float(row["high"]))
        if found_sweep:
            if direction == "LONG" and float(row["close"]) > asia_low:
                close_back = True
            elif direction == "SHORT" and float(row["close"]) < asia_high:
                close_back = True

    if not found_sweep:
        log.debug("No M5 sweep of Asia extreme in last 20 candles — Asia Fade skip")
        stats.record(_S, "no_sweep")
        return None
    if not close_back:
        log.debug("No close back inside range after sweep — Asia Fade skip")
        stats.record(_S, "no_reintegration")
        return None

    # Hard gate 4: current price back inside Asia range
    if not (asia_low < current_price < asia_high):
        log.debug("Price %.2f not inside Asia range [%.2f, %.2f] — Asia Fade skip",
                  current_price, asia_low, asia_high)
        stats.record(_S, "price_outside_range")
        return None

    # ── Soft confluences ────────────────────────────────────────────────────
    confluences = ["Asia_Sweep"]

    h4_swings = find_swings(h4, lookback=cfg.SWING_LOOKBACK)
    h4_bias = determine_bias(h4_swings)
    expected = "BULLISH" if direction == "LONG" else "BEARISH"
    if h4_bias == expected:
        confluences.append("Bias_H4")

    # SFP_Wick: last CLOSED M15 candle wicks beyond extreme and closes inside
    if len(m15) >= 2:
        m15_confirm = m15.iloc[-2]
        if direction == "LONG":
            sfp_wick = float(m15_confirm["low"]) < asia_low and float(m15_confirm["close"]) > asia_low
        else:
            sfp_wick = float(m15_confirm["high"]) > asia_high and float(m15_confirm["close"]) < asia_high
        if sfp_wick:
            confluences.append("SFP_Wick")
            avg_vol = _avg_volume(m15.iloc[:-1], cfg.SFP_VOLUME_LOOKBACK)
            if avg_vol is not None and "volume" in m15.columns:
                if float(m15_confirm["volume"]) > cfg.SFP_VOLUME_FACTOR * avg_vol:
                    confluences.append("Volume_Spike")

    # FVG_M5: unfilled FVG in trade direction within last 20 closed candles
    m5_fvgs = detect_fvg(recent_m5, min_size_pips=cfg.FVG_MIN_SIZE_PIPS)
    fvg_dir = "BULLISH" if direction == "LONG" else "BEARISH"
    m5_fvgs = filter_unfilled_fvg(m5_fvgs, current_price)
    recent_fvgs = get_recent_fvg(m5_fvgs, fvg_dir, n=3)
    if recent_fvgs:
        confluences.append("FVG_M5")

    # Hard gate 6: score
    score = _score_confluences(confluences)
    if score < cfg.MIN_SCORE_A:
        log.debug("Score %d < MIN_SCORE_A %d — Asia Fade skip", score, cfg.MIN_SCORE_A)
        stats.record(_S, "score_below_min")
        return None

    # ── Entry zone: FVG (price inside) > fallback band ──────────────────────
    entry_low: float | None = None
    entry_high: float | None = None

    if recent_fvgs:
        best_fvg = recent_fvgs[-1]
        if best_fvg.bottom <= current_price <= best_fvg.top:
            entry_low, entry_high = best_fvg.bottom, best_fvg.top

    if entry_low is None:
        fade_zone = cfg.ASIA_FADE_ZONE_PIPS * _PIP
        if direction == "LONG":
            entry_low = asia_low
            entry_high = asia_low + fade_zone
        else:
            entry_high = asia_high
            entry_low = asia_high - fade_zone

    # Hard gate 5: SL / TP, then worst-case RR
    if direction == "LONG":
        sl = sweep_extreme - cfg.SL_BUFFER  # type: ignore[operator]
        tp = asia_high
        entry_ref = entry_high
    else:
        sl = sweep_extreme + cfg.SL_BUFFER  # type: ignore[operator]
        tp = asia_low
        entry_ref = entry_low

    rr = _safe_rr(tp, entry_ref, sl)
    if rr is None or rr < cfg.MIN_RR_A:
        log.debug("RR %.2f < MIN_RR_A %.1f — Asia Fade skip", rr or 0, cfg.MIN_RR_A)
        stats.record(_S, "rr_below_min")
        return None

    stats.record(_S, "EMIT")
    return {
        "tier": "A",
        "direction": direction,
        "pattern": "Asia Fade",
        "killzone": killzone,
        "entry_zone_low": round(entry_low, 2),
        "entry_zone_high": round(entry_high, 2),
        "stop_loss": round(sl, 2),
        "take_profit": round(tp, 2),
        "bias_h4": h4_bias,
        "bias_h1": expected,
        "confluences": confluences,
        "confluence_score": score,
        "estimated_winrate": 0.62,
    }
