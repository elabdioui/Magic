"""APScheduler job: refresh news cache every N minutes."""
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from services.news.aggregator import refresh_news
from core.config import settings

log = logging.getLogger(__name__)


def start_news_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    # next_run_time omitted — APScheduler fires after the first interval.
    # The initial refresh is handled by backend/main.py lifespan on startup.
    scheduler.add_job(
        refresh_news,
        "interval",
        minutes=settings.NEWS_REFRESH_MINUTES,
        id="news_refresh",
    )
    scheduler.start()
    log.info("News scheduler started — refresh every %dmin", settings.NEWS_REFRESH_MINUTES)
    return scheduler
