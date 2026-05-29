"""POST /signal — receives signed webhooks from the detector."""
import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from core.security import require_hmac
from db.database import get_session
from models.alert import Alert
from services.news.aggregator import get_news_context, is_red_news_kill_switch, is_orange_news_kill_switch
from services.llm.router import get_verdict
from services.telegram.client import send_message
from services.telegram.formatter import format_alert, format_no_go_news

log = logging.getLogger(__name__)
router = APIRouter()


@router.post("/signal", status_code=202)
async def receive_signal(
    body: bytes = Depends(require_hmac),
    session: Session = Depends(get_session),
):
    try:
        signal = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    log.info(
        "Signal received — tier=%s dir=%s pattern=%s score=%s",
        signal.get("tier"), signal.get("direction"),
        signal.get("pattern"), signal.get("confluence_score"),
    )

    # Hard kill-switch: red news imminent
    if is_red_news_kill_switch():
        log.warning("RED NEWS KILL SWITCH — signal rejected")
        alert = _build_alert(signal, {}, "NO_GO", "Kill-switch news rouge", "", "", "none")
        session.add(alert)
        session.commit()
        blocked_msg = format_no_go_news(signal, "News rouge dans ≤15min")
        send_message(blocked_msg)
        return {"status": "blocked", "reason": "red_news_kill_switch"}

    # Optional kill-switch: orange news (activated by BLOCK_ORANGE_NEWS=true)
    if is_orange_news_kill_switch():
        log.warning("ORANGE NEWS KILL SWITCH — signal rejected")
        alert = _build_alert(signal, {}, "NO_GO", "Kill-switch news orange", "", "", "none")
        session.add(alert)
        session.commit()
        blocked_msg = format_no_go_news(signal, "News orange USD dans ≤5min")
        send_message(blocked_msg)
        return {"status": "blocked", "reason": "orange_news_kill_switch"}

    # Enrich with news context
    news_context = get_news_context(window_minutes=60)

    # LLM verdict
    verdict, provider = get_verdict(signal, news_context)

    # Format and send Telegram
    text = format_alert(signal, verdict, provider)
    msg_id = send_message(text)

    # Persist
    verdict_str = verdict.get("verdict", "") if verdict else ""
    reasoning = verdict.get("reason_short", "") if verdict else ""
    risk = verdict.get("risk_main", "") if verdict else ""
    action = verdict.get("action", "") if verdict else ""

    alert = _build_alert(
        signal, news_context,
        verdict_str, reasoning, risk, action, provider,
        telegram_sent=msg_id is not None,
        telegram_message_id=msg_id,
    )
    session.add(alert)
    session.commit()

    log.info("Alert #%d saved — verdict=%s provider=%s tg_sent=%s",
             alert.id, verdict_str, provider, msg_id is not None)

    return {
        "status": "ok",
        "alert_id": alert.id,
        "verdict": verdict_str,
        "provider": provider,
        "telegram_sent": msg_id is not None,
    }


def _build_alert(
    signal: dict,
    news_context: dict,
    verdict_str: str,
    reasoning: str,
    risk: str,
    action: str,
    provider: str,
    telegram_sent: bool = False,
    telegram_message_id: int | None = None,
    error: str | None = None,
) -> Alert:
    return Alert(
        signal_id=signal.get("id", str(uuid.uuid4())),
        received_at=datetime.now(tz=timezone.utc),
        symbol=signal.get("symbol", "XAUUSD"),
        tier=signal.get("tier", "?"),
        direction=signal.get("direction", "?"),
        pattern=signal.get("pattern", "?"),
        killzone=signal.get("killzone", "?"),
        entry_zone_low=signal.get("entry_zone_low", 0.0),
        entry_zone_high=signal.get("entry_zone_high", 0.0),
        stop_loss=signal.get("stop_loss", 0.0),
        take_profit=signal.get("take_profit", 0.0),
        confluence_score=signal.get("confluence_score", 0),
        signal_json=json.dumps(signal, default=str),
        news_context=json.dumps(news_context, default=str),
        llm_verdict=verdict_str,
        llm_reasoning=reasoning,
        llm_risk=risk,
        llm_action=action,
        llm_provider=provider,
        telegram_sent=telegram_sent,
        telegram_message_id=telegram_message_id,
        error=error,
    )
