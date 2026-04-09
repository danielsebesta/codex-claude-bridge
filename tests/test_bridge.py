from __future__ import annotations

import unittest

from claude_codex_bridge.bridge import build_prompt, estimate_tokens, message_response
from claude_codex_bridge.config import BridgeSettings


class BridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = BridgeSettings(
            host="127.0.0.1",
            port=8787,
            default_model="gpt-5.4",
            vendor_name="OpenAI",
            codex_bin="codex",
            codex_model=None,
            codex_exec_args=("--full-auto",),
            workdir=None,
        )

    def test_build_prompt_mentions_public_identity(self) -> None:
        payload = {
            "system": "Follow the request carefully.",
            "messages": [{"role": "user", "content": "Say hello."}],
        }
        prompt = build_prompt(payload, self.settings)
        self.assertIn("You are gpt-5.4 by OpenAI", prompt)
        self.assertIn("<system>", prompt)
        self.assertIn("<user>", prompt)

    def test_estimate_tokens_is_positive(self) -> None:
        self.assertGreaterEqual(estimate_tokens("hello"), 1)

    def test_message_response_uses_requested_model(self) -> None:
        response = message_response("gpt-5.4", "hello", 10, 2)
        self.assertEqual(response["model"], "gpt-5.4")
        self.assertEqual(response["content"][0]["text"], "hello")


if __name__ == "__main__":
    unittest.main()
