import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from root (VPS mono-machine) then fall back to local detector/.env
_root_env = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=_root_env if _root_env.exists() else None)


class Config:
    MT5_LOGIN: int = int(os.getenv("MT5_LOGIN", "0"))
    MT5_PASSWORD: str = os.getenv("MT5_PASSWORD", "")
    MT5_SERVER: str = os.getenv("MT5_SERVER", "")

    SYMBOL: str = os.getenv("SYMBOL", "XAUUSD")
    SCAN_INTERVAL_SECONDS: int = int(os.getenv("SCAN_INTERVAL_SECONDS", "30"))

    BACKEND_WEBHOOK_URL: str = os.getenv("BACKEND_WEBHOOK_URL", "")
    WEBHOOK_HMAC_SECRET: str = os.getenv("WEBHOOK_HMAC_SECRET", "")

    ENABLED_TIERS: list[str] = os.getenv("ENABLED_TIERS", "S,A,B").split(",")
    ENABLED_KILLZONES: list[str] = os.getenv("ENABLED_KILLZONES", "LONDON,NY_AM,NY_PM").split(",")

    TIMEZONE: str = os.getenv("TIMEZONE", "Africa/Casablanca")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # Candle counts per timeframe for OHLC fetch
    OHLC_COUNT_M1: int = 200
    OHLC_COUNT_M5: int = 200
    OHLC_COUNT_M15: int = 100
    OHLC_COUNT_H1: int = 100
    OHLC_COUNT_H4: int = 60
    OHLC_COUNT_D1: int = 30

    # ICT params
    FVG_MIN_SIZE_PIPS: float = 3.0      # minimum FVG size (XAUUSD pip = 0.1)
    OB_LOOKBACK: int = 30               # candles to look back for OB detection
    OB_MITIGATION_LOOKBACK: int = 5     # candles to scan for OB mitigation
    SWING_LOOKBACK: int = 5             # candles each side for swing detection
    OTE_LOW: float = 0.618              # shallow OTE boundary (Fibonacci ratio)
    OTE_HIGH: float = 0.786             # deep OTE boundary   (Fibonacci ratio)
    LIQUIDITY_EQUAL_THRESHOLD: float = 0.50  # pips, equal high/low tolerance
    # Per-tier minimum confluence scores (old MIN_CONFLUENCE_SCORE=4 kept as fallback)
    MIN_CONFLUENCE_SCORE: int = 4
    MIN_SCORE_S: int = 7   # Tier S: requires strong confluences
    MIN_SCORE_A: int = 5   # Tier A: moderate
    MIN_SCORE_B: int = 4   # Tier B: baseline


cfg = Config()
