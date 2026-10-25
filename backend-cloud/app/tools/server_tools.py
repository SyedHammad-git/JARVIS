"""Server-side tools: weather, web search, memory. No local-OS code."""
from __future__ import annotations

import logging

from app.config import REQUESTS_OK, _req, DDGS_OK, DDGS, WEATHER_KEY
from app.error_utils import classify_exception, CircuitBreaker
from app.memory import search_facts_semantic
from app.tools.registry import Tool, register

log = logging.getLogger("jarvis.tools")
_weather_breaker = CircuitBreaker(threshold=3, cooldown=60)


def _friendly(e: Exception) -> str:
    phrase, _ = classify_exception(e)
    return f"I wasn't able to complete that, Sir — {phrase or 'an unexpected error occurred'}."


def tool_web_search(query, max_results=5):
    if not DDGS_OK:
        return "Install: pip install duckduckgo-search"
    try:
        with DDGS() as d:
            results = list(d.text(query, max_results=max_results))
        return ("\n\n".join(
            f"• {r.get('title','')}\n  {r.get('body','')[:300]}"
            for r in results[:max_results]
        )) if results else "No results found, Sir."
    except Exception as e:
        return _friendly(e)


def tool_get_weather(city="Faisalabad"):
    if not REQUESTS_OK:
        return "requests not installed."
    if not _weather_breaker.available():
        return "The weather service is temporarily unavailable, Sir — I'll try again shortly."

    owm_key_invalid = False
    if WEATHER_KEY:
        try:
            r = _req.get(
                "https://api.openweathermap.org/data/2.5/weather",
                params={"q": city, "appid": WEATHER_KEY, "units": "metric"},
                timeout=10,
            )
            if r.status_code == 200:
                d = r.json()
                temp = round(d["main"]["temp"])
                feels = round(d["main"]["feels_like"])
                desc = d["weather"][0]["description"].capitalize()
                hum = d["main"]["humidity"]
                wind = round(d["wind"]["speed"] * 3.6)
                _weather_breaker.record_success()
                return (
                    f"Weather in {city}: {temp}°C (feels {feels}°C) — {desc} | "
                    f"Humidity: {hum}% | Wind: {wind} km/h"
                )
            log.warning("OWM weather failed for %r: HTTP %s — %s",
                        city, r.status_code, r.text[:300])
            if r.status_code in (401, 403):
                owm_key_invalid = True
        except Exception as e:
            log.warning("OWM request error for %r: %s — falling back to wttr.in", city, e)
    else:
        log.info("WEATHER_KEY not set — skipping OWM, using wttr.in directly")

    try:
        r = _req.get(
            f"https://wttr.in/{city}?format=j1",
            timeout=10,
            headers={"User-Agent": "JARVIS/17.0"},
        )
        if r.status_code == 200:
            cur = r.json()["current_condition"][0]
            _weather_breaker.record_success()
            return (
                f"Weather in {city}: {cur['temp_C']}°C (feels {cur['FeelsLikeC']}°C) "
                f"— {cur['weatherDesc'][0]['value']} | "
                f"Humidity: {cur['humidity']}% | Wind: {cur['windspeedKmph']} km/h"
            )
        log.warning("wttr.in failed for %r: HTTP %s — %s", city, r.status_code, r.text[:300])
    except Exception as e:
        log.warning("wttr.in request error for %r: %s", city, e)
        _weather_breaker.record_failure()
        if owm_key_invalid:
            return ("Weather API Key is missing or invalid in .env file, Sir — "
                    "and the backup weather service is unreachable right now too.")
        return _friendly(e)

    _weather_breaker.record_failure()
    if owm_key_invalid:
        return ("Weather API Key is missing or invalid in .env file, Sir — "
                "the backup weather service didn't have data for that city either.")
    return "Weather unavailable, Sir."


def tool_search_memory(query, top_k=5):
    hits = search_facts_semantic(query, top_k=top_k)
    if not hits:
        return "No stored facts matched that, Sir."
    return "\n".join(f"• {h['fact']} ({h['category']})" for h in hits)


register(Tool(
    name="web_search",
    description="Search the internet for current information.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "max_results": {"type": "integer"},
        },
        "required": ["query"],
    },
    where="server",
    risk="low",
    handler=lambda a: tool_web_search(a.get("query", ""), a.get("max_results", 5)),
))

register(Tool(
    name="get_weather",
    description="Get current weather for a city.",
    parameters={
        "type": "object",
        "properties": {"city": {"type": "string"}},
        "required": ["city"],
    },
    where="server",
    risk="low",
    handler=lambda a: tool_get_weather(a.get("city", "Faisalabad")),
))

register(Tool(
    name="search_memory",
    description=(
        "Search facts JARVIS has previously been asked to remember, by meaning "
        "rather than exact wording."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "top_k": {"type": "integer"},
        },
        "required": ["query"],
    },
    where="server",
    risk="low",
    handler=lambda a: tool_search_memory(a.get("query", ""), a.get("top_k", 5)),
))
