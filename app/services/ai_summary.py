from __future__ import annotations

import os
from typing import Optional

import requests
from google import genai
from google.genai import types
from loguru import logger


def _build_prompt(status_context: dict) -> str:
    """Build AI prompt from status context data."""
    prompt_parts = [
        "당신은 대학 기숙사 세탁실 현황을 간결하게 요약하는 AI입니다.",
        "다음 정보를 바탕으로 현재 세탁실 상황을 **한 줄**로 요약해주세요.",
        "자연스럽고 친근한 말투로 작성하되, 핵심 정보(혼잡도, 대기 시간, 날씨 등)를 포함해주세요.",
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

    # Weather context
    weather = status_context.get("weather")
    if weather:
        temp = weather.get("temperature")
        pty = weather.get("precipitation_type")
        pop = weather.get("precipitation_probability")
        weather_info = []
        if temp is not None:
            weather_info.append(f"기온 {temp}°C")
        if pty and pty != "없음":
            weather_info.append(f"{pty}")
        elif pop is not None and pop > 50:
            weather_info.append(f"강수확률 {pop}%")
        if weather_info:
            prompt_parts.append(f"- 날씨: {', '.join(weather_info)}")

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

    prompt_parts.append("")
    prompt_parts.append("위 정보를 바탕으로 현재 세탁실 상황을 한 줄로 요약해주세요. 이모지를 적절히 사용하면 좋습니다.")

    return "\n".join(prompt_parts)


def _call_google_gemini(prompt: str, model: str, api_key: str) -> Optional[str]:
    """Call Google Gemini API for text generation with thinking disabled."""
    try:
        client = genai.Client(api_key=api_key)
        
        # System instruction for concise summarization
        system_instruction = (
            "당신은 대학 기숙사 세탁실 현황을 간결하게 요약하는 AI입니다. "
            "반드시 한 줄로만 요약하며, 자연스럽고 친근한 말투를 사용합니다. "
            "핵심 정보(혼잡도, 대기 시간, 날씨)를 포함하고 이모지를 적절히 활용합니다."
        )
        
        # Configure with thinking disabled for faster response
        config = types.GenerateContentConfig(
            temperature=0.7,
            max_output_tokens=200,
            top_p=0.9,
            system_instruction=system_instruction,
        )
        
        # Disable thinking for Gemini 2.5 Flash
        if "2.5" in model.lower() and "flash" in model.lower():
            config.thinking_config = types.ThinkingConfig(thinking_budget=0)
        
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=config,
        )
        
        if response and response.text:
            return response.text.strip()
        
        logger.warning("Gemini response missing text")
        return None
    except Exception as exc:
        logger.error(f"Google Gemini API call failed: {exc}")
        return None


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


def generate_summary(status_context: dict) -> Optional[str]:
    """Generate one-line summary of laundry room status using configured AI provider.
    
    Args:
        status_context: Dict containing time, weather, rooms, totals, alerts, etc.
    
    Returns:
        Generated summary string or None if generation fails.
    """
    provider = os.getenv("AI_PROVIDER", "google").lower()
    
    if provider not in {"google", "ollama"}:
        logger.warning(f"Invalid AI_PROVIDER: {provider}. Must be 'google' or 'ollama'.")
        return None
    
    prompt = _build_prompt(status_context)
    logger.debug(f"AI prompt ({provider}):\n{prompt}")
    
    if provider == "google":
        api_key = os.getenv("GEMINI_API_KEY")
        model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash-exp")
        
        if not api_key:
            logger.warning("GEMINI_API_KEY not configured")
            return None
        
        return _call_google_gemini(prompt, model, api_key)
    
    elif provider == "ollama":
        base_url = os.getenv("OLLAMA_URL", "http://localhost:11434")
        model = os.getenv("OLLAMA_MODEL", "llama3.2:latest")
        
        return _call_ollama(prompt, model, base_url)
    
    return None
