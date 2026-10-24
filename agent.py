"""
J.A.R.V.I.S v17.M — ReAct Agent
FIXED: M2 work_session_lock, thread-safe counter updates
"""
import json, logging, threading, time
from config import (
    REQUESTS_OK,
    agent_lock,
    work_session, work_session_lock
)
from ai_engine import (
    call_groq, call_openrouter, call_gemini,
    build_jarvis_context, AGENT_SYS_BASE, groq_available
)
from tools import AGENT_TOOLS, TOOL_REG
from error_utils import classify_exception
from memory import save_message, load_recent_messages, prune_conversation

log = logging.getLogger("jarvis.agent")

# ── Execution memory — de-duplicates identical tool calls ──────────
# Lives here (not ai_engine.py) since execute_tool() is its only consumer;
# ai_engine.py has no visibility into individual tool calls at all.
# Guards against the LLM re-issuing the exact same action (same tool, same
# arguments) within a short window — e.g. calling create_folder("Reports")
# twice in a row because it didn't register the first call succeeded.
# Only successes are recorded: a failed call should still be retryable
# immediately (e.g. after the LLM adjusts a bad parameter), so blocking a
# retry of something that just errored would be actively unhelpful.
_last_action_registry = {}
_last_action_lock      = threading.Lock()
_DEDUP_WINDOW_SECS     = 10

def _tool_signature(name: str, args: dict) -> str:
    try:
        return f"{name}:{json.dumps(args, sort_keys=True, default=str)}"
    except Exception:
        return f"{name}:{args!r}"

def execute_tool(name: str, args: dict) -> str:
    fn = TOOL_REG.get(name)
    if not fn:
        return f"Unknown tool: {name}"

    sig = _tool_signature(name, args)
    now = time.time()
    with _last_action_lock:
        # Opportunistic eviction of stale entries so this dict doesn't
        # grow unbounded over a long-running session.
        for k in [k for k, t in _last_action_registry.items() if now - t > _DEDUP_WINDOW_SECS]:
            del _last_action_registry[k]
        last = _last_action_registry.get(sig)
        if last is not None and now - last < _DEDUP_WINDOW_SECS:
            log.info("De-duped repeat call: %s", sig[:120])
            return "This action was just performed, Sir — no need to repeat it."

    try:
        result = fn(args)
        with _last_action_lock:
            _last_action_registry[sig] = time.time()
        return result
    except Exception as e:
        # TASK-030: never let raw Python exception text reach the model
        # or the user — classify_exception() maps it to the same
        # JARVIS-toned phrasing used for HTTP route errors (TASK-011).
        log.warning("Tool error (%s): %s", name, e)
        phrase, _ = classify_exception(e)
        phrase = phrase or "an unexpected error occurred"
        return f"I wasn't able to complete that, Sir — {phrase}."

def run_agent(user_input: str, session_id: str = "default", max_steps: int = 8) -> dict:
    if not REQUESTS_OK:
        return {"ok": False, "reply": "requests not installed.", "steps": []}

    # Non-blocking guard (multi-tab / double-click race protection): if a
    # request is already in flight, reject immediately with a clear message
    # rather than silently queuing behind it or letting two calls race on
    # shared history/db state. Uses its own agent_lock (not ai_lock, which
    # guards the separate neural-heartbeat path) so a background heartbeat
    # check can never block, or be blocked by, a user-initiated chat.
    if not agent_lock.acquire(blocking=False):
        return {"ok": False,
                "reply": "I'm still working on your last request, Sir — one moment.",
                "steps": []}
    try:
        return _run_agent_inner(user_input, session_id, max_steps)
    finally:
        agent_lock.release()   # guaranteed release even if _run_agent_inner raises

def _run_agent_inner(user_input: str, session_id: str, max_steps: int) -> dict:
    # ✅ FIX M2: thread-safe work_session updates
    with work_session_lock:
        work_session["commands_count"] += 1
        work_session["last_active"]     = time.time()

    ctx        = build_jarvis_context()
    sys_prompt = AGENT_SYS_BASE + "\n" + ctx

    history  = load_recent_messages(session_id, limit=10)
    messages = [{"role": "system", "content": sys_prompt}]
    messages.extend({"role": r["role"], "content": r["content"]} for r in history)
    messages.append({"role": "user", "content": user_input})

    steps, model_used = [], "groq"

    for i in range(max_steps):
        try:
            if groq_available():
                result = call_groq(messages, tools=AGENT_TOOLS)
                if result["ok"]:
                    model_used = "groq/llama-3.3-70b"
                    data       = result["data"]
                    choice     = data["choices"][0]
                    message    = choice["message"]
                    messages.append(message)

                    tool_calls = message.get("tool_calls") or []
                    if choice["finish_reason"] == "tool_calls" and tool_calls:
                        for tc in tool_calls:
                            fn_name = tc["function"]["name"]
                            try:   fn_args = json.loads(tc["function"]["arguments"])
                            except (json.JSONDecodeError, KeyError): fn_args = {}
                            log.info("[AGENT][%d] %s", i+1, fn_name)
                            result_str = str(execute_tool(fn_name, fn_args))[:1500]
                            steps.append({
                                "step": i+1, "tool": fn_name,
                                "args": {k: str(v)[:80] for k, v in fn_args.items()},
                                "result": result_str[:200]
                            })
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tc["id"],
                                "content": result_str
                            })
                        continue

                    final     = message.get("content") or "Task complete, Sir."
                    tools_str = ",".join(set(s["tool"] for s in steps))
                    save_message(session_id, "user", user_input, tools_str, model_used)
                    save_message(session_id, "assistant", final, tools_str, model_used)
                    prune_conversation(session_id, keep_last=100)
                    log.info("[AGENT] Done in %d step(s) | Model: %s", i+1, model_used)
                    return {"ok": True, "reply": final, "steps": steps,
                            "iterations": i+1, "model": model_used}

            log.warning("[AGENT] Groq unavailable — falling back to OpenRouter")
            result = call_openrouter(messages)
            if result["ok"]:
                model_used = "openrouter/claude-haiku"
                final      = result["data"]["choices"][0]["message"].get("content", "") or "Done, Sir."
                save_message(session_id, "user", user_input, "", model_used)
                save_message(session_id, "assistant", final, "", model_used)
                return {"ok": True, "reply": final, "steps": steps,
                        "iterations": i+1, "model": model_used}

            prompt = "\n".join(
                m.get("content","") for m in messages[-4:]
                if isinstance(m.get("content"), str) and m.get("role") != "tool"
            )
            result = call_gemini(prompt)
            if result["ok"]:
                return {"ok": True, "reply": result["text"], "steps": steps,
                        "iterations": i+1, "model": "gemini-2.0-flash"}

            return {"ok": False,
                    "reply": "All AI engines unavailable. Please check API keys, Sir.",
                    "steps": steps}

        except Exception as e:
            log.error("[AGENT ERROR] %s", e)
            phrase, _ = classify_exception(e)
            reply = f"I wasn't able to complete that, Sir — {phrase or 'an unexpected error occurred'}."
            return {"ok": False, "reply": reply, "steps": steps}

    return {"ok": True, "reply": "Maximum steps reached, Sir.",
            "steps": steps, "iterations": max_steps, "model": model_used}
