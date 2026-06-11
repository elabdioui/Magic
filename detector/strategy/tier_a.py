"""Tier A setups: OB Retest + London Open Sweep."""
import logging
import pandas as pd
import pytz

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
    if h1 is None or h4 is None or m5 is None or h1.empty or m5.empty or h4.empty:
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

    score = _score_confluences(confluences)
    if score < cfg.MIN_SCORE_A:
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
        "bias_h1": h1_bias,
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
    if m15 is None or m5 is None or h4 is None or m15.empty or m5.empty or h4.empty:
        return None

    h4_swings = find_swings(h4, lookback=cfg.SWING_LOOKBACK)
    h4_bias = determine_bias(h4_swings)
    expected = "BULLISH" if direction == "LONG" else "BEARISH"
    if h4_bias != expected:
        return None

    # BUGFIX: Asia range now computed from timestamps (20:00–00:00 NY), not iloc.
    asia_high, asia_low = get_asia_range(m15)
    if asia_high is None or asia_low is None:
        log.debug("No valid Asia range — London Sweep skip")
        return None

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
    score = _score_confluences(confluences)

    if direction == "LONG":
        sl = sweep_extreme - 3 * 0.10
        target_tp = asia_high
    else:
        sl = sweep_extreme + 3 * 0.10
        target_tp = asia_low

    entry_ref = best_fvg.top if direction == "LONG" else best_fvg.bottom
    rr = _safe_rr(target_tp, entry_ref, sl)
    if rr is None or rr < cfg.MIN_RR:
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
    
# ──────────────────────────────────────────────────────────────────────────────
# SFP (Swing Failure Pattern) at Asia range extreme + OTE + volume confirmation
# ──────────────────────────────────────────────────────────────────────────────

def _avg_volume(df: pd.DataFrame, lookback: int) -> float | None:
    """Mean volume of the `lookback` candles BEFORE the last one. None if unavailable."""
    if "volume" not in df.columns or len(df) < lookback + 1:
        return None
    window = df["volume"].iloc[-(lookback + 1):-1]
    if window.empty:
        return None
    return float(window.mean())


def scan_sfp_asia(
    tf_data: dict[str, pd.DataFrame],
    direction: str = "LONG",
) -> dict | None:
    """
    SFP Asia + OTE (document Setup 3, tightened):
    - Active killzone LONDON or NY_AM
    - H4 bias aligned
    - Confirmation candle (M15) wicks BEYOND the Asia extreme but CLOSES back inside
    - Reintegration candle volume > factor * average of previous N candles
    - The sweep occurs within OTE (0.618–0.786) of the recent M15 leg (HTF proxy)
    - RR target 2.5–3.0 (reject < 2.0)

    NOTE: the OTE "daily leg" from the doc is approximated by the most recent M15
    swing leg, since clean D1 legs are not always available. Documented approximation.
    estimated_winrate = 0.65 is UNVALIDATED — needs backtest before trusting it.
    """
    killzone = get_active_killzone()
    if killzone not in ("LONDON", "NY_AM"):
        return None

    m15 = tf_data.get("M15")
    m5 = tf_data.get("M5")
    h4 = tf_data.get("H4")
    if m15 is None or m5 is None or h4 is None or m15.empty or m5.empty or h4.empty:
        return None

    h4_swings = find_swings(h4, lookback=cfg.SWING_LOOKBACK)
    h4_bias = determine_bias(h4_swings)
    expected = "BULLISH" if direction == "LONG" else "BEARISH"
    if h4_bias != expected:
        return None

    asia_high, asia_low = get_asia_range(m15)
    if asia_high is None or asia_low is None:
        return None

    # Confirmation candle = last CLOSED M15 candle (iloc[-2]; iloc[-1] may be forming).
    if len(m15) < 2:
        return None
    confirm = m15.iloc[-2]

    # SFP geometry: wick beyond Asia extreme, close back inside the range.
    if direction == "LONG":
        wick_beyond = confirm["low"] < asia_low
        closed_inside = confirm["close"] > asia_low
        sweep_wick = confirm["low"]
    else:
        wick_beyond = confirm["high"] > asia_high
        closed_inside = confirm["close"] < asia_high
        sweep_wick = confirm["high"]

    if not (wick_beyond and closed_inside):
        return None

    # Volume confirmation on the reintegration (confirmation) candle.
    avg_vol = _avg_volume(m15.iloc[:-1], cfg.SFP_VOLUME_LOOKBACK)
    if avg_vol is None:
        return None
    if "volume" not in m15.columns or confirm["volume"] <= cfg.SFP_VOLUME_FACTOR * avg_vol:
        return None

    # OTE filter: the sweep wick must sit in the OTE (0.618–0.786) retracement of
    # the recent M15 leg. BUGFIX: the fib was previously anchored on the Asia
    # extreme itself, putting the OTE zone strictly inside the range while the
    # sweep wick is by definition beyond it — the check could never pass.
    # The leg is now defined by the M15 swing extremes (leg low → leg high).
    m15_swings = find_swings(m15, lookback=cfg.SWING_LOOKBACK)
    current_price = m5.iloc[-1]["close"]
    swing_h = max((s.price for s in m15_swings if s.type == "HIGH"), default=None)
    swing_l = min((s.price for s in m15_swings if s.type == "LOW"), default=None)
    if swing_h is None or swing_l is None or swing_h <= swing_l:
        return None

    if direction == "LONG":
        # Up-leg swing_l → swing_h; sweep wick must be a 0.618–0.786 retracement.
        fib = compute_fib_from_sweep(swing_l, swing_h, ote_low=cfg.OTE_LOW, ote_high=cfg.OTE_HIGH)
    else:
        # Down-leg swing_h → swing_l; sweep wick must be a 0.618–0.786 retracement.
        fib = compute_fib_from_sweep_bearish(swing_h, swing_l, ote_low=cfg.OTE_LOW, ote_high=cfg.OTE_HIGH)

    if not fib.is_in_ote(sweep_wick):
        return None

    # Optional FVG confluence on M5
    m5_fvgs = detect_fvg(m5.iloc[-20:], min_size_pips=cfg.FVG_MIN_SIZE_PIPS)
    fvg_dir = "BULLISH" if direction == "LONG" else "BEARISH"
    m5_fvgs = filter_unfilled_fvg(m5_fvgs, current_price)
    recent_fvgs = get_recent_fvg(m5_fvgs, fvg_dir, n=2)

    confluences = ["Bias_H4", "Asia_SFP", "Volume_Confirm", "OTE"]
    if recent_fvgs:
        confluences.append("FVG_M5")
    score = _score_confluences(confluences)
    if score < cfg.MIN_SCORE_A:
        return None

    # Entry zone = the FVG if present, else the confirmation candle body back inside range.
    if recent_fvgs:
        best = recent_fvgs[-1]
        entry_low, entry_high = best.bottom, best.top
    else:
        entry_low = min(confirm["open"], confirm["close"])
        entry_high = max(confirm["open"], confirm["close"])

    buf = cfg.SFP_SL_BUFFER_PIPS * 0.10
    if direction == "LONG":
        sl = sweep_wick - buf
        tp = asia_high
    else:
        sl = sweep_wick + buf
        tp = asia_low

    entry_ref = entry_high if direction == "LONG" else entry_low
    rr = _safe_rr(tp, entry_ref, sl)
    if rr is None or rr < cfg.MIN_RR_A:
        return None

    return {
        "tier": "A",
        "direction": direction,
        "pattern": "SFP + OTE Asia",
        "killzone": killzone,
        "entry_zone_low": round(entry_low, 2),
        "entry_zone_high": round(entry_high, 2),
        "stop_loss": round(sl, 2),
        "take_profit": round(tp, 2),
        "bias_h4": h4_bias,
        "bias_h1": h4_bias,   # SFP Asia uses H4+M15 only — no H1 bias computed
        "confluences": confluences,
        "confluence_score": score,
        "estimated_winrate": 0.65,
    }