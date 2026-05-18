"""
Tests for TokenManager — focused on the security fixes:
- Token cache file permissions (must be 0o600)
- Rejection of world-readable cache files
- Expired token detection
- Corrupted cache handling
"""

import json
import os
import stat
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

import jwt

# Adjust sys.path so we can import from the project root.
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.token_manager import TokenManager


def _make_jwt(exp_offset: int = 3600) -> str:
    """Return a minimal unsigned JWT with given expiry offset (seconds from now)."""
    payload = {"sub": "test-agent", "exp": int(time.time()) + exp_offset}
    return jwt.encode(payload, "secret", algorithm="HS256")


class TestTokenCachePermissions(unittest.TestCase):
    """Token cache must be created owner-only (0o600)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.tm = TokenManager(
            agent_id="test-id",
            agent_key="test-key",
            auth_api_url="https://example.com",
        )
        # Override cache path to our tmp dir so we don't touch the real /tmp.
        self.tm.cache_file = os.path.join(self.tmpdir, "token_cache.json")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_cache_file_permissions_are_0o600(self):
        """Saved cache file must not be readable by group or others."""
        token = _make_jwt()
        self.tm._save_tokens_to_cache(token, token)

        file_mode = os.stat(self.tm.cache_file).st_mode
        # Neither group-read (0o040) nor other-read (0o004) should be set.
        self.assertEqual(file_mode & (stat.S_IRGRP | stat.S_IROTH), 0,
                         "Token cache must not be world-readable")

    def test_cache_file_contains_both_tokens(self):
        access = _make_jwt(3600)
        refresh = _make_jwt(86400)
        self.tm._save_tokens_to_cache(access, refresh)

        with open(self.tm.cache_file) as f:
            data = json.load(f)
        self.assertEqual(data["access_token"], access)
        self.assertEqual(data["refresh_token"], refresh)

    def test_world_readable_cache_is_rejected(self):
        """A cache file with insecure permissions must be deleted and ignored."""
        access = _make_jwt(3600)
        refresh = _make_jwt(86400)
        # Write a valid cache file and then chmod it to 0o644.
        self.tm._save_tokens_to_cache(access, refresh)
        os.chmod(self.tm.cache_file, 0o644)

        result = self.tm._load_tokens_from_cache()
        self.assertIsNone(result, "World-readable cache should be rejected")
        self.assertFalse(os.path.exists(self.tm.cache_file),
                         "Insecure cache file should have been deleted")

    def test_valid_cache_is_loaded(self):
        access = _make_jwt(3600)
        refresh = _make_jwt(86400)
        self.tm._save_tokens_to_cache(access, refresh)

        tokens = self.tm._load_tokens_from_cache()
        self.assertIsNotNone(tokens)
        self.assertEqual(tokens["access_token"], access)

    def test_expired_cache_is_cleared(self):
        expired = _make_jwt(-10)  # expired 10 seconds ago
        self.tm._save_tokens_to_cache(expired, expired)

        result = self.tm._load_tokens_from_cache()
        self.assertIsNone(result, "Both-expired cache should return None")
        self.assertFalse(os.path.exists(self.tm.cache_file),
                         "Expired cache file should have been deleted")

    def test_corrupted_cache_is_ignored(self):
        fd = os.open(self.tm.cache_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write("not-valid-json{{")

        result = self.tm._load_tokens_from_cache()
        self.assertIsNone(result, "Corrupted cache should return None")


class TestTokenExpiry(unittest.TestCase):
    """_is_token_expired should correctly identify valid vs. expired tokens."""

    def setUp(self):
        self.tm = TokenManager("id", "key", "https://example.com")

    def test_valid_token_not_expired(self):
        token = _make_jwt(3600)
        self.assertFalse(self.tm._is_token_expired(token))

    def test_expired_token_is_expired(self):
        token = _make_jwt(-1)
        self.assertTrue(self.tm._is_token_expired(token))

    def test_none_token_is_expired(self):
        self.assertTrue(self.tm._is_token_expired(None))

    def test_garbage_string_is_expired(self):
        self.assertTrue(self.tm._is_token_expired("not.a.jwt"))


if __name__ == "__main__":
    unittest.main()
