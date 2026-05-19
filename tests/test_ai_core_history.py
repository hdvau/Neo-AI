"""
Tests for NeoAI history trimming — prevents unbounded memory growth.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestHistoryTrimming(unittest.TestCase):
    """_trim_history must keep history within the configured limit."""

    def _make_ai(self, max_messages: int = 10):
        """Build a NeoAI instance with a minimal config, bypassing I/O."""
        from src.ai_core import NeoAI

        config = {
            "mode": "lm_studio",
            "api_url": "http://127.0.0.1:1234/v1",
            "api_key": "",
            "model": "test-model",
            "max_history_messages": max_messages,
            "command_approval": {"require_approval": True, "auto_approve_all": False},
            "stream": False,
        }
        ai = NeoAI.__new__(NeoAI)
        ai.mode = config["mode"]
        ai.require_approval = True
        ai.auto_approve_all = False
        ai.is_streaming_mode = False
        ai.config = config
        ai.history = []
        ai.context_initialized = True
        ai._max_history_messages = max_messages
        ai._openai_client = MagicMock()
        return ai

    def test_history_within_limit_is_unchanged(self):
        ai = self._make_ai(max_messages=10)
        for i in range(5):
            ai.history.append({"role": "user", "content": f"msg {i}"})
        ai._trim_history()
        self.assertEqual(len(ai.history), 5)

    def test_history_exceeding_limit_is_trimmed(self):
        ai = self._make_ai(max_messages=10)
        for i in range(20):
            ai.history.append({"role": "user", "content": f"msg {i}"})
        ai._trim_history()
        self.assertLessEqual(len(ai.history), 10)

    def test_first_message_is_preserved_after_trim(self):
        ai = self._make_ai(max_messages=6)
        ai.history.append({"role": "user", "content": "FIRST_MESSAGE"})
        for i in range(20):
            ai.history.append({"role": "user", "content": f"msg {i}"})
        ai._trim_history()
        self.assertEqual(ai.history[0]["content"], "FIRST_MESSAGE")

    def test_most_recent_messages_are_kept(self):
        ai = self._make_ai(max_messages=6)
        ai.history.append({"role": "user", "content": "first"})
        for i in range(20):
            ai.history.append({"role": "user", "content": f"msg {i}"})
        ai._trim_history()
        # Last message before trim should still be present.
        contents = [m["content"] for m in ai.history]
        self.assertIn("msg 19", contents)


if __name__ == "__main__":
    unittest.main()
