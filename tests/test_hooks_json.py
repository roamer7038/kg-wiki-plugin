"""同梱 hooks.json の規約（03 §5.5、02 §6.6。T5）。"""

import json
import unittest

from helpers import PLUGIN_ROOT

HOOKS_PATH = PLUGIN_ROOT / "hooks" / "hooks.json"
PLUGIN_JSON = PLUGIN_ROOT / ".claude-plugin" / "plugin.json"


class TestHooksJson(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(HOOKS_PATH.read_text(encoding="utf-8"))
        cls.plugin = json.loads(PLUGIN_JSON.read_text(encoding="utf-8"))

    def commands(self):
        for entries in self.data["hooks"].values():
            for entry in entries:
                for hook in entry["hooks"]:
                    yield hook["command"]

    def test_plugin_json_points_at_hooks_file(self):
        """hooks/hooks.json は自動検出されない（04 §10）。明示参照が必須。"""
        self.assertEqual(self.plugin.get("hooks"), "./hooks/hooks.json")

    def test_registers_both_events(self):
        self.assertEqual(set(self.data["hooks"]),
                         {"UserPromptSubmit", "SessionStart"})

    def test_commands_use_plugin_root_absolute_reference(self):
        """bin/ の PATH 追加は Bash ツールにのみ及ぶ（A-1）。"""
        commands = list(self.commands())
        self.assertEqual(len(commands), 2)
        for command in commands:
            self.assertIn('"${CLAUDE_PLUGIN_ROOT}/bin/kg"', command)

    def test_no_user_config_placeholder(self):
        """${user_config.*} を含む hook コマンドは実行されない（04 §10 (a)）。

        有効/無効の判定は kg hook-context 自身が環境変数で行う。
        """
        for command in self.commands():
            self.assertNotIn("user_config", command)

    def test_hook_commands_are_the_always_exit_zero_ones(self):
        joined = "\n".join(self.commands())
        self.assertIn("hook-context", joined)
        self.assertIn("validate --quick", joined)


if __name__ == "__main__":
    unittest.main()
