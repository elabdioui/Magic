"""Forex Factory calendar scraper — returns upcoming high-impact US events."""
import logging
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from typing import Literal

from curl_cffi import requests as curl_requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

ImpactLevel = Literal["red", "orange", "yellow", "gray"]


@dataclass
class NewsEvent:
    time_utc: datetime
    currency: str
    impact: ImpactLevel
    title: str
    actual: str = ""
    forecast: str = ""
    previous: str = ""

    @property
    def minutes_from_now(self) -> float:
        now = datetime.now(tz=timezone.utc)
        return (self.time_utc - now).total_seconds() / 60

    @property
    def is_us_red(self) -> bool:
        return self.currency == "USD" and self.impact == "red"

    @property
    def is_us_orange(self) -> bool:
        return self.currency == "USD" and self.impact == "orange"


_IMPACT_MAP = {
    "ff-impact--red": "red",
    "ff-impact--ora": "orange",
    "ff-impact--yel": "yellow",
    "ff-impact--gra": "gray",
}


def fetch_calendar() -> list[NewsEvent]:
    """Scrape Forex Factory calendar for today's events."""
    try:
        resp = curl_requests.get(
            "https://www.forexfactory.com/calendar",
            impersonate="chrome124",
            timeout=15,
        )
        if not resp.ok:
            log.warning("FF returned %d", resp.status_code)
            return []
        return _parse_calendar(resp.text)
    except Exception as exc:
        log.error("FF fetch failed: %s", exc)
        return []


def _parse_calendar(html: str) -> list[NewsEvent]:
    soup = BeautifulSoup(html, "lxml")
    rows = soup.select("tr.calendar__row")
    events: list[NewsEvent] = []
    current_date = datetime.now(tz=timezone.utc).date()
    last_time: datetime | None = None

    for row in rows:
        # Date cell (not always present)
        date_cell = row.select_one("td.calendar__date")
        if date_cell and date_cell.text.strip():
            try:
                parsed = datetime.strptime(date_cell.text.strip(), "%a%b %d")
                current_date = parsed.replace(year=datetime.now().year).date()
            except ValueError:
                pass

        # Time cell
        time_cell = row.select_one("td.calendar__time")
        time_str = time_cell.text.strip() if time_cell else ""
        if time_str and time_str not in ("All Day", ""):
            try:
                t = datetime.strptime(time_str, "%I:%M%p")
                last_time = datetime(
                    current_date.year, current_date.month, current_date.day,
                    t.hour, t.minute, tzinfo=timezone.utc,
                )
            except ValueError:
                pass

        if last_time is None:
            continue

        # Currency
        currency_cell = row.select_one("td.calendar__currency")
        currency = currency_cell.text.strip() if currency_cell else ""

        # Impact
        impact_cell = row.select_one("td.calendar__impact span")
        impact: ImpactLevel = "gray"
        if impact_cell:
            for cls, val in _IMPACT_MAP.items():
                if cls in " ".join(impact_cell.get("class", [])):
                    impact = val  # type: ignore[assignment]
                    break

        # Event title
        title_cell = row.select_one("td.calendar__event span.calendar__event-title")
        title = title_cell.text.strip() if title_cell else ""

        if not title or not currency:
            continue

        events.append(NewsEvent(
            time_utc=last_time,
            currency=currency,
            impact=impact,
            title=title,
        ))

    return events


def get_upcoming_us_events(
    events: list[NewsEvent],
    window_minutes: int = 60,
) -> list[NewsEvent]:
    """Return US events within the next window_minutes."""
    return [
        e for e in events
        if e.currency == "USD" and 0 <= e.minutes_from_now <= window_minutes
    ]


def is_red_news_imminent(events: list[NewsEvent], window_minutes: int = 15) -> bool:
    return any(e.is_us_red and 0 <= e.minutes_from_now <= window_minutes for e in events)


def is_orange_news_imminent(events: list[NewsEvent], window_minutes: int = 5) -> bool:
    return any(e.is_us_orange and 0 <= e.minutes_from_now <= window_minutes for e in events)
