from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Optional

import pytz
import requests
from loguru import logger

KST = pytz.timezone("Asia/Seoul")
PTY_MAP = {
    "0": "NONE",
    "1": "RAIN",
    "2": "RAIN_SNOW",
    "3": "SNOW",
    "4": "SHOWER",
    "5": "DRIZZLE",
    "6": "RAIN_SNOW",
    "7": "SNOW",
}


def _compute_base_datetime(now: datetime) -> datetime:
    """Return the base datetime used for KMA ultra-short-term APIs."""
    localized = now.astimezone(KST)
    # Ultra short-term data is published every 10 minutes; subtract 40 minutes for safety
    adjusted = localized - timedelta(minutes=40)
    return adjusted.replace(minute=(adjusted.minute // 10) * 10, second=0, microsecond=0)


def _safe_float(value: Optional[str]) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_kma_weather(now: Optional[datetime] = None) -> Optional[dict[str, Optional[float | str]]]:
    """Fetch latest weather snapshot from KMA ultra-short-term nowcast API."""
    if now is None:
        now = datetime.now(tz=KST)

    service_key = os.getenv("KMA_SERVICE_KEY")
    nx = os.getenv("KMA_NX")
    ny = os.getenv("KMA_NY")

    if not service_key or not nx or not ny:
        logger.debug("KMA weather skipped: missing credentials or grid coordinates")
        return None

    base_dt = _compute_base_datetime(now)
    params = {
        "serviceKey": service_key,
        "pageNo": 1,
        "numOfRows": 200,
        "dataType": "JSON",
        "base_date": base_dt.strftime("%Y%m%d"),
        "base_time": base_dt.strftime("%H%M"),
        "nx": nx,
        "ny": ny,
    }

    url = "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getUltraSrtNcst"

    try:
        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        logger.warning("KMA weather request failed: {}", exc)
        return None

    try:
        items = data["response"]["body"]["items"]["item"]
    except (KeyError, TypeError):
        logger.warning("KMA weather response missing items: {}", data)
        return None

    categories: dict[str, str] = {}
    for item in items:
        cat = item.get("category")
        val = item.get("obsrValue")
        if cat:
            categories[cat] = val

    precipitation_type = PTY_MAP.get(str(categories.get("PTY"))) if categories.get("PTY") is not None else None

    return {
        "base_time": base_dt.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "forecast_time": now.astimezone(KST).strftime("%Y-%m-%dT%H:%M:%S%z"),
        "precipitation_probability": None,  # Not provided by ultra-short-term nowcast
        "precipitation_type": precipitation_type,
        "rainfall_last_hour": _safe_float(categories.get("RN1")),
        "temperature": _safe_float(categories.get("T1H")),
        "humidity": _safe_float(categories.get("REH")),
    }
