from __future__ import annotations

from typing import Optional, Tuple

import time
from loguru import logger


def compute_remaining_minutes(
    first_ts: Optional[int],
    avg_minutes: Optional[int],
    now_ts: Optional[int] = None,
) -> Tuple[Optional[int], bool]:
    """Compute remaining minutes and whether the elapsed time was invalid/negative."""
    if avg_minutes is None:
        return (None, False)

    if now_ts is None:
        now_ts = int(time.time())

    if first_ts is None:
        return (avg_minutes, False)

    try:
        first_int = int(first_ts)
    except Exception:
        logger.warning("timer: invalid first_update value=%s", first_ts)
        return (None, False)

    elapsed_seconds = now_ts - first_int
    if elapsed_seconds < 0:
        logger.warning("timer: negative elapsed (first_ts=%s now_ts=%s)", first_ts, now_ts)
        return (None, True)

    elapsed_minutes = elapsed_seconds // 60
    remaining = avg_minutes - elapsed_minutes
    if remaining < 0:
        logger.info("timer: remaining time negative (elapsed=%s, avg=%s)", elapsed_minutes, avg_minutes)
        return (None, True)

    return (remaining, False)
