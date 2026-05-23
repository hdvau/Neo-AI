"""
Security protocol handler for MCP.
This protocol handles security-related operations.
"""

import logging
from typing import Dict, Any
from ..registry import ProtocolHandler
import sys
import os
import shlex

# Get the parent directory to import Neo modules
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
sys.path.append(parent_dir)

# Import terminal handler to execute security commands
from .terminal_protocol import handler as terminal_handler

logger = logging.getLogger("mcp_protocol.security")


class SecurityProtocolHandler(ProtocolHandler):
    """Handler for security protocol commands."""

    def __init__(self):
        """Initialize the security protocol handler."""
        super().__init__("security")

        # Define the security commands
        self.security_commands = {
            # --- User & Account Enumeration ---
            "users": "cat /etc/passwd | grep -v '/nologin' | grep -v '/false'",
            "groups": "cat /etc/group",
            "sudo": "sudo -l",
            "accounts": "lastlog | grep -v 'Never logged in'",
            "logins": "last -n 20",
            "history": "history | tail -n 20",
            "failed-logins": "grep 'Failed password' /var/log/auth.log 2>/dev/null || journalctl -u sshd 2>/dev/null | grep 'Failed password'",
            "nopasswd-sudo": "grep -r 'NOPASSWD' /etc/sudoers /etc/sudoers.d/ 2>/dev/null",
            "uid0": "awk -F: '$3==0{print $1}' /etc/passwd",
            "shadow-perms": "ls -la /etc/shadow /etc/gshadow /etc/passwd /etc/group 2>/dev/null",
            "inactive-accounts": "awk -F: '$2~/^[^!*]/ && $7~/nologin|false/{print $1}' /etc/passwd 2>/dev/null; chage -l root 2>/dev/null | head -5",

            # --- Network & Port Inspection ---
            "ports": "netstat -tuln 2>/dev/null || ss -tuln",
            "listening": "lsof -i -P -n 2>/dev/null | grep LISTEN || ss -tlnp",
            "connections": "ss -tunap 2>/dev/null | head -40",
            "arp": "arp -n 2>/dev/null || ip neigh show",
            "firewall": "iptables -L -n 2>/dev/null || nft list ruleset 2>/dev/null || ufw status verbose 2>/dev/null",
            "fail2ban": "fail2ban-client status 2>/dev/null && fail2ban-client status sshd 2>/dev/null",

            # --- Process & Runtime Inspection ---
            "processes": "ps aux --sort=-%cpu | head -30",
            "processes-tree": "ps auxf 2>/dev/null | head -60",
            "deleted-running": "ls -la /proc/*/exe 2>/dev/null | grep deleted | head -20",

            # --- File System & Permissions ---
            "suid": "find / -perm -4000 -ls 2>/dev/null | head -20",
            "sgid": "find / -perm -2000 -ls 2>/dev/null | head -20",
            "capabilities": "getcap -r / 2>/dev/null | head -20 || echo 'getcap not found'",
            "world-writable": "find / -xdev -perm -0002 -type f 2>/dev/null | grep -v '/proc/' | head -20",
            "unowned-files": "find / -xdev \\( -nouser -o -nogroup \\) -ls 2>/dev/null | grep -v '/proc/' | head -20",
            "tmp-executables": "find /tmp /var/tmp /dev/shm -type f -executable 2>/dev/null",

            # --- Persistence Mechanisms ---
            "cronjobs": "crontab -l 2>/dev/null; ls -la /etc/cron.d/ /etc/cron.daily/ /etc/cron.weekly/ /etc/cron.monthly/ 2>/dev/null; cat /etc/crontab 2>/dev/null",
            "crontabs-all": "for u in $(cut -d: -f1 /etc/passwd); do crontab -u $u -l 2>/dev/null && echo \"--- $u ---\"; done",
            "systemd-units": "systemctl list-units --type=service --state=running --no-pager 2>/dev/null | head -40",
            "systemd-timers": "systemctl list-timers --all --no-pager 2>/dev/null",
            "authorized-keys": "find /home /root -name authorized_keys 2>/dev/null -exec echo '=== {} ===' \\; -exec cat {} \\;",
            "ld-preload": "cat /etc/ld.so.preload 2>/dev/null && echo '---' && env | grep LD_PRELOAD || echo 'LD_PRELOAD not set'",

            # --- Kernel & Modules ---
            "kernelmodules": "lsmod",
            "kernelmodules-unsigned": "for m in $(lsmod | awk 'NR>1{print $1}'); do modinfo $m 2>/dev/null | grep -q '^signer' || echo \"UNSIGNED: $m\"; done",

            # --- SSH Configuration ---
            "ssh-config": "sshd -T 2>/dev/null | grep -iE 'permitroot|passwordauth|pubkeyauth|permitemptypassword|protocol|port|x11forward|allowtcpforward|maxauthtries' || cat /etc/ssh/sshd_config 2>/dev/null | grep -v '^#' | grep -v '^$'",
            "ssh-keys": "find /home /root /etc/ssh -name '*.pub' -o -name 'id_*' 2>/dev/null | grep -v '.pub$' | xargs ls -la 2>/dev/null | head -20",

            # --- Rootkit & Integrity Checks ---
            "rootkits": "rkhunter --check --skip-keypress 2>/dev/null | tail -30 || chkrootkit 2>/dev/null | grep -iE 'infected|suspect|warning' || echo 'No rootkit scanner found (install rkhunter or chkrootkit)'",
        }

    def handle(self, command: str, require_approval: bool, auto_approve: bool) -> Dict[str, Any]:
        """
        Handle security protocol commands (security operations).

        Args:
            command: The security command
            require_approval: Whether approval is required
            auto_approve: Whether to auto-approve

        Returns:
            Dictionary with execution results
        """
        result = {
            "command": command,
            "executed": False,
            "output": ""
        }

        try:
            if command in self.security_commands:
                logger.debug(f"Processing security command: {command}")
                security_command = self.security_commands[command]

                # Execute the security command using terminal protocol
                terminal_result = terminal_handler.handle(
                    security_command, require_approval, auto_approve
                )

                # Add security operation type to result
                terminal_result["security_operation"] = command
                return terminal_result

            elif command.startswith("check:"):
                # Custom security check - format: check:file or directory
                logger.debug(f"Processing custom security check: {command}")
                target = command[6:].strip()
                target = shlex.quote(target)

                # Check permissions, owner, and other security attributes
                check_command = f"ls -la {target} 2>/dev/null && find {target} -type f -perm -o+w -ls 2>/dev/null | head -10"

                terminal_result = terminal_handler.handle(
                    check_command, require_approval, auto_approve
                )

                terminal_result["security_operation"] = "check"
                return terminal_result

            elif command.startswith("vulnerabilities:"):
                # Check for known vulnerabilities - format: vulnerabilities:package
                logger.debug(f"Processing vulnerabilities check: {command}")
                package = command[16:].strip()
                package = shlex.quote(package)

                # Try to check using available tools
                check_command = f"apt list --installed 2>/dev/null | grep {package} || rpm -q {package} 2>/dev/null || pacman -Qi {package} 2>/dev/null"

                terminal_result = terminal_handler.handle(
                    check_command, require_approval, auto_approve
                )

                terminal_result["security_operation"] = "vulnerabilities"
                return terminal_result

            else:
                valid_commands = ", ".join(sorted(self.security_commands.keys()))
                special_commands = "check:<path>, vulnerabilities:<package>"
                result["output"] = f"Unknown security command.\n\nValid commands: {valid_commands}\n\nParametric: {special_commands}"
                logger.warning(f"Unknown security command: {command}")

        except Exception as e:
            logger.error(f"Error processing security command: {str(e)}")
            result["error"] = str(e)

        return result


# Create singleton instance
handler = SecurityProtocolHandler()


def register():
    """Register this protocol handler."""
    from .. import mcp
    mcp.registry.register_handler(handler)