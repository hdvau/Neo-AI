"""
Terminal protocol handler for MCP.
Executes shell commands inline in the current terminal (works in SSH / headless).
"""

import logging
import os
import sys
from typing import Dict, Any
from ..registry import ProtocolHandler

parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
sys.path.append(parent_dir)

from src.command_executor import execute_command_inline
from src.approval_handler import ApprovalHandler

logger = logging.getLogger("mcp_protocol.terminal")

_DEFAULT_TIMEOUT = 120  # seconds


class TerminalProtocolHandler(ProtocolHandler):
    """Execute shell commands inline — no separate window required."""

    def __init__(self, command_timeout: int = _DEFAULT_TIMEOUT):
        super().__init__("terminal")
        self.command_timeout = command_timeout

    def handle(self, command: str, require_approval: bool, auto_approve: bool) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "command": command,
            "executed": False,
            "output": "",
            "approved": False,
        }

        try:
            logger.debug("Terminal command requested: %s", command)

            approval_handler = ApprovalHandler(require_approval, auto_approve)
            approved, _ = approval_handler.request_approval(command)
            result["approved"] = approved

            if not approved:
                result["output"] = "Command execution was denied."
                return result

            # Run inline — output streams to the current terminal in real-time.
            output = execute_command_inline(command, timeout=self.command_timeout)
            result["output"] = output
            result["executed"] = True
            logger.debug("Command completed, output length: %d chars", len(output))

        except Exception as e:
            logger.error("Error executing terminal command: %s", e)
            result["error"] = str(e)

        return result


handler = TerminalProtocolHandler()


def register():
    from .. import mcp
    mcp.registry.register_handler(handler)
