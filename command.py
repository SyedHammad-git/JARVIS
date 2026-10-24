"""
J.A.R.V.I.S v17.M — Command Router
FIXED: L3 "sleep" keyword false match, M2 work_session_lock

TASK-020 (Phase 2): narrowed to ONLY the 5 irreversible/disruptive system
actions — shutdown, restart, sleep, lock, hibernate. Volume, screenshot,
folder creation, and open-app used to be keyword-matched here too, but they
already have LLM-callable equivalents in tools.py (control_volume,
take_screenshot, create_folder, open_app), so they were removed from this
rigid router entirely — the agent now handles their natural-language variety
(including Urdu/Roman-Urdu phrasing) instead of requiring exact English
keywords like "create folder" or "volume up".
"""
import logging, re, subprocess
from threading import Lock

from auth import safety_check, add_alert, sec_log_count
from error_utils import classify_exception

log = logging.getLogger("jarvis.command")
command_lock = Lock()

# Guards the 5 keyword matches below from false-triggering on a genuine
# question or discussion that merely mentions the word — "do bears
# hibernate in winter", "why did the system restart", "my screen is
# locked, help" — rather than an actual instruction to do it.
_QUESTION_STARTERS = re.compile(
    r'^\s*(what|why|how|do|does|did|can|could|would|will|is|are|was|were|'
    r'should|explain|tell me|describe|when)\b', re.I
)
_PROBLEM_SIGNALS = re.compile(
    r'\b(help|isn\'?t|won\'?t|doesn\'?t|can\'?t|seems?|stuck|frozen|stopped)\b', re.I
)
def _is_command_not_question(c: str) -> bool:
    if '?' in c:
        return False
    if _QUESTION_STARTERS.match(c):
        return False
    if _PROBLEM_SIGNALS.search(c):
        return False
    if len(c.split()) > 6:   # genuine short commands vs. longer discussion
        return False
    return True

# TASK-023: single source of truth for the 5 safety-critical actions kept
# in TASK-020. Both the keyword match in cmd_route() below AND
# tools.py::tool_system_action() (the new agent-callable version, for when
# the request is phrased in a way this simple keyword match doesn't catch —
# e.g. Roman Urdu, or "put the PC to sleep for a bit") call this exact same
# function. The LLM is free to *recognize* the intent from any phrasing;
# the actual execution is always this one fixed, reviewed code path either
# way — natural-language understanding and safe execution aren't in tension.
_SYSTEM_ACTIONS = {
    "shutdown":  (["shutdown", "/s", "/t", "5"],
                  "Shutting down in 5 seconds, Sir."),
    "restart":   (["shutdown", "/r", "/t", "5"],
                  "Restarting in 5 seconds, Sir."),
    "sleep":     (["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
                  "PC going to sleep, Sir."),
    "lock":      (["rundll32.exe", "user32.dll,LockWorkStation"],
                  "Workstation locked, Sir."),
    "hibernate": (["shutdown", "/h"],
                  "Hibernating, Sir."),
}

def perform_system_action(action: str) -> str:
    """Execute one of the 5 whitelisted system actions (exact key match
    only — callers are responsible for mapping natural language / keywords
    to one of these first, this function does no interpretation itself).
    argv list only — never shell=True."""
    entry = _SYSTEM_ACTIONS.get(action)
    if not entry:
        return f"Unknown system action: {action}"
    cmd, reply = entry
    subprocess.run(cmd, shell=False, check=False)
    log.info("System action executed: %s", action)
    return reply

def cmd_route(raw: str) -> dict:
    with command_lock:
        c    = raw.lower().strip()
        safe, matched = safety_check(c)
        if not safe:
            sec_log_count(blocked=True, cmd=raw)
            msg = f"ACCESS DENIED — Blocked: '{matched}'"
            add_alert(msg)
            return {"handled": True, "blocked": True, "result": msg}
        try:
            cmd_ok = _is_command_not_question(c)
            if re.search(r'\bshut\s*down\b', c) and cmd_ok:
                return {"handled": True, "result": perform_system_action("shutdown")}
            if re.search(r'\brestart\b', c) and cmd_ok:
                return {"handled": True, "result": perform_system_action("restart")}
            # ✅ FIX L3: use word-boundary check so "asleep" doesn't trigger sleep
            if re.search(r'\bsleep\b', c) and "deep sleep" not in c and cmd_ok:
                return {"handled": True, "result": perform_system_action("sleep")}
            if re.search(r'\block\b', c) and cmd_ok:
                return {"handled": True, "result": perform_system_action("lock")}
            if re.search(r'\bhibernate\b', c) and cmd_ok:
                return {"handled": True, "result": perform_system_action("hibernate")}

            # TASK-020: everything else — volume, screenshot, folder
            # creation, open-app, and anything not listed above — is
            # intentionally NOT matched here. It falls through to
            # run_agent (see routes/core_routes.py::do_command, TASK-021),
            # which has LLM-callable tools for all of it and understands
            # natural phrasing/Urdu instead of requiring exact keywords.
            sec_log_count(cmd=raw)
            return {"handled": False, "result": "Unknown command."}
        except Exception as e:
            log.error("cmd_route error: %s", e)
            phrase, _ = classify_exception(e)
            reply = f"I wasn't able to complete that, Sir — {phrase or 'an unexpected error occurred'}."
            return {"handled": False, "result": reply}
