"""
src/anonymizer.py — Prompt anonymizer for Neo AI.

Replaces PII and server-critical data with stable, numbered placeholders
before sending any text to an external AI backend (OpenAI, Claude).

The same placeholder is reused for the same value across the entire
session so the AI stays consistent ("IP_1 is unreachable" stays coherent
across follow-up messages).  An optional deanonymize pass replaces
placeholders back in the model's response before it is displayed to the
user, keeping the conversation natural.

Detected categories (in processing order):
  API_KEY  — OpenAI / Anthropic secret keys (sk-..., sk-ant-...)
  MAC      — Ethernet MAC addresses
  IP6      — IPv6 addresses (full and compressed)
  IP       — IPv4 addresses
  EMAIL    — E-mail addresses
  HOST     — Seeded hostname (platform.node())
  USER     — Seeded UNIX username ($USER)
  PATH     — /home/<user>/... and /root/... paths
"""

import re
import logging
from typing import Optional


# ── Compiled regex patterns ────────────────────────────────────────────────
# Applied after seeded-value substitution, in this priority order.

_PATTERNS: list[tuple[str, re.Pattern]] = [
    # OpenAI / Anthropic secret keys
    ('API_KEY', re.compile(r'\bsk-(?:ant-)?[A-Za-z0-9\-_]{20,}\b')),

    # MAC address  e.g.  aa:bb:cc:dd:ee:ff
    ('MAC', re.compile(r'\b[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}\b')),

    # IPv6 — covers full form, compressed, and loopback ::1
    ('IP6', re.compile(
        r'(?:'
        r'(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}'          # full
        r'|(?:[0-9a-fA-F]{1,4}:){1,7}:'                        # trailing ::
        r'|(?:[0-9a-fA-F]{1,4}:){1,6}:[0-9a-fA-F]{1,4}'      # compressed end
        r'|::(?:[0-9a-fA-F]{1,4}:){0,5}[0-9a-fA-F]{1,4}'     # leading ::
        r'|::1'                                                  # loopback
        r'|fe80:[0-9a-fA-F:]+(?:%[\w]+)?'                      # link-local
        r')'
    )),

    # IPv4  e.g.  192.168.1.10
    ('IP', re.compile(
        r'\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}'
        r'(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b'
    )),

    # E-mail
    ('EMAIL', re.compile(
        r'\b[\w.+-]{1,64}@[\w-]{1,63}(?:\.[\w-]{2,63})+\b'
    )),
]

# Matches any placeholder we have already written — prevents
# double-anonymisation when the same text is processed twice.
_PH_RE = re.compile(
    r'\[(?:API_KEY|IP6?|MAC|EMAIL|HOST|USER|PATH)_\d+\]'
)

# /home/<user>/...  and  /Users/<user>/...  (always sensitive)
_HOME_PATH_RE = re.compile(
    r'(?<!\[)(/(?:home|Users)/[^/\s][^\s\'"`,;)>\]]*)'
)

# /root/...  (always sensitive)
_ROOT_PATH_RE = re.compile(
    r'(?<!\[)(/root/[^\s\'"`,;)>\]]*)'
)


# ── Anonymizer class ──────────────────────────────────────────────────────────

class PromptAnonymizer:
    """Session-scoped prompt anonymizer.

    Example::

        anon = PromptAnonymizer()
        anon.seed(username="user", hostname="myserver")

        safe_prompt = anon.anonymize(prompt)
        # ... send safe_prompt to OpenAI / Claude ...
        display_text = anon.deanonymize(api_response)
    """

    def __init__(self) -> None:
        self._fwd: dict[str, str] = {}   # real_value  → placeholder
        self._rev: dict[str, str] = {}   # placeholder → real_value
        self._cnt: dict[str, int] = {}   # category    → counter

    # ── Public API ────────────────────────────────────────────────────────────

    def seed(self, username: str = '', hostname: str = '') -> None:
        """Pre-register known system values for consistent placeholder assignment.

        Call once after construction so that the username and hostname always
        map to USER_1 / HOST_1 regardless of whether they appear before or
        after an IP address in the text.
        """
        if username:
            self._register('USER', username)
        if hostname:
            self._register('HOST', hostname)

    def anonymize(self, text: str) -> str:
        """Return *text* with all sensitive values replaced by placeholders."""
        if not text:
            return text

        # Step 1: replace previously seen exact values first so they get their
        # established placeholder even when they appear inside a new context.
        for real, ph in list(self._fwd.items()):
            escaped = re.escape(real)
            text = re.sub(rf'(?<!\[)\b{escaped}\b(?!\])', ph, text)

        # Step 2: anonymise home/root paths before the generic regex pass so
        # the full path string is captured as a single PATH_N token.
        text = _HOME_PATH_RE.sub(self._path_replacer, text)
        text = _ROOT_PATH_RE.sub(self._path_replacer, text)

        # Step 3: regex-based pattern detection
        for category, pattern in _PATTERNS:
            text = pattern.sub(self._make_replacer(category), text)

        return text

    def deanonymize(self, text: str) -> str:
        """Return *text* with all placeholders replaced by the original values."""
        for ph, real in self._rev.items():
            text = text.replace(ph, real)
        return text

    def reset(self) -> None:
        """Clear all mappings.  Call when starting a fresh conversation."""
        self._fwd.clear()
        self._rev.clear()
        self._cnt.clear()
        logging.debug("Anonymizer: mapping reset.")

    @property
    def mapping_count(self) -> int:
        """Number of distinct values currently mapped."""
        return len(self._fwd)

    def summary(self) -> str:
        """Human-readable list of active placeholder → real-value mappings."""
        if not self._fwd:
            return "No anonymisation mappings active."
        lines = [
            f"  {ph:<20} ← {real}"
            for real, ph in sorted(self._fwd.items(), key=lambda kv: kv[1])
        ]
        return "Active anonymisation mappings:\n" + "\n".join(lines)

    # ── Internals ─────────────────────────────────────────────────────────────

    def _register(self, category: str, value: str) -> str:
        """Return the placeholder for *value*, creating a new one if needed."""
        if value in self._fwd:
            return self._fwd[value]
        n = self._cnt.get(category, 0) + 1
        self._cnt[category] = n
        ph = f'[{category}_{n}]'
        self._fwd[value] = ph
        self._rev[ph] = value
        logging.debug("Anonymizer: %r → %s", value, ph)
        return ph

    def _make_replacer(self, category: str):
        """Return a ``re.sub`` replacement callback for *category*."""
        def _replace(m: re.Match) -> str:
            val = m.group(0)
            if _PH_RE.fullmatch(val):   # already anonymised — leave it
                return val
            return self._register(category, val)
        return _replace

    def _path_replacer(self, m: re.Match) -> str:
        val = m.group(1)
        if _PH_RE.fullmatch(val):
            return val
        return self._register('PATH', val)
