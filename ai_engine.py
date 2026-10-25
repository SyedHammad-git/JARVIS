"""
J.A.R.V.I.S v17.M — Multi-AI Engine
FIXED: M3 _manager_cache eviction, M4 ai_router_state thread safety, M1 Gemini URL
"""
import datetime, json, logging, threading, time, uuid

from config import (
    GROQ_KEY, GEMINI_KEY, OPENROUTER_KEY,
    GROQ_URL, GROQ_MODEL, OPENROUTER_URL, OPENROUTER_MODEL,
    ai_lock, ai_router_state, ai_router_lock, stat_lock,
    work_session, cache, REQUESTS_OK, _req, get_gemini_url,
    GROQ_FAIL_THRESHOLD, GROQ_COOLDOWN_SECS
)
from database import db_read, ts

log = logging.getLogger("jarvis.ai")

# ── TASK-012: one quick same-provider retry before failover ────────
# A single transient blip (network hiccup, 429 rate-limit, 5xx) used to
# immediately fail the provider over AND mark it "down" for later calls.
# This adds one short retry within the same provider first, so a momentary
# glitch doesn't needlessly demote a healthy provider or make responses
# feel inconsistent. Does NOT retry 4xx (bad key, bad request) — that's a
# permanent failure and retrying just adds latency for the same result.
_RETRYABLE_STATUS   = {429, 500, 502, 503, 504}
_RETRY_BACKOFF_SECS = 1.5

def _post_with_retry(url, headers=None, json=None, timeout=30, retries=1,
                     backoff=_RETRY_BACKOFF_SECS):
    """POST via _req, retrying `retries` time(s) on transient failures only."""
    last_exc = None
    resp = None
    for attempt in range(retries + 1):
        try:
            resp = _req.post(url, headers=headers, json=json, timeout=timeout)
            if resp.status_code not in _RETRYABLE_STATUS or attempt == retries:
                return resp
            log.warning("Transient HTTP %s from %s — retry %d/%d in %.1fs",
                        resp.status_code, url, attempt + 1, retries, backoff)
        except Exception as e:
            last_exc = e
            if attempt == retries:
                raise
            log.warning("Transient error calling %s (%s) — retry %d/%d in %.1fs",
                        url, e, attempt + 1, retries, backoff)
        time.sleep(backoff)
    if last_exc:
        raise last_exc
    return resp

AGENT_SYS_BASE = """You are JARVIS — Just A Rather Very Intelligent System, built by Hammad.
You are a British AI with precise, calm, slightly witty intelligence. Always address the user as "Sir". Never casual.
Fully autonomous AI with Windows PC access, internet, and all connected systems.

TOOLS: web_search, open_app, open_url, file_find, file_read, get_processes, kill_process,
       get_system_status, take_screenshot, describe_screen, control_volume, type_text,
       get_weather, get_clipboard, set_clipboard, create_folder, system_action, search_memory
There is NO free-form shell tool. Use open_app (allowlisted names) or open_url (http/https).
If a device tool returns device_offline or device_timeout, tell Sir the PC is not connected or did not respond — never claim the action succeeded.

LANGUAGE & PHRASING: The user mixes Urdu, Roman Urdu, and English in the same sentence,
and phrases requests casually rather than in exact keywords — e.g. "notepad khol do",
"zara volume kam karo", "ye process band kardo yaar" and "open notepad" are all
complete, valid requests for the same kind of thing. Understand intent from meaning,
not literal string matching, and map confidently to whichever tool does what's being
asked. Don't ask for clarification or claim not to understand just because the
phrasing isn't textbook English — that's exactly the rigid behavior you're meant to
avoid. Reply in the PERSONALITY below regardless of the input language, unless asked
to reply in a specific language.

PERSONALITY: British formal intelligence. Dry wit at appropriate moments.
Never start with "Sure!", "Of course!", "Great question!" — just answer.
Under 2 sentences unless detail was requested. Never use emoji in text responses.

SAFETY: NEVER use: del, rmdir, format, erase, rd/s, reg delete, diskpart, bcdedit.

CONTEXT (injected automatically):"""


def build_jarvis_context() -> str:
    now          = datetime.datetime.now()
    session_mins = int((time.time() - work_session["start"]) / 60)
    # TASK (QA pass): snapshot every value under stat_lock together, rather
    # than reading cache[...] four separate times unprotected — monitor.py's
    # background thread writes all of these under the same lock every 2s,
    # so an unprotected multi-key read here could show a torn mix of
    # before/after values (cosmetic, but avoidable).
    with stat_lock:
        cpu, ram, disk_pct = cache["cpu"], cache["ram"], cache["disk_pct"]
        battery, charging  = cache["battery"], cache["charging"]
        active_window      = cache.get("active_window", "")
    bat        = f"{battery}%{'⚡' if charging else ''}"
    active_win = active_window[:40]
    facts        = db_read("SELECT fact FROM memory_facts ORDER BY last_used DESC LIMIT 5")
    facts_str    = " | ".join(f.get("fact", "") for f in facts) if facts else "No stored facts"
    return (
        f"Time: {now.strftime('%H:%M')} | Day: {now.strftime('%A')} | "
        f"CPU: {cpu}% | RAM: {ram}% | Battery: {bat} | "
        f"Disk: {disk_pct}% | Window: {active_win or 'unknown'} | "
        f"Session: {session_mins}min | Facts: {facts_str}"
    )

# ── AI Provider Callers ───────────────────────────────────────────
def call_groq(messages: list, tools=None, max_tokens=1024, temperature=0.1) -> dict:
    if not REQUESTS_OK or not GROQ_KEY:
        return {"ok": False, "error": "Groq not configured"}
    try:
        payload = {"model": GROQ_MODEL, "messages": messages,
                   "max_tokens": max_tokens, "temperature": temperature}
        if tools: payload["tools"] = tools; payload["tool_choice"] = "auto"
        resp = _post_with_retry(GROQ_URL,
                         headers={"Authorization": f"Bearer {GROQ_KEY}",
                                  "Content-Type": "application/json"},
                         json=payload, timeout=35)
        if resp.status_code == 200:
            with ai_router_lock:
                ai_router_state["groq_ok"] = True
                ai_router_state["groq_fail_streak"] = 0   # any success clears the streak
            return {"ok": True, "data": resp.json()}
        with ai_router_lock:
            ai_router_state["groq_ok"] = False
            _bump_groq_fail_streak()
        return {"ok": False, "error": f"Groq HTTP {resp.status_code}"}
    except Exception as e:
        with ai_router_lock:
            ai_router_state["groq_ok"] = False
            _bump_groq_fail_streak()
        return {"ok": False, "error": str(e)}

def _bump_groq_fail_streak():
    """Caller must hold ai_router_lock. Increments the consecutive-failure
    streak and, once it crosses GROQ_FAIL_THRESHOLD, opens the circuit
    (groq_cooldown_until) so subsequent calls skip Groq entirely for
    GROQ_COOLDOWN_SECS instead of paying a timeout on a provider that's
    currently down."""
    ai_router_state["groq_fail_streak"] += 1
    if ai_router_state["groq_fail_streak"] >= GROQ_FAIL_THRESHOLD:
        ai_router_state["groq_cooldown_until"] = time.time() + GROQ_COOLDOWN_SECS

def groq_available() -> bool:
    """Single source of truth for 'should we even try Groq right now' —
    used by both _route_inner() here and agent.py::run_agent(), so the
    circuit-breaker applies consistently to every entry point.

    The cooldown timer is the ONLY gate. groq_ok is deliberately NOT also
    checked here: it only flips back to True via a successful call_groq(),
    but call_groq() never runs if something upstream is already refusing
    to call it — checking both would mean a single failure closes the gate
    permanently (until process restart), since nothing would ever call
    Groq again to give it a chance to reset the flag. The cooldown expiring
    is what grants that one retry chance; if it fails, _bump_groq_fail_streak
    just re-opens the cooldown for another GROQ_COOLDOWN_SECS."""
    if not GROQ_KEY:
        return False
    with ai_router_lock:
        return time.time() >= ai_router_state.get("groq_cooldown_until", 0)

def call_gemini(prompt: str, image_base64: str = None) -> dict:
    if not REQUESTS_OK or not GEMINI_KEY:
        return {"ok": False, "error": "Gemini not configured"}
    try:
        # ✅ FIX M1: Use runtime URL builder so key changes are picked up
        url   = get_gemini_url(pro=False)
        parts = [{"text": prompt}]
        if image_base64:
            parts.insert(0, {"inline_data": {"mime_type": "image/jpeg", "data": image_base64}})
        payload = {"contents": [{"parts": parts}],
                   "generationConfig": {"maxOutputTokens": 1024, "temperature": 0.1}}
        resp = _post_with_retry(url, json=payload,
                         headers={"Content-Type": "application/json"}, timeout=30)
        if resp.status_code == 200:
            with ai_router_lock: ai_router_state["gemini_ok"] = True
            text = (resp.json().get("candidates", [{}])[0]
                    .get("content", {}).get("parts", [{}])[0].get("text", ""))
            return {"ok": True, "text": text}
        with ai_router_lock: ai_router_state["gemini_ok"] = False
        return {"ok": False, "error": f"Gemini HTTP {resp.status_code}"}
    except Exception as e:
        with ai_router_lock: ai_router_state["gemini_ok"] = False
        return {"ok": False, "error": str(e)}

def call_openrouter(messages: list, tools=None, max_tokens=1024) -> dict:
    if not REQUESTS_OK or not OPENROUTER_KEY:
        return {"ok": False, "error": "OpenRouter not configured"}
    try:
        payload = {"model": OPENROUTER_MODEL, "messages": messages,
                   "max_tokens": max_tokens, "temperature": 0.1}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        resp = _post_with_retry(OPENROUTER_URL,
                         headers={"Authorization": f"Bearer {OPENROUTER_KEY}",
                                  "Content-Type": "application/json",
                                  "HTTP-Referer": "https://jarvis.local",
                                  "X-Title": "JARVIS"},
                         json=payload,
                         timeout=35)
        if resp.status_code == 200:
            with ai_router_lock: ai_router_state["openrouter_ok"] = True
            return {"ok": True, "data": resp.json()}
        with ai_router_lock: ai_router_state["openrouter_ok"] = False
        return {"ok": False, "error": f"OpenRouter HTTP {resp.status_code}"}
    except Exception as e:
        with ai_router_lock: ai_router_state["openrouter_ok"] = False
        return {"ok": False, "error": str(e)}

# ── Provider adapter: one normalized function-calling shape ───────
def _parse_openai_args(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def normalize_openai_chat_completion(data: dict) -> dict:
    """Groq / OpenRouter chat.completion -> {text, tool_calls, raw_assistant_message}."""
    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    text = message.get("content") or ""
    tool_calls = []
    for tc in message.get("tool_calls") or []:
        fn = tc.get("function") or {}
        tool_calls.append({
            "id": tc.get("id") or f"call_{uuid.uuid4().hex[:24]}",
            "name": fn.get("name") or "",
            "args": _parse_openai_args(fn.get("arguments")),
        })
    return {
        "ok": True,
        "text": text,
        "tool_calls": tool_calls,
        "raw_assistant_message": message,
        "error": "",
    }


def normalize_gemini_generate_content(data: dict) -> dict:
    """Gemini generateContent -> the same normalized dict (OpenAI-shaped raw message)."""
    cand = (data.get("candidates") or [{}])[0]
    parts = (cand.get("content") or {}).get("parts") or []
    texts, tool_calls, openai_tcs = [], [], []
    for part in parts:
        if part.get("text"):
            texts.append(part["text"])
        fc = part.get("functionCall") or part.get("function_call")
        if not fc:
            continue
        tid = f"call_{uuid.uuid4().hex[:24]}"
        name = fc.get("name") or ""
        args = fc.get("args") if isinstance(fc.get("args"), dict) else _parse_openai_args(
            fc.get("args") or fc.get("arguments")
        )
        tool_calls.append({"id": tid, "name": name, "args": args})
        openai_tcs.append({
            "id": tid,
            "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)},
        })
    text = "\n".join(texts)
    raw = {"role": "assistant", "content": text or None}
    if openai_tcs:
        raw["tool_calls"] = openai_tcs
    return {
        "ok": True,
        "text": text,
        "tool_calls": tool_calls,
        "raw_assistant_message": raw,
        "error": "",
    }


def _tool_name_from_history(tool_call_id: str, messages: list) -> str:
    if not tool_call_id:
        return "tool"
    for m in messages:
        for tc in (m.get("tool_calls") or []):
            if tc.get("id") == tool_call_id:
                return (tc.get("function") or {}).get("name") or "tool"
    return "tool"


def openai_history_to_gemini(messages: list, tools=None):
    """Convert OpenAI-format history so failover mid-conversation can hit Gemini."""
    system_parts, contents, pending_fn = [], [], []

    def flush_fn():
        nonlocal pending_fn
        if pending_fn:
            contents.append({"role": "user", "parts": pending_fn})
            pending_fn = []

    for m in messages:
        role = m.get("role")
        if role == "system":
            system_parts.append(m.get("content") or "")
            continue
        if role == "tool":
            fname = m.get("name") or _tool_name_from_history(m.get("tool_call_id"), messages)
            pending_fn.append({
                "functionResponse": {
                    "name": fname,
                    "response": {"result": str(m.get("content") or "")[:4000]},
                }
            })
            continue
        flush_fn()
        if role == "user":
            contents.append({"role": "user", "parts": [{"text": m.get("content") or ""}]})
        elif role == "assistant":
            parts = []
            if m.get("content"):
                parts.append({"text": m["content"]})
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function") or {}
                parts.append({
                    "functionCall": {
                        "name": fn.get("name") or "",
                        "args": _parse_openai_args(fn.get("arguments")),
                    }
                })
            if parts:
                contents.append({"role": "model", "parts": parts})
    flush_fn()

    g_tools = None
    if tools:
        decls = []
        for t in tools:
            fn = t.get("function") or t
            decls.append({
                "name": fn.get("name"),
                "description": fn.get("description") or "",
                "parameters": fn.get("parameters") or {"type": "object", "properties": {}},
            })
        g_tools = [{"functionDeclarations": decls}]
    sys_inst = "\n".join(p for p in system_parts if p) or None
    return contents, g_tools, sys_inst


def call_gemini_chat(contents, tools=None, system=None, max_tokens=1024) -> dict:
    if not REQUESTS_OK or not GEMINI_KEY:
        return {"ok": False, "error": "Gemini not configured", "text": "",
                "tool_calls": [], "raw_assistant_message": None}
    try:
        url = get_gemini_url(pro=False)
        payload = {
            "contents": contents,
            "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.1},
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        if tools:
            payload["tools"] = tools
        resp = _post_with_retry(url, json=payload,
                                headers={"Content-Type": "application/json"}, timeout=35)
        if resp.status_code == 200:
            with ai_router_lock:
                ai_router_state["gemini_ok"] = True
            norm = normalize_gemini_generate_content(resp.json())
            norm["model"] = "gemini-2.0-flash"
            return norm
        with ai_router_lock:
            ai_router_state["gemini_ok"] = False
        return {"ok": False, "error": f"Gemini HTTP {resp.status_code}",
                "text": "", "tool_calls": [], "raw_assistant_message": None}
    except Exception as e:
        with ai_router_lock:
            ai_router_state["gemini_ok"] = False
        return {"ok": False, "error": str(e), "text": "",
                "tool_calls": [], "raw_assistant_message": None}


def _empty_chat(error: str, text: str = "") -> dict:
    return {
        "ok": False, "text": text, "tool_calls": [],
        "raw_assistant_message": None, "model": "none", "error": error,
    }


def chat(messages: list, tools=None, max_tokens=1024, temperature=0.1) -> dict:
    """
    Single adapter: Groq -> OpenRouter -> Gemini.
    Always returns {ok, text, tool_calls:[{id,name,args}], raw_assistant_message, model}.
    History is kept in OpenAI shape; converted only when Gemini is used.
    """
    with ai_router_lock:
        ai_router_state["call_count"] += 1

    if groq_available():
        result = call_groq(messages, tools=tools, max_tokens=max_tokens, temperature=temperature)
        if result.get("ok"):
            with ai_router_lock:
                ai_router_state["active"] = "groq"
            norm = normalize_openai_chat_completion(result["data"])
            norm["model"] = "groq/llama-3.3-70b"
            return norm
        with ai_router_lock:
            ai_router_state["fail_count"] += 1
        log.warning("chat(): Groq failed (%s) — OpenRouter", result.get("error"))

    if OPENROUTER_KEY:
        result = call_openrouter(messages, tools=tools, max_tokens=max_tokens)
        if result.get("ok"):
            with ai_router_lock:
                ai_router_state["active"] = "openrouter"
                ai_router_state["last_switch"] = ts()
                ai_router_state["switch_reason"] = "Groq unavailable"
            norm = normalize_openai_chat_completion(result["data"])
            norm["model"] = "openrouter/claude-haiku"
            return norm
        log.warning("chat(): OpenRouter failed (%s) — Gemini", result.get("error"))

    if GEMINI_KEY:
        contents, g_tools, sys_inst = openai_history_to_gemini(messages, tools)
        result = call_gemini_chat(contents, tools=g_tools, system=sys_inst, max_tokens=max_tokens)
        if result.get("ok"):
            with ai_router_lock:
                ai_router_state["active"] = "gemini"
                ai_router_state["last_switch"] = ts()
                ai_router_state["switch_reason"] = "Groq/OpenRouter unavailable"
            return result
        log.warning("chat(): Gemini failed (%s)", result.get("error"))

    return _empty_chat(
        "all_providers_unavailable",
        "All AI engines unavailable, Sir. Please check API keys in .env.",
    )


# ── ✅ FIX M3: Bounded manager cache with TTL eviction ────────────
_manager_cache: dict = {}
_manager_cache_lock = threading.Lock()   # ✅ thread-safe cache access — TASK-002 fix: 'Lock' was never imported/qualified, crashed the whole app at import time
_CACHE_MAX    = 200        # max entries
_CACHE_TTL    = 300        # seconds (5 min)

def _evict_cache():
    """Remove expired entries and trim if over max size. Caller must hold
    _manager_cache_lock — this only mutates/iterates, never locks itself,
    so two threads evicting at once can't race each other."""
    now     = time.time()
    expired = [k for k, (epoch, _) in _manager_cache.items() if now - epoch > _CACHE_TTL]
    for k in expired:
        _manager_cache.pop(k, None)
    if len(_manager_cache) > _CACHE_MAX:
        oldest = sorted(_manager_cache, key=lambda k: _manager_cache[k][0])
        for k in oldest[:len(_manager_cache) - _CACHE_MAX]:
            _manager_cache.pop(k, None)

def groq_as_manager(trigger: str, worker_output: str,
                    max_tokens: int = 100, context: str = "") -> str:
    if not GROQ_KEY or not REQUESTS_OK:
        return worker_output

    cache_key = f"{trigger}:{worker_output[:60]}"
    # QA pass: read + evict + (later) write all happen under the same lock
    # now — previously only the final write was protected, so a concurrent
    # call's _evict_cache() could mutate the dict mid-iteration from another
    # thread (risk of "dictionary changed size during iteration").
    with _manager_cache_lock:
        cached = _manager_cache.get(cache_key)
        if cached and time.time() - cached[0] < 5:
            return cached[1]
        _evict_cache()   # ✅ FIX M3: periodic eviction

    sys_ctx = build_jarvis_context() if context == "auto" else context
    prompt  = (
        f"System notification:\nEvent: {trigger}\nData: {worker_output}\n"
        + (f"Context: {sys_ctx}\n" if sys_ctx else "")
        + "Relay in 1-2 sentences. British formal. Address as Sir. No markdown."
    )
    try:
        result = call_groq(
            [{"role": "system", "content": "You are JARVIS — British AI. Concise and formal. Address as Sir."},
             {"role": "user", "content": prompt}],
            max_tokens=max_tokens, temperature=0.05
        )
        if result["ok"]:
            reply = result["data"]["choices"][0]["message"].get("content", "").strip()
            if reply:
                with _manager_cache_lock:
                    _manager_cache[cache_key] = (time.time(), reply)
                return reply
    except Exception as e:
        log.error("groq_as_manager failed (%s): %s", trigger, e)
    return worker_output

def groq_as_manager_async(trigger: str, worker_output: str, on_ready, priority: str = "medium"):
    if priority == "critical":
        on_ready(worker_output)
    def _work():
        narrated = groq_as_manager(trigger, worker_output)
        if narrated != worker_output:
            on_ready(narrated)
    threading.Thread(target=_work, daemon=True).start()

# ── AI Router ─────────────────────────────────────────────────────
def route_ai_call(messages: list, tools=None, task_type="chat") -> tuple:
    with ai_lock:
        return _route_inner(messages, tools=tools, task_type=task_type)

def _route_inner(messages: list, tools=None, task_type="chat") -> tuple:
    with ai_router_lock:
        ai_router_state["call_count"] += 1
    steps = []

    if task_type == "vision":
        prompt = messages[-1].get("content", "") if messages else ""
        result = call_gemini(prompt)
        if result["ok"]:
            with ai_router_lock: ai_router_state["active"] = "gemini"
            return result["text"], "gemini-2.0-flash", steps

    if groq_available():
        result = call_groq(messages, tools=tools)
        if result["ok"]:
            with ai_router_lock: ai_router_state["active"] = "groq"
            choice = result["data"]["choices"][0]
            return choice["message"].get("content", ""), "groq/llama-3.3-70b", steps
        with ai_router_lock: ai_router_state["fail_count"] += 1
        log.warning("Groq failed: %s — trying OpenRouter", result.get("error"))

    if OPENROUTER_KEY:
        result = call_openrouter(messages)
        if result["ok"]:
            with ai_router_lock:
                ai_router_state["active"]        = "openrouter"
                ai_router_state["last_switch"]   = ts()
                ai_router_state["switch_reason"] = "Groq unavailable"
            raw = result["data"]["choices"][0]["message"].get("content", "") or ""
            if groq_available():
                summary = groq_as_manager("openrouter_worker", raw, max_tokens=200,
                                          context="OpenRouter completed this task. Relay as JARVIS.")
                return summary, "groq/manager←openrouter", steps
            return raw, "openrouter/claude-haiku", steps

    if GEMINI_KEY:
        prompt = "\n".join(m.get("content", "") for m in messages[-3:]
                           if isinstance(m.get("content"), str))
        result = call_gemini(prompt)
        if result["ok"]:
            with ai_router_lock: ai_router_state["active"] = "gemini"
            raw = result["text"] or ""
            if groq_available():
                summary = groq_as_manager("gemini_worker", raw, max_tokens=200,
                                          context="Gemini completed this task. Relay as JARVIS.")
                return summary, "groq/manager←gemini", steps
            return raw, "gemini-2.0-flash", steps

    return "All AI engines unavailable, Sir. Please check API keys in .env.", "none", steps
