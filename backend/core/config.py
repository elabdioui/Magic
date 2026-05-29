import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from root (VPS mono-machine) then fall back to local backend/.env
_root_env = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(dotenv_path=_root_env if _root_env.exists() else None)


class Settings:
    WEBHOOK_HMAC_SECRET: str = os.getenv("WEBHOOK_HMAC_SECRET", "")

    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    LLM_TIMEOUT_SECONDS: int = int(os.getenv("LLM_TIMEOUT_SECONDS", "5"))

    BLOCK_ORANGE_NEWS: bool = os.getenv("BLOCK_ORANGE_NEWS", "false").lower() == "true"
    NEWS_ORANGE_BLOCK_WINDOW_MIN: int = int(os.getenv("NEWS_ORANGE_BLOCK_WINDOW_MIN", "5"))

    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

    FOREX_FACTORY_URL: str = os.getenv(
        "FOREX_FACTORY_URL", "https://www.forexfactory.com/calendar"
    )
    NEWS_REFRESH_MINUTES: int = int(os.getenv("NEWS_REFRESH_MINUTES", "5"))
    NEWS_RED_BLOCK_WINDOW_MIN: int = int(os.getenv("NEWS_RED_BLOCK_WINDOW_MIN", "15"))

    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./alerts.db")

    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    PORT: int = int(os.getenv("PORT", "8000"))
    API_SECRET_TOKEN: str = os.getenv("API_SECRET_TOKEN", "")


settings = Settings()
