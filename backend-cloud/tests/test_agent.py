"""Agent loop: cloud tools, paired-device dispatch, confirmation, truncation."""
import json
import unittest
from unittest.mock import patch

import app.tools as tools  # noqa: F401
from app.tools.registry import REGISTRY
from app.ai.agent import (
    execute_tool, run_agent, truncate_tool_result, _RESULT_LIMIT,
    _last_action_registry, _last_action_lock,
)


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
        with _last_action_lock:
            _last_action_registry.clear()
        self._weather = REGISTRY["get_weather"].handler
        REGISTRY["get_weather"].handler = lambda a: f"Weather in {a.get('city')}: 22C"

    def tearDown(self):
        REGISTRY["get_weather"].handler = self._weather

    def test_loop_weather_then_open_app_uses_remote_device(self):
        fake = FakeLLM()
        with patch("app.ai.agent.chat", fake), \
             patch("app.ai.agent.save_message", return_value=True), \
             patch("app.ai.agent.load_recent_messages", return_value=[]), \
             patch("app.ai.agent.prune_conversation", return_value=True), \
             patch("app.devices.gateway.call_device", return_value={
                 "ok": True, "message": "Opened notepad",
             }) as call_device:
            out = run_agent(
                "weather in Lahore and open notepad",
                session_id="test-loop",
                ctx={
                    "device_id": "dev_online",
                    "owner_username": "clerk:test-owner",
                    "device_online": True,
                    "confirmed": False,
                },
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
        call_device.assert_called_once()
        self.assertEqual(call_device.call_args.args[:3], (
            "dev_online", "open_app", {"target": "notepad"},
        ))
        self.assertEqual(call_device.call_args.kwargs["owner_username"], "clerk:test-owner")

    def test_device_tool_remote_offline(self):
        with patch("app.devices.gateway.call_device", return_value={"ok": False, "error": "device_offline"}):
            raw = execute_tool(
                "open_app",
                {"target": "notepad"},
                {
                    "device_id": "dev_test",
                    "confirmed": True,
                    "confirmed_signature": 'open_app:{"target": "notepad"}',
                    "confirmation_nonce": "approved-nonce",
                },
            )
        data = json.loads(raw)
        self.assertFalse(data["ok"])
        self.assertEqual(data["error"], "device_offline")

    def test_device_tool_remote_ack(self):
        with patch("app.devices.gateway.call_device",
                   return_value={"ok": True, "message": "fake executed"}) as mock_call:
            raw = execute_tool(
                "open_app",
                {"target": "notepad"},
                {
                    "device_id": "dev_live",
                    "confirmed": True,
                    "confirmed_signature": 'open_app:{"target": "notepad"}',
                    "confirmation_nonce": "approved-nonce",
                },
            )
        mock_call.assert_called_once_with(
            "dev_live",
            "open_app",
            {"target": "notepad"},
            owner_username=None,
            confirmed=True,
            confirmation_nonce="approved-nonce",
        )
        data = json.loads(raw)
        self.assertTrue(data["ok"])
        self.assertEqual(data["message"], "fake executed")

    def test_remote_offline_hides_device_tools_and_explains(self):
        class OfflineLLM:
            def __call__(self, messages, tools=None, **kwargs):
                names = {t["function"]["name"] for t in (tools or [])}
                self.names = names
                self.sys = messages[0]["content"]
                return {
                    "ok": True, "text": "The paired PC is not connected, Sir.",
                    "model": "fake", "error": "", "tool_calls": [],
                    "raw_assistant_message": {
                        "role": "assistant",
                        "content": "The paired PC is not connected, Sir.",
                    },
                }

        fake = OfflineLLM()
        with patch("app.ai.agent.chat", fake), \
             patch("app.ai.agent.save_message", return_value=True), \
             patch("app.ai.agent.load_recent_messages", return_value=[]), \
             patch("app.ai.agent.prune_conversation", return_value=True), \
             patch("app.devices.gateway.is_online", return_value=False):
            out = run_agent(
                "open notepad",
                session_id="test-offline",
                ctx={"device_id": "dev_off", "confirmed": True},
            )
        self.assertTrue(out["ok"])
        self.assertNotIn("open_app", fake.names)
        self.assertIn("device_offline", fake.sys)
        self.assertIn("not connected", out["reply"].lower())

    def test_high_risk_needs_confirmation(self):
        raw = execute_tool(
            "lock_screen",
            {},
            {"confirmed": False},
        )
        data = json.loads(raw)
        self.assertTrue(data.get("needs_confirmation"))
        self.assertEqual(data.get("error"), "needs_confirmation")

    def test_device_action_shares_web_search_batch_requires_confirmation(self):
        response = {
            "ok": True,
            "text": "",
            "model": "fake",
            "error": "",
            "tool_calls": [
                {"id": "open", "name": "open_app", "args": {"target": "notepad"}},
                {"id": "search", "name": "web_search", "args": {"query": "instructions"}},
            ],
            "raw_assistant_message": {"role": "assistant", "content": ""},
        }
        with patch("app.ai.agent.chat", return_value=response), \
             patch("app.ai.agent.save_message", return_value=True), \
             patch("app.ai.agent.load_recent_messages", return_value=[]), \
             patch("app.devices.gateway.call_device") as call_device:
            out = run_agent(
                "search and open notepad",
                ctx={
                    "device_id": "dev_online",
                    "owner_username": "clerk:test-owner",
                    "device_online": True,
                    "confirmed": False,
                },
            )

        self.assertTrue(out["needs_confirmation"])
        self.assertEqual(out["reason"], "untrusted_web_content")
        call_device.assert_not_called()

    def test_confirmed_device_action_requires_matching_signature_and_nonce(self):
        args = {"target": "notepad"}
        with patch("app.devices.gateway.call_device", return_value={"ok": True}) as call_device:
            denied = execute_tool(
                "open_app", args,
                {
                    "confirmed": True,
                    "confirmed_signature": "open_app:{}",
                    "confirmation_nonce": "nonce",
                    "owner_username": "owner-a",
                },
            )
            self.assertTrue(json.loads(denied)["needs_confirmation"])
            call_device.assert_not_called()

            approved = execute_tool(
                "open_app", args,
                {
                    "confirmed": True,
                    "confirmed_signature": "open_app:{\"target\": \"notepad\"}",
                    "confirmation_nonce": "nonce",
                    "owner_username": "owner-a",
                },
            )
            self.assertTrue(json.loads(approved)["ok"])
        call_device.assert_called_once()

    def test_duplicate_action_cache_is_partitioned_by_owner(self):
        with patch("app.devices.gateway.call_device", return_value={"ok": True}) as call_device:
            first = execute_tool(
                "open_app", {"target": "notepad"},
                {"device_id": "dev_a", "owner_username": "owner-a"},
            )
            second = execute_tool(
                "open_app", {"target": "notepad"},
                {"device_id": "dev_b", "owner_username": "owner-b"},
            )

        self.assertIn('"ok": true', first)
        self.assertIn('"ok": true', second)
        self.assertEqual(call_device.call_count, 2)

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
