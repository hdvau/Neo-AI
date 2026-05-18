"""
Tests for multiple / duplicate MCP tags in one response.

Two behaviours are verified:
- Different commands of the same protocol all execute (counter-suffix keys).
- Identical (protocol, command) pairs are deduplicated: reasoning models
  sometimes emit the same tag two or three times; only the first must run.
"""

import pytest
from unittest.mock import patch, MagicMock
from src.mcp_protocol.core import MCPProtocol
from src.mcp_protocol.registry import ProtocolRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_protocol_with_mock_handler(handler_fn):
    """Return an MCPProtocol whose 'terminal' handler uses handler_fn."""
    proto = MCPProtocol()
    mock_handler = MagicMock()
    mock_handler.name = "terminal"
    mock_handler.handle.side_effect = handler_fn
    proto.registry.handlers = {"terminal": mock_handler}
    return proto


# ---------------------------------------------------------------------------
# parse_mcp_tags
# ---------------------------------------------------------------------------

class TestParseMcpTags:
    def test_single_tag_parsed(self):
        proto = MCPProtocol()
        tags = proto.parse_mcp_tags("<mcp:terminal>ls -la</mcp:terminal>")
        assert tags == [("terminal", "ls -la")]

    def test_two_same_protocol_tags_both_returned(self):
        proto = MCPProtocol()
        text = (
            "<mcp:terminal>echo hello</mcp:terminal>\n"
            "<mcp:terminal>echo world</mcp:terminal>"
        )
        tags = proto.parse_mcp_tags(text)
        assert len(tags) == 2
        assert tags[0] == ("terminal", "echo hello")
        assert tags[1] == ("terminal", "echo world")

    def test_different_protocols_parsed(self):
        proto = MCPProtocol()
        text = (
            "<mcp:terminal>ls</mcp:terminal>\n"
            "<mcp:files>list:/tmp</mcp:files>"
        )
        tags = proto.parse_mcp_tags(text)
        assert ("terminal", "ls") in tags
        assert ("files", "list:/tmp") in tags


# ---------------------------------------------------------------------------
# process_response — key uniqueness
# ---------------------------------------------------------------------------

class TestMultipleTagsNoCollision:
    def _make_proto(self):
        """Protocol with a terminal handler that records calls."""
        calls = []

        def fake_handle(cmd, require_approval, auto_approve):
            calls.append(cmd)
            return {"command": cmd, "executed": True, "output": f"out:{cmd}", "approved": True}

        proto = _make_protocol_with_mock_handler(fake_handle)
        return proto, calls

    def test_two_terminal_tags_produce_two_keys(self):
        proto, calls = self._make_proto()
        text = (
            "<mcp:terminal>echo first</mcp:terminal>\n"
            "<mcp:terminal>echo second</mcp:terminal>"
        )
        results = proto.process_response(text, require_approval=False, auto_approve=True)

        assert "terminal" in results
        assert "terminal_1" in results
        assert len(results) == 2

    def test_first_command_not_overwritten(self):
        proto, calls = self._make_proto()
        text = (
            "<mcp:terminal>echo first</mcp:terminal>\n"
            "<mcp:terminal>echo second</mcp:terminal>"
        )
        results = proto.process_response(text, require_approval=False, auto_approve=True)

        assert results["terminal"]["command"] == "echo first"
        assert results["terminal_1"]["command"] == "echo second"

    def test_three_different_commands_all_execute(self):
        proto, calls = self._make_proto()
        text = (
            "<mcp:terminal>a</mcp:terminal>"
            "<mcp:terminal>b</mcp:terminal>"
            "<mcp:terminal>c</mcp:terminal>"
        )
        results = proto.process_response(text, require_approval=False, auto_approve=True)

        assert set(results.keys()) == {"terminal", "terminal_1", "terminal_2"}

    def test_single_tag_still_uses_bare_key(self):
        proto, calls = self._make_proto()
        results = proto.process_response(
            "<mcp:terminal>ls</mcp:terminal>",
            require_approval=False,
            auto_approve=True,
        )
        assert list(results.keys()) == ["terminal"]


# ---------------------------------------------------------------------------
# Deduplication — identical tags must not run twice
# ---------------------------------------------------------------------------

class TestDuplicateTagDeduplication:
    """Reasoning models (o1, o3, gpt-5.x) sometimes repeat the same tag.
    The parser must drop duplicates so the command runs only once."""

    def test_duplicate_tag_deduplicated_in_parse(self):
        proto = MCPProtocol()
        text = (
            "<mcp:terminal>find $HOME -name foo</mcp:terminal>\n"
            "<mcp:terminal>find $HOME -name foo</mcp:terminal>\n"
            "<mcp:terminal>find $HOME -name foo</mcp:terminal>"
        )
        tags = proto.parse_mcp_tags(text)
        assert len(tags) == 1
        assert tags[0] == ("terminal", "find $HOME -name foo")

    def test_duplicate_tag_executes_only_once(self):
        call_count = []

        def fake_handle(cmd, require_approval, auto_approve):
            call_count.append(cmd)
            return {"command": cmd, "executed": True, "output": "ok", "approved": True}

        proto = MCPProtocol()
        mock_handler = MagicMock()
        mock_handler.name = "terminal"
        mock_handler.handle.side_effect = fake_handle
        proto.registry.handlers = {"terminal": mock_handler}

        text = (
            "<mcp:terminal>ls -la</mcp:terminal>"
            "<mcp:terminal>ls -la</mcp:terminal>"
        )
        proto.process_response(text, require_approval=False, auto_approve=True)

        assert len(call_count) == 1

    def test_different_commands_not_deduplicated(self):
        proto = MCPProtocol()
        text = (
            "<mcp:terminal>echo hello</mcp:terminal>"
            "<mcp:terminal>echo world</mcp:terminal>"
        )
        tags = proto.parse_mcp_tags(text)
        assert len(tags) == 2

    def test_same_command_different_protocols_not_deduplicated(self):
        """Same content but different protocols must both be kept."""
        proto = MCPProtocol()
        text = (
            "<mcp:terminal>connections</mcp:terminal>"
            "<mcp:network>connections</mcp:network>"
        )
        tags = proto.parse_mcp_tags(text)
        assert len(tags) == 2
