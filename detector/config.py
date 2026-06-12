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
    MT5_PATH: str = os.getenv("MT5_PATH", "")
    MT5_INIT_RETRIES: int = int(os.getenv("MT5_INIT_RETRIES", "10"))
    MT5_INIT_RETRY_DELAY_SECONDS: int = int(os.getenv("MT5_INIT_RETRY_DELAY_SECONDS", "30"))
    HEARTBEAT_MINUTES: int = int(os.getenv("HEARTBEAT_MINUTES", "15"))

    SYMBOL: str = os.getenv("SYMBOL", "XAUUSD")
    SCAN_INTERVAL_SECONDS: int = int(os.getenv("SCAN_INTERVAL_SECONDS", "30"))

    BACKEND_WEBHOOK_URL: str = os.getenv("BACKEND_WEBHOOK_URL", "")
    WEBHOOK_HMAC_SECRET: str = os.getenv("WEBHOOK_HMAC_SECRET", "")

    SHEETS_WEBHOOK_URL: str = os.getenv("SHEETS_WEBHOOK_URL", "")
    SHEETS_WEBHOOK_TOKEN: str = os.getenv("SHEETS_WEBHOOK_TOKEN", "")

    ENABLED_TIERS: list[str] = os.getenv("ENABLED_TIERS", "S,A,B,ORB").split(",")
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
    MIN_RR: float = 1.5    # minimum risk/reward ratio (worst-case fill)
    MIN_RR_A: float = 2.0  # Tier A minimum RR (Asia Fade, OB Retest)
    MIN_RR_S: float = 2.0  # Tier S Golden Setup minimum RR (worst-case edge)
    SL_BUFFER: float = 0.30  # distance beyond zone edge for stop-loss (3 pips × 0.10)
    REGIME_ATR_PERIOD: int = 14          # ATR look-back for regime detection
    REGIME_VOL_MULTIPLIER: float = 2.0   # ATR ratio above which regime = high_vol
    REGIME_RANGE_MULTIPLIER: float = 0.5 # ATR ratio below which regime = range
    CONFLUENCE_WEIGHTS: dict[str, int] = {
        # Tier B / shared
        "Bias_H4":      2,
        "BOS_M5":       2,
        "FVG_M5":       1,
        "Breaker_M5":   2,
        "OTE":          2,
        "Sweep":        3,
        # Tier A
        "OB_H1":        2,
        "Asia_Sweep":   3,
        "Asia_SFP":     2,
        "Volume_Confirm": 1,
        "SFP_Wick":     1,
        "Volume_Spike": 1,
        # Tier S
        "Bias_H1":      2,
        "OB_M5":        2,
        "SSL_Sweep":    3,
        "BSL_Sweep":    3,
        "CHoCH_M5":     2,
        "CHoCH_M1":     2,
        "FVG_M1":       1,
        # Tier SWING
        "SR_Level":         2,
        "Breakout_Volume":  2,
        "Polarity_Retest":  2,
        "Rejection_Candle": 2,
    }
    
    # SFP Asia + OTE (Tier A new)
    SFP_VOLUME_LOOKBACK: int = 10       # candles for the avg-volume baseline
    SFP_VOLUME_FACTOR: float = 1.0      # reintegration candle vol > factor * avg
    SFP_SL_BUFFER_PIPS: float = 8.0     # 5–10 pip range from the doc

    # ORB NY (Opening Range Breakout) — 3 tunable params, no ICT confluences
    ORB_WINDOW_MINUTES: int = int(os.getenv("ORB_WINDOW_MINUTES", "30"))
    ORB_TP_R: float = float(os.getenv("ORB_TP_R", "1.5"))
    ORB_MIN_RANGE_PIPS: float = float(os.getenv("ORB_MIN_RANGE_PIPS", "10"))

    # Asia Fade (Tier A)
    ASIA_MIN_RANGE_PIPS: float = float(os.getenv("ASIA_MIN_RANGE_PIPS", "15.0"))
    ASIA_FADE_ZONE_PIPS: float = float(os.getenv("ASIA_FADE_ZONE_PIPS", "5.0"))

    # Break & Retest S/R (Tier SWING new)
    SR_MIN_REJECTIONS: int = 2          # min swings clustering to call it an S/R level
    SR_TOLERANCE_PIPS: float = 30.0     # clustering tolerance for S/R levels
    SR_VOLUME_MA_PERIOD: int = 20       # volume MA period for breakout confirmation
    SR_VOLUME_FACTOR: float = 1.3       # breakout candle vol > 1.3 * MA20
    SR_SL_BUFFER_PIPS: float = 70.0     # 50–100 pip range from the doc
    SWING_RR_MIN: float = 2.5           # min RR for swing trades


cfg = Config()
