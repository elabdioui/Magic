"""
Script de test bout en bout : envoie un faux signal Tier S au backend.
Usage: python tests/send_mock_signal.py
"""
import hashlib
import hmac
import json
import sys
import os
from datetime import datetime, timezone

import httpx

BACKEND_URL = os.getenv("BACKEND_WEBHOOK_URL", "http://localhost:8000/signal")
SECRET = os.getenv("WEBHOOK_HMAC_SECRET", "test-secret-32chars-aaaaaaaaaaaa")

MOCK_SIGNAL = {
    "id": "mock-test-001",
    "timestamp": datetime.now(tz=timezone.utc).isoformat(),
    "symbol": "XAUUSD",
    "tier": "S",
    "direction": "LONG",
    "pattern": "Golden Setup",
    "killzone": "NY_AM",
    "entry_zone_low": 1850.50,
    "entry_zone_high": 1852.00,
    "stop_loss": 1845.00,
    "take_profit": 1870.00,
    "bias_h4": "BULLISH",
    "bias_h1": "BULLISH",
    "confluences": ["Bias_H4", "Bias_H1", "SSL_Sweep", "CHoCH_M5", "FVG_M5", "OTE_0.618"],
    "confluence_score": 9,
    "estimated_winrate": 0.72,
}

# Serialize once with sort_keys=True — same logic as detector/webhook.py
payload_bytes = json.dumps(MOCK_SIGNAL, default=str, sort_keys=True).encode()
sig = hmac.new(SECRET.encode(), payload_bytes, hashlib.sha256).hexdigest()

headers = {
    "Content-Type": "application/json",
    "X-HMAC-Signature": sig,
}

print(f"Sending mock Tier S LONG signal to {BACKEND_URL}…")
try:
    resp = httpx.post(BACKEND_URL, content=payload_bytes, headers=headers, timeout=15.0)
    print(f"Status: {resp.status_code}")
    print(f"Response: {resp.text}")
except httpx.RequestError as exc:
    print(f"Error: {exc}")
    sys.exit(1)
