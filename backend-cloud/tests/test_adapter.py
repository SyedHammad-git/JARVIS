"""Provider adapter: Groq, OpenRouter, and Gemini normalize to one shape."""
import json
import unittest
from unittest.mock import patch

from app.ai.engine import (
    normalize_openai_chat_completion,
    normalize_gemini_generate_content,
    openai_history_to_gemini,
    chat,
)


def _openai_payload(name="get_weather", city="Lahore"):
    return {
        "choices": [{
            "finish_reason": "tool_calls",
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call_shared",
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": json.dumps({"city": city}),
                    },
                }],
            },
        }]
    }


def _gemini_payload(name="get_weather", city="Lahore"):
    return {
        "candidates": [{
            "content": {
                "role": "model",
                "parts": [{
                    "functionCall": {"name": name, "args": {"city": city}},
                }],
            }
        }]
    }


class AdapterNormalizeTests(unittest.TestCase):
    def test_three_providers_same_tool_call(self):
        groq = normalize_openai_chat_completion(_openai_payload())
        openrouter = normalize_openai_chat_completion(_openai_payload())
        gemini = normalize_gemini_generate_content(_gemini_payload())
        for norm in (groq, openrouter, gemini):
            self.assertTrue(norm["ok"])
            self.assertEqual(len(norm["tool_calls"]), 1)
            self.assertEqual(norm["tool_calls"][0]["name"], "get_weather")
            self.assertEqual(norm["tool_calls"][0]["args"], {"city": "Lahore"})
            self.assertIn("raw_assistant_message", norm)

    def test_gemini_history_conversion_roundtrip(self):
        messages = [
            {"role": "system", "content": "You are JARVIS."},
            {"role": "user", "content": "weather in Lahore?"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call_shared",
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "arguments": '{"city":"Lahore"}',
                    },
                }],
            },
            {
                "role": "tool",
                "tool_call_id": "call_shared",
                "name": "get_weather",
                "content": "30C sunny",
            },
        ]
        contents, g_tools, sys_inst = openai_history_to_gemini(
            messages,
            tools=[{"type": "function", "function": {
                "name": "get_weather",
                "description": "weather",
                "parameters": {"type": "object", "properties": {}},
            }}],
        )
        self.assertIn("JARVIS", sys_inst)
        roles = [c["role"] for c in contents]
        self.assertEqual(roles[0], "user")
        self.assertEqual(roles[1], "model")
        self.assertEqual(roles[2], "user")
        self.assertEqual(contents[1]["parts"][0]["functionCall"]["name"], "get_weather")
        self.assertEqual(contents[2]["parts"][0]["functionResponse"]["name"], "get_weather")
        self.assertEqual(g_tools[0]["functionDeclarations"][0]["name"], "get_weather")


class ChatFailoverTests(unittest.TestCase):
    def test_chat_uses_groq_then_identical_normalize(self):
        payload = _openai_payload()
        with patch("app.ai.engine.groq_available", return_value=True), \
             patch("app.ai.engine.call_groq", return_value={"ok": True, "data": payload}):
            out = chat([{"role": "user", "content": "hi"}], tools=[])
        self.assertTrue(out["ok"])
        self.assertEqual(out["model"], "groq/llama-3.3-70b")
        self.assertEqual(out["tool_calls"][0]["name"], "get_weather")

    def test_chat_failsover_to_openrouter(self):
        payload = _openai_payload()
        with patch("app.ai.engine.groq_available", return_value=False), \
             patch("app.ai.engine.OPENROUTER_KEY", "x"), \
             patch("app.ai.engine.call_openrouter", return_value={"ok": True, "data": payload}):
            out = chat([{"role": "user", "content": "hi"}], tools=[])
        self.assertTrue(out["ok"])
        self.assertEqual(out["model"], "openrouter/claude-haiku")
        self.assertEqual(out["tool_calls"][0]["args"], {"city": "Lahore"})

    def test_chat_failsover_to_gemini_converting_history(self):
        gemini_norm = normalize_gemini_generate_content(_gemini_payload())
        gemini_norm["ok"] = True
        with patch("app.ai.engine.groq_available", return_value=False), \
             patch("app.ai.engine.OPENROUTER_KEY", ""), \
             patch("app.ai.engine.GEMINI_KEY", "x"), \
             patch("app.ai.engine.call_gemini_chat", return_value=gemini_norm) as mock_g:
            out = chat(
                [
                    {"role": "system", "content": "sys"},
                    {"role": "user", "content": "weather"},
                ],
                tools=[{"type": "function", "function": {
                    "name": "get_weather", "description": "",
                    "parameters": {"type": "object", "properties": {}},
                }}],
            )
        self.assertTrue(out["ok"])
        self.assertEqual(out["tool_calls"][0]["name"], "get_weather")
        args, kwargs = mock_g.call_args
        self.assertEqual(kwargs.get("system") or (args[2] if len(args) > 2 else None), "sys")


if __name__ == "__main__":
    unittest.main()
