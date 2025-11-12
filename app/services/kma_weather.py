from __future__ import annotations

import os
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Optional

import pytz
import requests
from loguru import logger

from app.database import get_db_connection

KST = pytz.timezone("Asia/Seoul")
PTY_MAP = {
    0: "없음",
    1: "비",
    2: "비/눈",
    3: "눈",
    4: "소나기",
}
SKY_MAP = {
    1: "맑음",
    3: "구름많음",
    4: "흐림",
}
CACHE_DURATION_SECONDS = 3600  # 1시간


def _safe_int(value: Optional[str]) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_float(value: Optional[str]) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _get_base_time(now: datetime) -> tuple[str, str]:
    """Return (base_date, base_time) for KMA forecast API.
    Base times: 0200, 0500, 0800, 1100, 1400, 1700, 2000, 2300 (3시간 간격)
    """
    from datetime import timedelta
    
    localized = now.astimezone(KST)
    hour = localized.hour
    
    # 가장 최근의 base_time 선택 (예보는 매 3시간마다 발표)
    if hour < 2:
        base_time = "2300"
        base_date = (localized - timedelta(days=1)).strftime("%Y%m%d")
    elif hour < 5:
        base_time = "0200"
        base_date = localized.strftime("%Y%m%d")
    elif hour < 8:
        base_time = "0500"
        base_date = localized.strftime("%Y%m%d")
    elif hour < 11:
        base_time = "0800"
        base_date = localized.strftime("%Y%m%d")
    elif hour < 14:
        base_time = "1100"
        base_date = localized.strftime("%Y%m%d")
    elif hour < 17:
        base_time = "1400"
        base_date = localized.strftime("%Y%m%d")
    elif hour < 20:
        base_time = "1700"
        base_date = localized.strftime("%Y%m%d")
    elif hour < 23:
        base_time = "2000"
        base_date = localized.strftime("%Y%m%d")
    else:
        base_time = "2300"
        base_date = localized.strftime("%Y%m%d")
    
    return base_date, base_time


def _fetch_from_cache(base_date: str, base_time: str, nx: int, ny: int, now_ts: int) -> Optional[dict]:
    """Check if valid cached weather data exists in DB."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT * FROM weather_cache
                WHERE base_date = %s AND base_time = %s AND nx = %s AND ny = %s
                ORDER BY fetched_at DESC
                LIMIT 1
                """,
                (base_date, base_time, nx, ny),
            )
            row = cursor.fetchone()
            
            if row and (now_ts - row.get("fetched_at", 0)) < CACHE_DURATION_SECONDS:
                logger.info(f"Weather cache hit: {base_date} {base_time}")
                return row
            
            return None
    except Exception as exc:
        logger.warning(f"Weather cache read failed: {exc}")
        return None


def _parse_xml_forecast(xml_text: str) -> Optional[dict[str, str]]:
    """Parse KMA XML response and extract first forecast item's categories."""
    try:
        root = ET.fromstring(xml_text)
        items = root.findall(".//item")
        
        if not items:
            logger.warning("No items found in XML response")
            return None
        
        # 각 카테고리별로 첫 번째 예보 시간 값 추출
        categories: dict[str, str] = {}
        for item in items:
            cat = item.findtext("category")
            val = item.findtext("fcstValue")
            if cat and val and cat not in categories:
                categories[cat] = val
        
        return categories
    except ET.ParseError as exc:
        logger.error(f"XML parsing failed: {exc}")
        return None


def _store_to_cache(base_date: str, base_time: str, nx: int, ny: int, categories: dict[str, str], now_ts: int) -> None:
    """Store parsed weather data to DB cache (all fields)."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO weather_cache
                (base_date, base_time, nx, ny, fetched_at, tmp, tmn, tmx, pop, pty, pcp, sno,
                 sky, vec, wsd, uuu, vvv, reh, wav)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    fetched_at = VALUES(fetched_at),
                    tmp = VALUES(tmp),
                    tmn = VALUES(tmn),
                    tmx = VALUES(tmx),
                    pop = VALUES(pop),
                    pty = VALUES(pty),
                    pcp = VALUES(pcp),
                    sno = VALUES(sno),
                    sky = VALUES(sky),
                    vec = VALUES(vec),
                    wsd = VALUES(wsd),
                    uuu = VALUES(uuu),
                    vvv = VALUES(vvv),
                    reh = VALUES(reh),
                    wav = VALUES(wav)
                """,
                (
                    base_date,
                    base_time,
                    nx,
                    ny,
                    now_ts,
                    _safe_float(categories.get("TMP")),
                    _safe_float(categories.get("TMN")),
                    _safe_float(categories.get("TMX")),
                    _safe_int(categories.get("POP")),
                    _safe_int(categories.get("PTY")),
                    categories.get("PCP"),
                    categories.get("SNO"),
                    _safe_int(categories.get("SKY")),
                    _safe_int(categories.get("VEC")),
                    _safe_float(categories.get("WSD")),
                    _safe_float(categories.get("UUU")),
                    _safe_float(categories.get("VVV")),
                    _safe_int(categories.get("REH")),
                    _safe_float(categories.get("WAV")),
                ),
            )
            conn.commit()
            logger.info(f"Weather cache stored: {base_date} {base_time}")
    except Exception as exc:
        logger.error(f"Weather cache store failed: {exc}")


def _format_weather_context(data: dict) -> dict:
    """Convert DB row to extended weather dict with all fields."""
    pty_val = data.get("pty")
    sky_val = data.get("sky")
    
    return {
        "base_time": f"{data.get('base_date')}T{data.get('base_time')}00+0900",
        "forecast_time": datetime.now(tz=KST).isoformat(),
        # 기온
        "temperature": float(data.get("tmp")) if data.get("tmp") is not None else None,
        "min_temperature": float(data.get("tmn")) if data.get("tmn") is not None else None,
        "max_temperature": float(data.get("tmx")) if data.get("tmx") is not None else None,
        # 강수
        "precipitation_probability": int(data.get("pop")) if data.get("pop") is not None else None,
        "precipitation_type": PTY_MAP.get(pty_val) if pty_val is not None else None,
        "precipitation_type_code": pty_val,
        "precipitation_amount": data.get("pcp"),
        "snow_amount": data.get("sno"),
        # 하늘
        "sky_condition": SKY_MAP.get(sky_val) if sky_val is not None else None,
        "sky_condition_code": sky_val,
        # 바람
        "wind_direction": int(data.get("vec")) if data.get("vec") is not None else None,
        "wind_speed": float(data.get("wsd")) if data.get("wsd") is not None else None,
        "wind_ew": float(data.get("uuu")) if data.get("uuu") is not None else None,
        "wind_ns": float(data.get("vvv")) if data.get("vvv") is not None else None,
        # 기타
        "humidity": int(data.get("reh")) if data.get("reh") is not None else None,
        "wave_height": float(data.get("wav")) if data.get("wav") is not None else None,
        # Legacy fields for backward compatibility
        "rainfall_last_hour": None,
    }


def fetch_kma_weather(now: Optional[datetime] = None) -> Optional[dict[str, Optional[float | str]]]:
    """Fetch KMA short-term forecast with 1-hour DB caching."""
    if now is None:
        now = datetime.now(tz=KST)
    
    auth_key = os.getenv("KMA_AUTH_KEY")
    nx_str = os.getenv("KMA_NX")
    ny_str = os.getenv("KMA_NY")
    
    if not auth_key or not nx_str or not ny_str:
        logger.debug("KMA weather skipped: missing credentials or grid coordinates")
        return None
    
    nx = int(nx_str)
    ny = int(ny_str)
    base_date, base_time = _get_base_time(now)
    now_ts = int(time.time())
    
    # 1. Check cache
    cached = _fetch_from_cache(base_date, base_time, nx, ny, now_ts)
    if cached:
        return _format_weather_context(cached)
    
    # 2. Fetch from API
    url = "https://apihub.kma.go.kr/api/typ02/openApi/VilageFcstInfoService_2.0/getVilageFcst"
    params = {
        "pageNo": 1,
        "numOfRows": 1000,
        "dataType": "XML",
        "base_date": base_date,
        "base_time": base_time,
        "nx": nx,
        "ny": ny,
        "authKey": auth_key,
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        xml_text = response.text
    except Exception as exc:
        logger.warning(f"KMA API request failed: {exc}")
        return None
    
    # 3. Parse XML
    categories = _parse_xml_forecast(xml_text)
    if not categories:
        return None
    
    # 4. Store to cache
    _store_to_cache(base_date, base_time, nx, ny, categories, now_ts)
    
    # 5. Format and return (all fields)
    return _format_weather_context({
        "base_date": base_date,
        "base_time": base_time,
        "tmp": _safe_float(categories.get("TMP")),
        "tmn": _safe_float(categories.get("TMN")),
        "tmx": _safe_float(categories.get("TMX")),
        "pop": _safe_int(categories.get("POP")),
        "pty": _safe_int(categories.get("PTY")),
        "pcp": categories.get("PCP"),
        "sno": categories.get("SNO"),
        "sky": _safe_int(categories.get("SKY")),
        "vec": _safe_int(categories.get("VEC")),
        "wsd": _safe_float(categories.get("WSD")),
        "uuu": _safe_float(categories.get("UUU")),
        "vvv": _safe_float(categories.get("VVV")),
        "reh": _safe_int(categories.get("REH")),
        "wav": _safe_float(categories.get("WAV")),
    })
