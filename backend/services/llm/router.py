"""LLM router: Groq primary → degraded (no verdict) if all fails."""
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

from .groq import call_groq
from .prompts import SYSTEM_PROMPT, build_user_prompt
from core.config import settings

log = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=2)


def _call_with_timeout(fn, *args) -> dict | None:
    future = _executor.submit(fn, *args)
    try:
        return future.result(timeout=settings.LLM_TIMEOUT_SECONDS)
    except FuturesTimeout:
        log.warning("LLM call timed out after %ds", settings.LLM_TIMEOUT_SECONDS)
        return None
    except Exception as exc:
        log.error("LLM executor error: %s", exc)
        return None


def get_verdict(signal: dict, news_context: dict) -> tuple[dict | None, str]:
    """
    Returns (verdict_dict, provider_name).
    verdict_dict is None if Groq fails (both primary and fallback models).
    """
    user_prompt = build_user_prompt(signal, news_context)
    result = _call_with_timeout(call_groq, SYSTEM_PROMPT, user_prompt)
    if result:
        return result, "groq"

    log.error("Groq LLM failed — returning degraded verdict")
    return None, "none"
