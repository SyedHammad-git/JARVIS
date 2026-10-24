"""
J.A.R.V.I.S v17.M — Native function-calling agent
"""
import json, logging, re, threading, time
from config import (
    REQUESTS_OK,
    agent_lock,
    work_session, work_session_lock,
    EXECUTION_MODE, DEVICE_ID,
)
from ai_engine import chat, build_jarvis_context, AGENT_SYS_BASE
from tools.registry import llm_schemas, get_tool
from error_utils import classify_exception
from memory import save_message, load_recent_messages, prune_conversation

log = logging.getLogger("jarvis.agent")

_last_action_registry = {}
_last_action_lock = threading.Lock()
_DEDUP_WINDOW_SECS = 10
_RESULT_LIMIT = 4000
_DATA_URI_B64 = re.compile(r"data:image/[a-zA-Z0+.-]+;base64,[A-Za-z0-9+/=\s]+")
_LONG_B64 = re.compile(r"[A-Za-z0-9+/]{200,}={0,2}")


def _tool_signature(name: str, args: dict) -> str:
    try:
        return f"{name}:{json.dumps(args, sort_keys=True, default=str)}"
    except Exception:
        return f"{name}:{args!r}"


def truncate_tool_result(result, limit: int = _RESULT_LIMIT) -> str:
    if result is None:
        return ""
    if isinstance(result, (dict, list)):
        text = json.dumps(result, default=str)
    else:
        text = str(result)
    text = _DATA_URI_B64.sub("[image omitted]", text)
    text = _LONG_B64.sub("[binary omitted]", text)
    if len(text) > limit:
        text = text[:limit] + "\n[truncated]"
    return text


def execute_tool(name: str, args: dict, ctx: dict | None = None) -> str:
    ctx = ctx or {}
    tool = get_tool(name)
    if not tool:
        return json.dumps({"ok": False, "error": "unknown_action", "tool": name})

    sig = _tool_signature(name, args or {})
    now = time.time()
    with _last_action_lock:
        for k in [k for k, t in _last_action_registry.items() if now - t > _DEDUP_WINDOW_SECS]:
            del _last_action_registry[k]
        last = _last_action_registry.get(sig)
        if last is not None and now - last < _DEDUP_WINDOW_SECS:
            log.info("De-duped repeat call: %s", sig[:120])
            return "This action was just performed, Sir — no need to repeat it."

    if tool.risk == "high" and not ctx.get("confirmed"):
        return json.dumps({
            "ok": False,
            "needs_confirmation": True,
            "error": "needs_confirmation",
            "tool": name,
            "args": args or {},
        })

    mode = ctx.get("execution_mode") or EXECUTION_MODE
    if tool.where == "device":
        if mode != "local":
            return json.dumps({"ok": False, "error": "remote_not_implemented"})
        fn = tool.local_impl
    else:
        fn = tool.handler
    if not fn:
        return json.dumps({"ok": False, "error": "unknown_action", "tool": name})

    try:
        result = fn(args or {})
        with _last_action_lock:
            _last_action_registry[sig] = time.time()
        return truncate_tool_result(result)
    except Exception as e:
        log.warning("Tool error (%s): %s", name, e)
        phrase, _ = classify_exception(e)
        phrase = phrase or "an unexpected error occurred"
        return f"I wasn't able to complete that, Sir — {phrase}."


def run_agent(user_input: str, session_id: str = "default",
              max_steps: int = 6, ctx: dict | None = None) -> dict:
    if not REQUESTS_OK:
        return {"ok": False, "reply": "requests not installed.", "steps": []}

    if not agent_lock.acquire(blocking=False):
        return {"ok": False,
                "reply": "I'm still working on your last request, Sir — one moment.",
                "steps": []}
    try:
        return _run_agent_inner(user_input, session_id, max_steps, ctx or {})
    finally:
        agent_lock.release()


def _run_agent_inner(user_input: str, session_id: str, max_steps: int, ctx: dict) -> dict:
    with work_session_lock:
        work_session["commands_count"] += 1
        work_session["last_active"] = time.time()

    ctx = dict(ctx)
    ctx.setdefault("execution_mode", EXECUTION_MODE)
    ctx.setdefault("device_id", DEVICE_ID)
    ctx.setdefault("confirmed", False)
    device_online = ctx.get("device_online")
    if device_online is None:
        device_online = ctx["execution_mode"] == "local"

    schemas = llm_schemas(device_online=bool(device_online))
    sys_prompt = AGENT_SYS_BASE + "\n" + build_jarvis_context()

    history = load_recent_messages(session_id, limit=10)
    messages = [{"role": "system", "content": sys_prompt}]
    messages.extend({"role": r["role"], "content": r["content"]} for r in history)
    messages.append({"role": "user", "content": user_input})

    steps, model_used = [], "none"

    for i in range(max_steps):
        try:
            result = chat(messages, tools=schemas)
            if not result.get("ok"):
                reply = result.get("text") or result.get("error") or "All AI engines unavailable, Sir."
                return {"ok": False, "reply": reply, "steps": steps,
                        "iterations": i + 1, "model": result.get("model", "none")}

            model_used = result.get("model") or model_used
            raw = result.get("raw_assistant_message")
            if raw:
                messages.append(raw)
            elif result.get("text"):
                messages.append({"role": "assistant", "content": result["text"]})

            tool_calls = result.get("tool_calls") or []
            if tool_calls:
                for tc in tool_calls:
                    fn_name = tc.get("name") or ""
                    fn_args = tc.get("args") if isinstance(tc.get("args"), dict) else {}
                    log.info("[AGENT][%d] %s", i + 1, fn_name)
                    result_str = execute_tool(fn_name, fn_args, ctx)
                    steps.append({
                        "step": i + 1, "tool": fn_name,
                        "args": {k: str(v)[:80] for k, v in fn_args.items()},
                        "result": result_str[:200],
                    })
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id") or "",
                        "name": fn_name,
                        "content": result_str,
                    })
                continue

            final = result.get("text") or "Task complete, Sir."
            tools_str = ",".join(set(s["tool"] for s in steps))
            save_message(session_id, "user", user_input, tools_str, model_used)
            save_message(session_id, "assistant", final, tools_str, model_used)
            prune_conversation(session_id, keep_last=100)
            log.info("[AGENT] Done in %d step(s) | Model: %s", i + 1, model_used)
            return {"ok": True, "reply": final, "steps": steps,
                    "iterations": i + 1, "model": model_used}

        except Exception as e:
            log.error("[AGENT ERROR] %s", e)
            phrase, _ = classify_exception(e)
            reply = f"I wasn't able to complete that, Sir — {phrase or 'an unexpected error occurred'}."
            return {"ok": False, "reply": reply, "steps": steps}

    return {"ok": True, "reply": "Maximum steps reached, Sir.",
            "steps": steps, "iterations": max_steps, "model": model_used}
