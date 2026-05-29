"""Groq Llama — primary LLM client with two-model fallback."""
import json
import logging

from groq import Groq

from core.config import settings

log = logging.getLogger(__name__)
_groq_client: Groq | None = None

# Primary model — high quality, ~30 RPM free tier
_PRIMARY_MODEL = "llama-3.3-70b-versatile"
# Secondary model — lighter, ~14 400 req/day free tier
_FALLBACK_MODEL = "llama-3.1-8b-instant"


def _get_client() -> Groq:
    global _groq_client
    if _groq_client is None:
        _groq_client = Groq(api_key=settings.GROQ_API_KEY)
    return _groq_client


def _call_model(model: str, system_prompt: str, user_prompt: str) -> dict | None:
    client = _get_client()
    completion = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
        max_tokens=256,
        response_format={"type": "json_object"},
    )
    text = completion.choices[0].message.content or ""
    return json.loads(text)


def call_groq(system_prompt: str, user_prompt: str) -> dict | None:
    """Returns parsed JSON dict from Groq, or None on failure. Tries primary then fallback model."""
    if not settings.GROQ_API_KEY:
        log.warning("GROQ_API_KEY not set")
        return None

    try:
        return _call_model(_PRIMARY_MODEL, system_prompt, user_prompt)
    except json.JSONDecodeError as exc:
        log.warning("Groq JSON parse error (%s): %s", _PRIMARY_MODEL, exc)
    except Exception as exc:
        log.warning("Groq primary model failed (%s): %s — trying fallback", _PRIMARY_MODEL, exc)

    try:
        result = _call_model(_FALLBACK_MODEL, system_prompt, user_prompt)
        log.info("Groq fallback model succeeded (%s)", _FALLBACK_MODEL)
        return result
    except json.JSONDecodeError as exc:
        log.warning("Groq JSON parse error (%s): %s", _FALLBACK_MODEL, exc)
        return None
    except Exception as exc:
        log.error("Groq fallback model failed (%s): %s", _FALLBACK_MODEL, exc)
        return None
