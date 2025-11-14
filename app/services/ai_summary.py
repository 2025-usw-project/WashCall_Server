from __future__ import annotations

import asyncio
import os
import random
import time
from datetime import datetime
from typing import Optional

import holidays
import pytz
import requests
from google import genai
from google.genai import types
from loguru import logger
from openai import OpenAI

from app.database import get_db_connection
from app.services.kma_weather import get_kma_weather_from_cache_only

CACHE_DURATION_SECONDS = 60  # 1분
KST = pytz.timezone("Asia/Seoul")
AI_REFRESH_LOCK = asyncio.Lock()


def _build_prompt(status_context: dict) -> str:
    """Build AI prompt from status context data."""
    prompt_parts = [
        "당신은 대학 기숙사 세탁실 이용 시간을 추천하는 AI입니다.",
        "다음 정보를 바탕으로 **언제 세탁하면 좋을지** **무조건 한 줄**로 추천해주세요.",
        "현재 상황을 간단히 언급하고, 혼잡도 통계를 분석하여 가장 한산한 시간대(요일+시간)를 추천하세요.",
        "자연스럽고 친근한 말투로 작성하되, 미래 예측 형태로 작성해주세요.",
        "",
        "# 현재 세탁실 상황",
    ]

    # Time context
    time_ctx = status_context.get("time", {})
    if time_ctx:
        weekday = time_ctx.get("weekday", "")
        hour = time_ctx.get("hour", 0)
        period = "오전" if hour < 12 else "오후"
        hour_12 = hour if hour <= 12 else hour - 12
        if hour_12 == 0:
            hour_12 = 12
        prompt_parts.append(f"- 현재 시간: {weekday}요일 {period} {hour_12}시")
        if time_ctx.get("is_holiday"):
            prompt_parts.append("- 오늘은 공휴일입니다")

    # Weather context (전체 정보)
    weather = status_context.get("weather")
    if weather:
        weather_lines = ["- 날씨 상세:"]
        
        # 기온
        temp = weather.get("temperature")
        if temp is not None:
            weather_lines.append(f"  * 현재 기온: {temp}°C")
        min_temp = weather.get("min_temperature")
        max_temp = weather.get("max_temperature")
        if min_temp is not None or max_temp is not None:
            temp_range = []
            if min_temp is not None:
                temp_range.append(f"최저 {min_temp}°C")
            if max_temp is not None:
                temp_range.append(f"최고 {max_temp}°C")
            weather_lines.append(f"  * 예상 기온: {', '.join(temp_range)}")
        
        # 강수
        pop = weather.get("precipitation_probability")
        if pop is not None:
            weather_lines.append(f"  * 강수확률: {pop}%")
        pty = weather.get("precipitation_type")
        if pty and pty != "없음":
            weather_lines.append(f"  * 강수형태: {pty}")
        pcp = weather.get("precipitation_amount")
        if pcp and pcp != "강수없음":
            weather_lines.append(f"  * 강수량: {pcp}")
        sno = weather.get("snow_amount")
        if sno and sno != "적설없음":
            weather_lines.append(f"  * 적설량: {sno}")
        
        # 하늘 상태
        sky = weather.get("sky_condition")
        if sky:
            weather_lines.append(f"  * 하늘: {sky}")
        
        # 바람
        wind_speed = weather.get("wind_speed")
        wind_dir = weather.get("wind_direction")
        if wind_speed is not None:
            wind_info = f"풍속 {wind_speed}m/s"
            if wind_dir is not None:
                wind_info += f", 풍향 {wind_dir}°"
            weather_lines.append(f"  * 바람: {wind_info}")
        
        # 습도
        humidity = weather.get("humidity")
        if humidity is not None:
            weather_lines.append(f"  * 습도: {humidity}%")
        
        if len(weather_lines) > 1:
            prompt_parts.extend(weather_lines)

    # Room summaries
    rooms = status_context.get("rooms", [])
    if rooms:
        prompt_parts.append("- 세탁실별 현황:")
        for room in rooms:
            room_name = room.get("room_name")
            available = room.get("machines_idle", 0)
            total = room.get("machines_total", 0)
            busy = room.get("machines_busy", 0)
            estimated_wait = room.get("estimated_wait_minutes")
            
            room_info = f"  * {room_name}: 사용 가능 {available}/{total}대"
            if busy > 0:
                room_info += f", 사용 중 {busy}대"
            if estimated_wait and estimated_wait > 0:
                room_info += f", 예상 대기 {int(estimated_wait)}분"
            prompt_parts.append(room_info)

    # Totals
    totals = status_context.get("totals", {})
    if totals:
        prompt_parts.append(f"- 전체: 사용 가능 {totals.get('machines_idle', 0)}대 / 총 {totals.get('machines_total', 0)}대")
        
        # Active reservations
        active_res = totals.get("reservations_total", 0)
        if active_res > 0:
            prompt_parts.append(f"- 활성 예약: {active_res}건")

    # Recent alerts
    alerts = status_context.get("alerts", {})
    recent_finished = alerts.get("recent_finished_count", 0)
    if recent_finished > 0:
        prompt_parts.append(f"- 최근 완료: {recent_finished}건")

    # Congestion statistics (요일별/시간별 혼잡도 - 전체 시간대)
    congestion = status_context.get("congestion_stats")
    if congestion:
        prompt_parts.append("- 혼잡도 통계 (요일별/시간별 평균 사용 대수, 전체 시간대):")
        for day, hours in congestion.items():
            if isinstance(hours, list) and len(hours) == 24:
                hour_str = ", ".join([f"{i}시:{hours[i]}대" for i in range(24)])
                prompt_parts.append(f"  * {day}: {hour_str}")

    prompt_parts.append("")
    prompt_parts.append(
        "위 정보를 바탕으로 **언제 세탁하면 좋을지** 한 줄로 추천해주세요. "
        "혼잡도 통계를 분석하여 가장 한산한 시간대(요일과 시간)를 찾고, "
        "'Y요일 Z시가 가장 한산할 것 같아요!' 또는 "
        "'지금보다 오늘 저녁 8시가 더 쾌적할 것 같아요!' 같은 식으로 **미래 시간대를 추천**해주세요. "
        "친근한 말투와 이모지를 적절히 사용하면 좋습니다."
    )

    return "\n".join(prompt_parts)


def _call_google_gemini(prompt: str, model: str, api_key: str, count: int = 5) -> list[str]:
    """Call Google Gemini API for multiple text generation responses.
    
    Args:
        prompt: Input prompt
        model: Model name
        api_key: API key
        count: Number of responses to generate (default: 5)
    
    Returns:
        List of generated responses
    """
    try:
        client = genai.Client(api_key=api_key)
        
        # System instruction for time recommendation
        system_instruction = (
            "당신은 대학 기숙사 세탁실 이용 시간을 추천하는 AI입니다. "
            "반드시 한 줄로만 추천하며, 자연스럽고 친근한 말투를 사용합니다. "
            "혼잡도 통계를 분석하여 가장 한산한 미래 시간대(요일+시간)를 추천하세요. "
            "'내일 금요일 저녁 8시가 한산할 것 같아요!' 또는 '오늘 밤 10시 이후가 쾌적할 거예요!' 같은 식으로 "
            "**미래 예측** 형태로 추천해주세요. 이모지를 적절히 활용하세요."
        )
        
        # Configure with multiple candidates
        config = types.GenerateContentConfig(
            candidate_count=count,
            system_instruction=system_instruction,
        )
        
        # Disable thinking for Gemini 2.5 Flash
        if "2.5" in model.lower() and "flash" in model.lower():
            config.thinking_config = types.ThinkingConfig(thinking_budget=0)
        
        logger.debug(f"[Gemini] Sending prompt to {model} (requesting {count} responses)")
        
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=config,
        )
        
        # Extract all candidate responses
        results = []
        if hasattr(response, 'candidates') and response.candidates:
            for candidate in response.candidates:
                if hasattr(candidate, 'content') and candidate.content:
                    if hasattr(candidate.content, 'parts') and candidate.content.parts:
                        for part in candidate.content.parts:
                            if hasattr(part, 'text') and part.text:
                                text = part.text.strip()
                                if text:
                                    results.append(text)
                                    logger.debug(f"[Gemini] Response {len(results)}: {text}")
        
        if not results:
            # Fallback to single response.text
            result = response.text.strip()
            if result:
                results.append(result)
                logger.debug(f"[Gemini] Fallback response: {result}")
        
        logger.debug(f"[Gemini] Total responses received: {len(results)}")
        return results
    except Exception as exc:
        logger.error(f"Google Gemini API call failed: {exc}")
        return []


def _call_openrouter_chat(
    prompt: str,
    model: str,
    api_key: str,
    base_url: str,
    count: int = 5,
) -> list[str]:
    """Call OpenRouter (OpenAI-compatible) chat completion API for multiple tips.

    Args:
        prompt: Input prompt string (already contains detailed context).
        model: OpenRouter model name (e.g. "openai/gpt-oss-120b").
        api_key: OpenRouter API key.
        base_url: OpenRouter base URL (default: https://openrouter.ai/api/v1).
        count: Number of candidate responses to request.

    Returns:
        List of generated one-line tips.
    """
    try:
        client = OpenAI(
            base_url=base_url,
            api_key=api_key,
        )

        system_instruction = (
            "당신은 대학 기숙사 세탁실 이용 시간을 추천하는 AI입니다. "
            "반드시 한 줄로만 추천하며, 자연스럽고 친근한 말투를 사용합니다. "
            "혼잡도 통계를 분석하여 가장 한산한 미래 시간대(요일+시간)를 추천하세요. "
            "'내일 금요일 저녁 8시가 한산할 것 같아요!' 또는 '오늘 밤 10시 이후가 쾌적할 거예요!' 같은 식으로 "
            "미래 예측 형태로 추천해주세요. 이모지를 적절히 활용하세요."
        )

        logger.debug(f"[OpenRouter] Sending prompt to {model} (requesting {count} responses)")

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt},
            ],
            n=count,
            # Enable reasoning if the model supports it (OpenRouter extension)
            extra_body={"reasoning": {"enabled": True}},
        )

        results: list[str] = []
        if hasattr(response, "choices") and response.choices:
            for idx, choice in enumerate(response.choices, start=1):
                # In openai>=1.x chat.completions, message.content is usually a string
                text = (getattr(choice, "message", None).content or "") if getattr(choice, "message", None) else ""
                text = text.strip()
                if text:
                    results.append(text)
                    logger.debug(f"[OpenRouter] Response {idx}: {text}")

        logger.debug(f"[OpenRouter] Total responses received: {len(results)}")
        return results
    except Exception as exc:
        logger.error(f"OpenRouter API call failed: {exc}")
        return []


def _call_ollama(prompt: str, model: str, base_url: str) -> Optional[str]:
    """Call Ollama API for text generation."""
    url = f"{base_url.rstrip('/')}/api/generate"
    
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.7,
            "num_predict": 200,
        }
    }
    
    try:
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        generated_text = data.get("response", "").strip()
        if generated_text:
            return generated_text
        
        logger.warning(f"Ollama response missing 'response' field: {data}")
        return None
    except Exception as exc:
        logger.error(f"Ollama API call failed: {exc}")
        return None


def _fetch_cached_tip() -> Optional[str]:
    """Fetch a random cached tip if available and not expired."""
    try:
        now_ts = int(time.time())
        with get_db_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT tip_message FROM ai_tip_cache WHERE fetched_at >= %s",
                (now_ts - CACHE_DURATION_SECONDS,)
            )
            rows = cursor.fetchall() or []
            
            if rows:
                # Return random tip from cache
                selected = random.choice(rows)
                tip = selected["tip_message"]
                logger.debug(f"[Cache] Returning cached tip: {tip}")
                return tip
            
            return None
    except Exception as exc:
        logger.warning(f"Cache fetch failed: {exc}")
        return None


def get_tip_from_cache_no_ttl() -> Optional[str]:
    """Fetch a random cached tip from DB without TTL filtering.

    Used by the /tip endpoint so that user requests never trigger new AI calls
    as long as there is at least one cached tip available.
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT tip_message FROM ai_tip_cache")
            rows = cursor.fetchall() or []

            if not rows:
                return None

            selected = random.choice(rows)
            tip = selected.get("tip_message")
            if tip:
                logger.debug(f"[Cache] Returning cached tip (no TTL): {tip}")
            return tip
    except Exception as exc:
        logger.warning(f"Cache (no TTL) fetch failed: {exc}")
        return None


def _store_tips_to_cache(tips: list[str]) -> None:
    """Store multiple tips to cache, clearing old ones."""
    try:
        now_ts = int(time.time())
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Clear old cache
            cursor.execute("DELETE FROM ai_tip_cache")
            
            # Insert new tips
            for tip in tips:
                cursor.execute(
                    "INSERT INTO ai_tip_cache (tip_message, fetched_at) VALUES (%s, %s)",
                    (tip, now_ts)
                )
            
            conn.commit()
            logger.debug(f"[Cache] Stored {len(tips)} tips to cache")
    except Exception as exc:
        logger.error(f"Cache store failed: {exc}")


def generate_summary(status_context: dict) -> Optional[str]:
    """Generate one-line summary of laundry room status using configured AI provider.
    
    Uses 10-minute cache: returns random cached tip if available, otherwise generates 5+ new tips.
    
    Args:
        status_context: Dict containing time, weather, rooms, totals, alerts, etc.
    
    Returns:
        Generated summary string or None if generation fails.
    """
    # Try cache first
    cached = _fetch_cached_tip()
    if cached:
        return cached
    
    logger.info("[Cache] Cache expired or empty, generating new tips")
    
    provider = os.getenv("AI_PROVIDER", "openrouter").lower()
    
    if provider not in {"google", "ollama", "openrouter"}:
        logger.warning(
            f"Invalid AI_PROVIDER: {provider}. Must be 'google', 'ollama', or 'openrouter'."
        )
        return None
    
    prompt = _build_prompt(status_context)
    logger.debug(f"AI prompt ({provider}):\n{prompt}")
    
    tips = []
    
    if provider == "google":
        api_key = os.getenv("GEMINI_API_KEY")
        model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        
        if not api_key:
            logger.warning("GEMINI_API_KEY not configured")
            return None
        
        tips = _call_google_gemini(prompt, model, api_key, count=5)

    elif provider == "ollama":
        base_url = os.getenv("OLLAMA_URL", "http://localhost:11434")
        model = os.getenv("OLLAMA_MODEL", "llama3.2:latest")
        
        # Ollama: generate multiple times
        for _ in range(5):
            result = _call_ollama(prompt, model, base_url)
            if result:
                tips.append(result)
    
    elif provider == "openrouter":
        api_key = os.getenv("OPENROUTER_API_KEY")
        model = os.getenv("OPENROUTER_MODEL", "openai/gpt-oss-120b")
        base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

        if not api_key:
            logger.warning("OPENROUTER_API_KEY not configured")
            return None

        tips = _call_openrouter_chat(prompt, model, api_key, base_url, count=5)
    
    if tips:
        _store_tips_to_cache(tips)
        return random.choice(tips)
    
    return None
