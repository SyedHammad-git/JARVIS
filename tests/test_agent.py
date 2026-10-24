"""Agent loop: function calling, local device dispatch, confirmation, truncation."""
import json
import unittest
from unittest.mock import patch

import tools  # noqa: F401
from tools.registry import REGISTRY
from agent import execute_tool, run_agent, truncate_tool_result, _RESULT_LIMIT


def _raw_tool_call(call_id, name, args):
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [{
            "id": call_id,
            "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)},
        }],
    }


class FakeLLM:
    """Calls get_weather, then open_app, then a final sentence."""

    def __init__(self):
        self.calls = 0
        self.tools_seen = []

    def __call__(self, messages, tools=None, **kwargs):
        self.calls += 1
        self.tools_seen.append({t["function"]["name"] for t in (tools or [])})
        done = [m.get("name") for m in messages if m.get("role") == "tool"]
        if "get_weather" not in done:
            return {
                "ok": True, "text": "", "model": "fake", "error": "",
                "tool_calls": [{"id": "c1", "name": "get_weather", "args": {"city": "Lahore"}}],
                "raw_assistant_message": _raw_tool_call("c1", "get_weather", {"city": "Lahore"}),
            }
        if "open_app" not in done:
            return {
                "ok": True, "text": "", "model": "fake", "error": "",
                "tool_calls": [{"id": "c2", "name": "open_app", "args": {"target": "notepad"}}],
                "raw_assistant_message": _raw_tool_call("c2", "open_app", {"target": "notepad"}),
            }
        text = "Weather in Lahore is 22C and notepad is open, Sir."
        return {
            "ok": True, "text": text, "model": "fake", "error": "",
            "tool_calls": [],
            "raw_assistant_message": {"role": "assistant", "content": text},
        }


class AgentLoopTests(unittest.TestCase):
    def setUp(self):
        self._weather = REGISTRY["get_weather"].handler
        self._open = REGISTRY["open_app"].local_impl
        REGISTRY["get_weather"].handler = lambda a: f"Weather in {a.get('city')}: 22C"
        REGISTRY["open_app"].local_impl = lambda a: f"Opened {a.get('target')}"

    def tearDown(self):
        REGISTRY["get_weather"].handler = self._weather
        REGISTRY["open_app"].local_impl = self._open

    def test_loop_weather_then_open_app_local(self):
        fake = FakeLLM()
        with patch("agent.chat", fake), \
             patch("agent.save_message", return_value=True), \
             patch("agent.load_recent_messages", return_value=[]), \
             patch("agent.prune_conversation", return_value=True):
            out = run_agent(
                "weather in Lahore and open notepad",
                session_id="test-loop",
                ctx={"execution_mode": "local", "device_online": True, "confirmed": False},
            )
        self.assertTrue(out["ok"])
        tools_used = [s["tool"] for s in out["steps"]]
        self.assertEqual(tools_used, ["get_weather", "open_app"])
        self.assertIn("22C", out["steps"][0]["result"])
        self.assertIn("notepad", out["steps"][1]["result"])
        self.assertIn("notepad", out["reply"])
        self.assertIn("get_weather", fake.tools_seen[0])
        self.assertIn("open_app", fake.tools_seen[0])
        self.assertLessEqual(fake.calls, 6)

    def test_device_tool_remote_stub(self):
        raw = execute_tool(
            "open_app",
            {"target": "notepad"},
            {"execution_mode": "remote", "confirmed": True},
        )
        data = json.loads(raw)
        self.assertFalse(data["ok"])
        self.assertEqual(data["error"], "remote_not_implemented")

    def test_high_risk_needs_confirmation(self):
        raw = execute_tool(
            "kill_process",
            {"name_or_pid": "notepad"},
            {"execution_mode": "local", "confirmed": False},
        )
        data = json.loads(raw)
        self.assertTrue(data.get("needs_confirmation"))
        self.assertEqual(data.get("error"), "needs_confirmation")

    def test_truncate_strips_base64_and_caps_length(self):
        blob = "data:image/png;base64," + ("A" * 400)
        out = truncate_tool_result({"shot": blob})
        self.assertNotIn("AAAA", out)
        self.assertIn("[image omitted]", out)
        long_txt = ("weather report. " * 400)
        capped = truncate_tool_result(long_txt)
        self.assertLessEqual(len(capped), _RESULT_LIMIT + 20)
        self.assertIn("[truncated]", capped)


if __name__ == "__main__":
    unittest.main()
