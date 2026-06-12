"""In-memory scan statistics — emit/skip counters per scanner, logged periodically."""
from collections import defaultdict
import logging

log = logging.getLogger(__name__)
_counters: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
_scan_count = 0


def record(scanner: str, outcome: str) -> None:
    """outcome: 'EMIT' or a short skip-reason string (e.g. 'no_sweep', 'rr_below_min')."""
    _counters[scanner][outcome] += 1


def tick(every: int = 120) -> None:
    """Call once per main-loop iteration; logs a one-line summary every `every` scans."""
    global _scan_count
    _scan_count += 1
    if _scan_count % every == 0:
        for scanner, outcomes in sorted(_counters.items()):
            summary = ", ".join(f"{k}={v}" for k, v in sorted(outcomes.items()))
            log.info("SCAN_STATS %s: %s", scanner, summary)
