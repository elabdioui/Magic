"""Fibonacci retracement levels and OTE zone computation."""
from dataclasses import dataclass, field


@dataclass
class FibLevels:
    swing_high: float
    swing_low: float
    direction: str          # "BULLISH" (retracing down) | "BEARISH" (retracing up)
    ote_low_ratio: float = 0.618   # shallow end of OTE zone (cfg.OTE_LOW)
    ote_high_ratio: float = 0.786  # deep end of OTE zone   (cfg.OTE_HIGH)

    @property
    def range(self) -> float:
        return self.swing_high - self.swing_low

    def level(self, ratio: float) -> float:
        if self.direction == "BULLISH":
            return self.swing_high - self.range * ratio
        return self.swing_low + self.range * ratio

    @property
    def ote_low(self) -> float:
        # For BULLISH: deeper retracement (ote_high_ratio) gives lower price
        return self.level(self.ote_high_ratio) if self.direction == "BULLISH" else self.level(self.ote_low_ratio)

    @property
    def ote_high(self) -> float:
        # For BULLISH: shallower retracement (ote_low_ratio) gives higher price
        return self.level(self.ote_low_ratio) if self.direction == "BULLISH" else self.level(self.ote_high_ratio)

    @property
    def equilibrium(self) -> float:
        return self.level(0.500)

    def is_in_ote(self, price: float) -> bool:
        lo = min(self.ote_low, self.ote_high)
        hi = max(self.ote_low, self.ote_high)
        return lo <= price <= hi

    def is_in_discount(self, price: float) -> bool:
        """Below 0.5 for bullish move (discounted prices)."""
        if self.direction == "BULLISH":
            return price <= self.equilibrium
        return price >= self.equilibrium


def compute_fib_from_sweep(
    sweep_low: float,
    swing_high: float,
    ote_low: float = 0.618,
    ote_high: float = 0.786,
) -> FibLevels:
    """Build fib for a bullish setup: sweep SSL (low) → targeting swing high."""
    return FibLevels(
        swing_high=swing_high,
        swing_low=sweep_low,
        direction="BULLISH",
        ote_low_ratio=ote_low,
        ote_high_ratio=ote_high,
    )


def compute_fib_from_sweep_bearish(
    sweep_high: float,
    swing_low: float,
    ote_low: float = 0.618,
    ote_high: float = 0.786,
) -> FibLevels:
    """Build fib for a bearish setup: sweep BSL (high) → targeting swing low."""
    return FibLevels(
        swing_high=sweep_high,
        swing_low=swing_low,
        direction="BEARISH",
        ote_low_ratio=ote_low,
        ote_high_ratio=ote_high,
    )
