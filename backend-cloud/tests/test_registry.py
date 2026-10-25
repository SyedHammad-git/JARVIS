"""Registry: device tools hidden when the device is offline."""
import unittest

import app.tools as tools  # noqa: F401 — registers server + device tools
from app.tools.registry import llm_schemas, REGISTRY


class RegistrySchemaTests(unittest.TestCase):
    def test_hides_device_tools_when_offline(self):
        names = {s["function"]["name"] for s in llm_schemas(device_online=False)}
        self.assertIn("get_weather", names)
        self.assertIn("web_search", names)
        self.assertIn("search_memory", names)
        self.assertNotIn("open_app", names)
        self.assertNotIn("system_stats", names)
        self.assertNotIn("clipboard", names)
        for name, tool in REGISTRY.items():
            if tool.where == "device":
                self.assertNotIn(name, names)

    def test_shows_device_tools_when_online(self):
        names = {s["function"]["name"] for s in llm_schemas(device_online=True)}
        self.assertIn("get_weather", names)
        self.assertIn("open_app", names)
        self.assertIn("open_url", names)
        self.assertEqual(
            {name for name, tool in REGISTRY.items() if tool.where == "device"},
            {"open_app", "open_url", "notify", "lock_screen", "system_stats", "take_snapshot"},
        )
        self.assertTrue(all(not hasattr(tool, "local_impl") for tool in REGISTRY.values()))
        self.assertEqual(len(names), len(REGISTRY))

    def test_open_app_is_enum_allowlist(self):
        schema = next(
            s for s in llm_schemas(True) if s["function"]["name"] == "open_app"
        )
        enum = schema["function"]["parameters"]["properties"]["target"]["enum"]
        self.assertIn("notepad", enum)
        self.assertNotIn("regedit", enum)


if __name__ == "__main__":
    unittest.main()
