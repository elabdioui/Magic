"""Buy-Side / Sell-Side Liquidity detection and sweep identification."""
import pandas as pd
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from .structure import Swing


@dataclass
class LiquidityLevel:
    type: Literal["BSL", "SSL"]   # Buy-Side (above highs) / Sell-Side (below lows)
    price: float
    time: datetime
    swept: bool = False
    sweep_time: datetime | None = None


def find_equal_highs_lows(
    df: pd.DataFrame,
    tolerance_pips: float = 0.50,
) -> list[LiquidityLevel]:
    """
    Equal highs = BSL (stops sitting above).
    Equal lows  = SSL (stops sitting below).
    """
    pip_unit = 0.10
    tol = tolerance_pips * pip_unit
    levels: list[LiquidityLevel] = []

    highs = df["high"].values
    lows = df["low"].values
    times = df["time"].values

    for i in range(len(df) - 1):
        for j in range(i + 1, min(i + 20, len(df))):
            if abs(highs[i] - highs[j]) <= tol:
                levels.append(LiquidityLevel("BSL", (highs[i] + highs[j]) / 2, times[i]))
                break
            if abs(lows[i] - lows[j]) <= tol:
                levels.append(LiquidityLevel("SSL", (lows[i] + lows[j]) / 2, times[i]))
                break

    return levels


def find_swing_liquidity(
    swings: list[Swing],
    equal_threshold_pips: float = 0.50,
) -> list[LiquidityLevel]:
    """Major swing highs = BSL, major swing lows = SSL.
    Merges levels within equal_threshold_pips to avoid duplicate sweeps."""
    pip_unit = 0.10
    tol = equal_threshold_pips * pip_unit
    levels: list[LiquidityLevel] = []

    for s in swings:
        ltype: Literal["BSL", "SSL"] = "BSL" if s.type == "HIGH" else "SSL"
        merged = False
        for existing in levels:
            if existing.type == ltype and abs(existing.price - s.price) <= tol:
                # Keep the more recent level
                if s.time > existing.time:
                    existing.price = s.price
                    existing.time = s.time
                merged = True
                break
        if not merged:
            levels.append(LiquidityLevel(ltype, s.price, s.time))

    return levels


def detect_sweeps(
    df: pd.DataFrame,
    levels: list[LiquidityLevel],
    lookback_candles: int = 5,
) -> list[LiquidityLevel]:
    """
    A sweep occurs when price wicks through a liquidity level then closes back.
    BSL sweep: wick above BSL price then close below it.
    SSL sweep: wick below SSL price then close above it.
    """
    if df.empty:
        return levels

    recent = df.iloc[-lookback_candles:]

    for level in levels:
        if level.swept:
            continue
        for _, row in recent.iterrows():
            if level.type == "BSL":
                # wick above then close below
                if row["high"] > level.price and row["close"] < level.price:
                    level.swept = True
                    level.sweep_time = row["time"]
                    break
            elif level.type == "SSL":
                # wick below then close above
                if row["low"] < level.price and row["close"] > level.price:
                    level.swept = True
                    level.sweep_time = row["time"]
                    break

    return levels


def get_recent_sweep(
    levels: list[LiquidityLevel],
    sweep_type: Literal["BSL", "SSL"],
    lookback_candles: int = 10,
    df: pd.DataFrame | None = None,
) -> LiquidityLevel | None:
    """Return the most recently swept level of the given type."""
    swept = [l for l in levels if l.swept and l.type == sweep_type]
    if not swept:
        return None
    return max(swept, key=lambda l: l.sweep_time or l.time)
