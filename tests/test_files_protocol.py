"""
Tests for FilesProtocolHandler — focused on path-traversal prevention.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.mcp_protocol.handlers.files_protocol import _is_safe_path, _ALLOWED_BASE_DIRS


class TestIsSafePath(unittest.TestCase):
    """_is_safe_path must block paths outside the allowed base directories."""

    def test_home_dir_is_allowed(self):
        home = os.path.expanduser("~")
        self.assertTrue(_is_safe_path(home))

    def test_file_in_home_is_allowed(self):
        self.assertTrue(_is_safe_path(os.path.expanduser("~/documents/notes.txt")))

    def test_tmp_is_allowed(self):
        self.assertTrue(_is_safe_path("/tmp/some_file.txt"))

    def test_etc_passwd_is_blocked(self):
        self.assertFalse(_is_safe_path("/etc/passwd"))

    def test_root_ssh_key_is_blocked(self):
        self.assertFalse(_is_safe_path("/root/.ssh/id_rsa"))

    def test_traversal_through_home_is_blocked(self):
        # Attempt: ~/../../etc/passwd
        traversal = os.path.expanduser("~") + "/../../etc/passwd"
        self.assertFalse(_is_safe_path(traversal))

    def test_absolute_path_outside_allowed_is_blocked(self):
        self.assertFalse(_is_safe_path("/var/log/syslog"))

    def test_proc_mem_is_blocked(self):
        self.assertFalse(_is_safe_path("/proc/self/mem"))


class TestFilesProtocolHandlerAccessControl(unittest.TestCase):
    """Integration-level: the handler must return Access denied for unsafe paths."""

    def setUp(self):
        # Import here to avoid module-level side effects during collection.
        from src.mcp_protocol.handlers.files_protocol import FilesProtocolHandler
        self.handler = FilesProtocolHandler()

    def test_read_etc_passwd_is_denied(self):
        result = self.handler.handle(
            "read:/etc/passwd",
            require_approval=False,
            auto_approve=True,
        )
        self.assertIn("Access denied", result["output"])
        self.assertFalse(result["executed"])

    def test_write_to_etc_is_denied(self):
        result = self.handler.handle(
            "write:/etc/crontab malicious content",
            require_approval=False,
            auto_approve=True,
        )
        self.assertIn("Access denied", result["output"])
        self.assertFalse(result["executed"])

    def test_read_tmp_file_is_allowed(self):
        with tempfile.NamedTemporaryFile(dir="/tmp", suffix=".txt", delete=False,
                                         mode="w") as f:
            f.write("hello")
            tmp_path = f.name
        try:
            result = self.handler.handle(
                f"read:{tmp_path}",
                require_approval=False,
                auto_approve=True,
            )
            self.assertTrue(result["executed"])
            self.assertEqual(result["output"], "hello")
        finally:
            os.unlink(tmp_path)


if __name__ == "__main__":
    unittest.main()
