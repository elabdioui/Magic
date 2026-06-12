"""ORB NY — Opening Range Breakout. Minimal control-group strategy: 3 params, no confluences."""
import logging
from datetime import time as dtime

import pandas as pd
import pytz

import stats
from config import cfg
from strategy.scoring import _safe_rr

log = logging.getLogger(__name__)

_NY_TZ = pytz.timezone("America/New_York")
_PIP = 0.10  # XAUUSD pip unit

_OR_START = dtime(9, 30)   # 09:30 NY
_OR_END   = dtime(10, 0)   # 10:00 NY  (after OR window closes)
_CUTOFF   = dtime(12, 0)   # 12:00 NY  (fixed, not a config knob)

# module-level guard: direction -> NY date string "YYYY-MM-DD"
_emitted: dict[str, str] = {}


def _reset_daily_guard() -> None:
    """Test helper — clears the daily emission guard."""
    _emitted.clear()


def scan_orb_ny(timeframes: dict, direction: str) -> dict | None:
    m5 = timeframes.get("M5")
    if m5 is None or m5.empty:
        log.debug("orb_ny: no M5 data")
        stats.record("scan_orb_ny", "no_m5_data")
        return None

    times_utc = pd.to_datetime(m5["time"], utc=True)

    # Last CLOSED candle = second-to-last row (last row is still forming)
    if len(m5) < 2:
        stats.record("scan_orb_ny", "insufficient_candles")
        return None

    last_closed_time_utc = times_utc.iloc[-2]
    now_ny = last_closed_time_utc.tz_convert(_NY_TZ)
    now_ny_date = now_ny.date()
    now_ny_time = now_ny.time()

    # Gate: must be after OR window closes and before cutoff
    if now_ny_time < _OR_END or now_ny_time >= _CUTOFF:
        log.debug("orb_ny: outside_window (NY time %s)", now_ny_time)
        stats.record("scan_orb_ny", "outside_window")
        return None

    # Build OR window: [09:30, 09:30 + ORB_WINDOW_MINUTES) on the current NY date
    or_start_ny = _NY_TZ.localize(
        pd.Timestamp(now_ny_date).to_pydatetime().replace(hour=9, minute=30, second=0, microsecond=0)
    )
    or_end_ny = or_start_ny + pd.Timedelta(minutes=cfg.ORB_WINDOW_MINUTES)

    or_start_utc = or_start_ny.astimezone(pytz.utc)
    or_end_utc   = or_end_ny.astimezone(pytz.utc)

    or_mask = (times_utc >= or_start_utc) & (times_utc < or_end_utc)
    # exclude last (forming) candle from the OR window too
    or_mask.iloc[-1] = False
    or_df = m5[or_mask.values]

    expected_candles = cfg.ORB_WINDOW_MINUTES // 5
    if len(or_df) < expected_candles:
        log.debug("orb_ny: or_incomplete (got %d, need %d)", len(or_df), expected_candles)
        stats.record("scan_orb_ny", "or_incomplete")
        return None

    or_high = float(or_df["high"].max())
    or_low  = float(or_df["low"].min())

    if (or_high - or_low) < cfg.ORB_MIN_RANGE_PIPS * _PIP:
        log.debug("orb_ny: range_too_small (%.2f pips)", (or_high - or_low) / _PIP)
        stats.record("scan_orb_ny", "range_too_small")
        return None

    # Candles AFTER the OR window and up to (and including) last closed candle
    after_mask = (times_utc >= or_end_utc) & (times_utc <= last_closed_time_utc)
    after_df = m5[after_mask.values]

    if after_df.empty:
        log.debug("orb_ny: no_post_or_candles")
        stats.record("scan_orb_ny", "no_post_or_candles")
        return None

    # Find first breakout candle for each direction
    long_break_idx  = after_df.index[after_df["close"] > or_high].min() if (after_df["close"] > or_high).any() else None
    short_break_idx = after_df.index[after_df["close"] < or_low].any() and after_df.index[after_df["close"] < or_low].min()
    # recalculate cleanly
    long_candidates  = after_df[after_df["close"] > or_high]
    short_candidates = after_df[after_df["close"] < or_low]

    long_first_idx  = long_candidates.index[0]  if not long_candidates.empty  else None
    short_first_idx = short_candidates.index[0] if not short_candidates.empty else None

    last_closed_idx = after_df.index[-1]

    if direction == "LONG":
        if long_first_idx is None:
            log.debug("orb_ny: no_long_breakout")
            stats.record("scan_orb_ny", "no_long_breakout")
            return None
        # Breakout must be the MOST RECENT closed candle
        if long_first_idx != last_closed_idx:
            log.debug("orb_ny: breakout_stale")
            stats.record("scan_orb_ny", "breakout_stale")
            return None
        # Opposite side broke first?
        if short_first_idx is not None and short_first_idx < long_first_idx:
            log.debug("orb_ny: opposite_broke_first")
            stats.record("scan_orb_ny", "opposite_broke_first")
            return None
        breakout_candle = m5.loc[long_first_idx]
        entry_ref = or_high
        sl        = or_low

    else:  # SHORT
        if short_first_idx is None:
            log.debug("orb_ny: no_short_breakout")
            stats.record("scan_orb_ny", "no_short_breakout")
            return None
        if short_first_idx != last_closed_idx:
            log.debug("orb_ny: breakout_stale")
            stats.record("scan_orb_ny", "breakout_stale")
            return None
        if long_first_idx is not None and long_first_idx < short_first_idx:
            log.debug("orb_ny: opposite_broke_first")
            stats.record("scan_orb_ny", "opposite_broke_first")
            return None
        breakout_candle = m5.loc[short_first_idx]
        entry_ref = or_low
        sl        = or_high

    # Daily guard
    ny_date_str = str(now_ny_date)
    if _emitted.get(direction) == ny_date_str:
        log.debug("orb_ny: already_emitted (dir=%s date=%s)", direction, ny_date_str)
        stats.record("scan_orb_ny", "already_emitted")
        return None

    # SL / TP
    risk = abs(entry_ref - sl)
    if direction == "LONG":
        tp = entry_ref + cfg.ORB_TP_R * risk
    else:
        tp = entry_ref - cfg.ORB_TP_R * risk

    rr = _safe_rr(tp, entry_ref, sl)
    if rr is None or rr < 1.0:
        log.debug("orb_ny: rr_degenerate (rr=%s)", rr)
        stats.record("scan_orb_ny", "rr_degenerate")
        return None

    pip2 = 2 * _PIP
    if direction == "LONG":
        entry_zone_low  = or_high - pip2
        entry_zone_high = or_high + pip2
    else:
        entry_zone_low  = or_low - pip2
        entry_zone_high = or_low + pip2

    _emitted[direction] = ny_date_str

    # ORB is deliberately unscored — fixed score, no _score_confluences call, no min-score gate
    stats.record("scan_orb_ny", "EMIT")
    log.debug("orb_ny: EMIT dir=%s entry_ref=%.2f sl=%.2f tp=%.2f rr=%.2f", direction, entry_ref, sl, tp, rr)

    return {
        "tier":             "ORB",
        "pattern":          "ORB NY",
        "direction":        direction,
        "confluences":      ["ORB_Breakout"],
        "confluence_score": 7,
        "entry_zone_low":   round(entry_zone_low, 2),
        "entry_zone_high":  round(entry_zone_high, 2),
        "stop_loss":        round(sl, 2),
        "take_profit":      round(tp, 2),
        "rr":               round(rr, 2),
    }
