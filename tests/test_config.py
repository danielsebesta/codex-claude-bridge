from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from claude_codex_bridge.config import load_env_file, parse_env_lines, resolve_env_file


class ConfigTests(unittest.TestCase):
    def test_parse_env_lines_ignores_comments(self) -> None:
        values = parse_env_lines(
            [
                "# comment",
                "",
                "CCB_PUBLIC_MODEL=gpt-5.4",
                "CCB_LAUNCH_MODEL=sonnet",
            ]
        )
        self.assertEqual(values["CCB_PUBLIC_MODEL"], "gpt-5.4")
        self.assertEqual(values["CCB_LAUNCH_MODEL"], "sonnet")

    def test_load_env_file_reads_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.env"
            path.write_text("CCB_VENDOR_NAME=OpenAI\n", encoding="utf-8")
            values = load_env_file(path)
            self.assertEqual(values["CCB_VENDOR_NAME"], "OpenAI")

    def test_resolve_env_file_returns_none_for_missing_explicit_file(self) -> None:
        self.assertIsNone(resolve_env_file("/definitely/missing/config.env"))


if __name__ == "__main__":
    unittest.main()
