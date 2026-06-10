"""
XAUUSD ICT Bot — Nœud 1 Détecteur (Windows MT5)
Boucle de scan toutes les N secondes, envoie les signaux au backend via webhook.
"""
import logging
import os
import sys
import time
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone

import pytz
from apscheduler.schedulers.blocking import BlockingScheduler

import mt5_client as mt5
from config import cfg
from strategy import (
    scan_golden_setup, scan_ob_retest, scan_london_sweep, scan_sfp_asia,
    scan_breaker_fib, scan_bos_fvg, scan_break_retest,
    is_in_killzone, minutes_to_next_killzone, get_active_killzone,
)
from webhook import send_signal

os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    level=cfg.LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        RotatingFileHandler(
            "logs/detector.log",
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5,
            encoding="utf-8",
        ),
    ],
)
log = logging.getLogger("detector.main")

_SCANNER_MAP = {
    "S": [
        lambda tf: scan_golden_setup(tf, "LONG"),
        lambda tf: scan_golden_setup(tf, "SHORT"),
    ],
    "A": [
        lambda tf: scan_ob_retest(tf, "LONG"),
        lambda tf: scan_ob_retest(tf, "SHORT"),
        lambda tf: scan_london_sweep(tf, "LONG"),
        lambda tf: scan_london_sweep(tf, "SHORT"),
        lambda tf: scan_sfp_asia(tf, "LONG"),
        lambda tf: scan_sfp_asia(tf, "SHORT"),
    ],
    "B": [
        lambda tf: scan_breaker_fib(tf, "LONG"),
        lambda tf: scan_breaker_fib(tf, "SHORT"),
        lambda tf: scan_bos_fvg(tf, "LONG"),
        lambda tf: scan_bos_fvg(tf, "SHORT"),
    ],
    "SWING": [
        lambda tf: scan_break_retest(tf, "LONG"),
        lambda tf: scan_break_retest(tf, "SHORT"),
    ],
}

_last_sent: dict[str, datetime] = {}
_COOLDOWN_BY_TIER = {
    "S": 300,        # 5 min
    "A": 300,        # 5 min
    "B": 300,        # 5 min
    "SWING": 14400,  # 4 h — un setup swing reste valide longtemps
}
_DEFAULT_COOLDOWN = 300


def _cooldown_key(signal: dict) -> str:
    return f"{signal['tier']}_{signal['direction']}_{signal['pattern']}"


def _is_cooling_down(signal: dict) -> bool:
    key = _cooldown_key(signal)
    last = _last_sent.get(key)
    if last is None:
        return False
    cooldown = _COOLDOWN_BY_TIER.get(signal.get("tier"), _DEFAULT_COOLDOWN)
    elapsed = (datetime.now(tz=timezone.utc) - last).total_seconds()
    return elapsed < cooldown
def scan_once() -> None:
    now_utc = datetime.now(tz=timezone.utc)

    if not is_in_killzone(now_utc):
        mins = minutes_to_next_killzone(now_utc)
        log.debug("Outside killzone — next in %d min", mins)
        return

    killzone = get_active_killzone(now_utc)
    log.info("Scan — killzone=%s time=%s", killzone, now_utc.strftime("%H:%M UTC"))

    if not mt5.is_connected():
        log.warning("MT5 disconnected — attempting reconnect")
        if not mt5.connect():
            log.error("Reconnect failed — skipping scan")
            return

    tf_data = mt5.get_all_timeframes(cfg.SYMBOL)
    if not tf_data or tf_data.get("M5") is None or tf_data["M5"].empty:
        log.warning("Could not fetch OHLC data")
        return

    found_any = False
    for tier in cfg.ENABLED_TIERS:
        scanners = _SCANNER_MAP.get(tier, [])
        for scanner in scanners:
            try:
                result = scanner(tf_data)
            except Exception as exc:
                log.exception("Scanner error (tier=%s): %s", tier, exc)
                continue

            if result is None:
                continue

            if _is_cooling_down(result):
                log.debug("Cooldown active for %s — skip", _cooldown_key(result))
                continue

            result["timestamp"] = now_utc.isoformat()
            result["symbol"] = cfg.SYMBOL

            log.info(
                "SIGNAL TIER %s %s %s | score=%d | entry=%.2f–%.2f | SL=%.2f TP=%.2f",
                result["tier"], result["direction"], result["pattern"],
                result["confluence_score"],
                result["entry_zone_low"], result["entry_zone_high"],
                result["stop_loss"], result["take_profit"],
            )

            ok = send_signal(result)
            if ok:
                _last_sent[_cooldown_key(result)] = now_utc
                found_any = True
                break  # one signal per scan per tier

    if not found_any:
        log.debug("No valid signal this scan")


def heartbeat() -> None:
    now_utc = datetime.now(tz=timezone.utc)
    kz = get_active_killzone(now_utc)
    mins = minutes_to_next_killzone(now_utc)
    log.info(
        "HEARTBEAT — alive | mt5_connected=%s | killzone=%s | next_kz_in=%dmin",
        mt5.is_connected(), kz, mins,
    )


def main() -> None:
    import os
    os.makedirs("logs", exist_ok=True)

    log.info("=== XAUUSD ICT Detector starting ===")
    log.info("Symbol=%s  Tiers=%s  Killzones=%s  Interval=%ds",
             cfg.SYMBOL, cfg.ENABLED_TIERS, cfg.ENABLED_KILLZONES, cfg.SCAN_INTERVAL_SECONDS)

    connected = False
    for i in range(1, cfg.MT5_INIT_RETRIES + 1):
        if mt5.connect():
            connected = True
            break
        log.warning("MT5 not ready — retry %d/%d in %ds",
                    i, cfg.MT5_INIT_RETRIES, cfg.MT5_INIT_RETRY_DELAY_SECONDS)
        time.sleep(cfg.MT5_INIT_RETRY_DELAY_SECONDS)

    if not connected:
        log.critical("Initial MT5 connection failed after %d retries — exiting",
                     cfg.MT5_INIT_RETRIES)
        sys.exit(1)

    scheduler = BlockingScheduler(timezone=pytz.utc)
    scheduler.add_job(
        scan_once,
        "interval",
        seconds=cfg.SCAN_INTERVAL_SECONDS,
        id="scan",
        next_run_time=datetime.now(tz=pytz.utc),
    )
    scheduler.add_job(heartbeat, "interval", minutes=cfg.HEARTBEAT_MINUTES, id="heartbeat")

    log.info("Scheduler started — scanning every %ds", cfg.SCAN_INTERVAL_SECONDS)
    try:
        scheduler.start()
    except KeyboardInterrupt:
        log.info("Detector stopped by user")
    finally:
        mt5.disconnect()


if __name__ == "__main__":
    main()
