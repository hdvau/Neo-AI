import logging
import os
import platform
import shutil
from src.command_executor import execute_command_in_terminal, execute_command
from src.utils import load_persistent_memory
from src.mcp_protocol import mcp  # Import the MCP singleton
import openai
from src.command_executor import wait_for_command_completion
from src.approval_handler import ApprovalHandler

try:
    import anthropic as _anthropic_sdk
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _ANTHROPIC_AVAILABLE = False

# Clear all proxy environment variables
os.environ.pop('http_proxy', None)
os.environ.pop('https_proxy', None)
os.environ.pop('HTTP_PROXY', None)
os.environ.pop('HTTPS_PROXY', None)
os.environ.pop('all_proxy', None)
os.environ.pop('ALL_PROXY', None)
os.environ.pop('socks_proxy', None)
os.environ.pop('SOCKS_PROXY', None)

# Log level is INFO by default; set NEO_DEBUG=1 to enable DEBUG output.
_log_level = logging.DEBUG if os.environ.get("NEO_DEBUG") else logging.INFO
logging.basicConfig(level=_log_level, format="%(asctime)s - %(levelname)s - %(message)s")


class NeoAI:
    def __init__(self, config):
        self.mode = config.get('mode', 'lm_studio')
        logging.info(f"Initializing NeoAI in {self.mode} mode.")
        self.require_approval = config.get('command_approval', {}).get('require_approval', True)
        self.auto_approve_all = config.get('command_approval', {}).get('auto_approve_all', False)
        self.is_streaming_mode = config.get('stream', True)
        self.config = config

        if self.mode == 'claude':
            if not _ANTHROPIC_AVAILABLE:
                raise ImportError(
                    "The 'anthropic' package is required for Claude mode.\n"
                    "Install it with: pip install anthropic"
                )
            claude_cfg = config.get('claude_config', {})
            api_key = claude_cfg.get('api_key') or os.environ.get('ANTHROPIC_API_KEY', '')
            if not api_key:
                raise ValueError(
                    "An Anthropic API key is required for Claude mode.\n"
                    "Set 'claude_config.api_key' in config.yaml or export ANTHROPIC_API_KEY."
                )
            self.model = claude_cfg.get('model', 'claude-opus-4-5')
            self._claude_max_tokens = claude_cfg.get('max_tokens', 4096)
            self._anthropic_client = _anthropic_sdk.Anthropic(api_key=api_key)

        elif self.mode == 'ollama':
            ollama_cfg = config.get('ollama_config', {})
            openai.api_base = ollama_cfg.get('api_url', 'http://localhost:11434/v1')
            # Ollama requires no real key but the openai library needs a non-empty value.
            openai.api_key = ollama_cfg.get('api_key', 'ollama')
            self.model = ollama_cfg['model']

        else:
            # lm_studio mode — support both nested (lm_studio_config.*)
            # and the legacy flat-key format (api_url / api_key / model).
            lm_cfg = config.get('lm_studio_config', {})
            openai.api_base = lm_cfg.get('api_url') or config.get('api_url', '')
            openai.api_key = lm_cfg.get('api_key') or config.get('api_key', '')
            self.model = lm_cfg.get('model') or config.get('model', '')

        self.lm_studio_config = config.get('lm_studio_config', {})
        self.history = []
        self.context_initialized = False
        # Maximum number of messages kept in history to prevent unbounded memory
        # growth and token-limit breaches. Keeps the last N message pairs.
        self._max_history_messages: int = config.get('max_history_messages', 40)

        # Load the system prompt (PrePromt.md) so the model knows to use
        # MCP tags for command execution. Without this the model answers as a
        # plain chatbot and never generates <mcp:terminal> tags.
        self._load_system_prompt(config)

        # Wire the command timeout from config into the terminal protocol handler.
        # The handler singleton is created at import time with a default; update
        # it now that the real config is available.
        _cmd_timeout: int = config.get('command_timeout', 120)
        try:
            from src.mcp_protocol.handlers.terminal_protocol import handler as _t_handler
            _t_handler.command_timeout = _cmd_timeout
        except Exception:
            pass  # Non-fatal — handler keeps its built-in default

    def _load_system_prompt(self, config: dict) -> None:
        """Prepend the system prompt to history as a 'system' role message.

        Looks for the prompt file at (in order):
          1. config['system_prompt_path']  — explicit override in config.yaml
          2. config/PrePromt.md            — default location in the project
        Falls back to a minimal inline prompt when neither file is found.
        """
        import os as _os

        script_dir = _os.path.dirname(_os.path.realpath(__file__))
        project_root = _os.path.join(script_dir, "..")

        candidates = [
            config.get("system_prompt_path"),
            _os.path.join(project_root, "config", "PrePromt.md"),
        ]

        system_text = None
        for path in candidates:
            if path and _os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        system_text = f.read().strip()
                    logging.info("System prompt loaded from: %s", path)
                    break
                except OSError as e:
                    logging.warning("Could not read system prompt from %s: %s", path, e)

        if not system_text:
            logging.warning(
                "config/PrePromt.md not found — using minimal fallback system prompt. "
                "The model may not generate MCP tags correctly."
            )
            system_text = (
                "You are Neo, a Linux terminal AI assistant. "
                "Use MCP protocol tags to execute commands: "
                "<mcp:terminal>command</mcp:terminal>. "
                "Always use these tags when the user asks you to run something."
            )

        self.history = [{"role": "system", "content": system_text}]

    def _trim_history(self) -> None:
        """Drop oldest messages when history exceeds the configured limit.

        The first message (context/system prompt) is always preserved so the AI
        retains its initial environment context.
        """
        if len(self.history) > self._max_history_messages:
            keep = self._max_history_messages - 1  # reserve slot for first msg
            self.history = self.history[:1] + self.history[-keep:]
            logging.debug("History trimmed to %d messages.", len(self.history))

    @staticmethod
    def _gather_system_info() -> str:
        """Return a concise, structured summary of the host OS for the system context.

        Uses only stdlib (platform, shutil, os) — no network, no subprocess.
        The result is injected into the <context> block so the model knows
        which OS it is talking to and picks the right commands from the start.
        """
        raw_os = platform.system()           # "Darwin" | "Linux" | "Windows"
        os_name = {"Darwin": "macOS", "Linux": "Linux", "Windows": "Windows"}.get(raw_os, raw_os)

        # Human-readable version string
        if raw_os == "Darwin":
            mac_ver = platform.mac_ver()[0]  # e.g. "14.5"
            os_version = f"macOS {mac_ver}" if mac_ver else "macOS (version unknown)"
        else:
            # On Linux this gives the distro string; on Windows the NT version.
            os_version = platform.version() or platform.release() or os_name

        arch = platform.machine()            # e.g. "arm64", "x86_64"
        hostname = platform.node()
        shell = os.environ.get("SHELL", "unknown")

        # Detect the available package manager(s)
        pkg_managers = [pm for pm in ("brew", "apt", "apt-get", "dnf", "pacman", "zypper", "yum") if shutil.which(pm)]
        pkg_info = ", ".join(pkg_managers) if pkg_managers else "none detected"

        lines = [
            "## System Information",
            f"OS:              {os_version}",
            f"Architecture:    {arch}",
            f"Hostname:        {hostname}",
            f"Shell:           {shell}",
            f"Package manager: {pkg_info}",
        ]

        # macOS-specific reminders so the model never uses Linux-only tools
        if raw_os == "Darwin":
            lines += [
                "",
                "macOS notes (IMPORTANT):",
                "  - Use `brew` for package management, NOT apt/apt-get/dnf/yum",
                "  - Use `ifconfig` for network interfaces, NOT `ip addr`",
                "  - Use `netstat -an` or `lsof -i`, NOT `ss`",
                "  - Use `top` or `htop` (if installed), NOT `vmstat` (limited on macOS)",
                "  - GNU coreutils may not be available; prefer BSD-style flags",
                "  - Use `open` to launch apps/files, NOT `xdg-open`",
            ]
        elif raw_os == "Linux":
            lines += [
                "",
                "Linux notes:",
                "  - Use `ip addr` for network interfaces",
                "  - Use `systemctl` for service management (if systemd)",
            ]

        return "\n".join(lines)

    def initialize_context(self):
        context_commands = [
            "pwd",
            "ls"
        ]
        context_data = load_persistent_memory()
        system_info = self._gather_system_info()

        initial_context = "<context>\n"
        initial_context += system_info + "\n\n"

        for command in context_commands:
            result = execute_command(command)
            initial_context += f"Command: {command}\nResult:\n{result}\n"

        full_context = f"{context_data}\n\n{initial_context}</context>"
        self.context_initialized = True
        return full_context

    # ── Claude (Anthropic) ───────────────────────────────────────────────────

    def _claude_messages(self) -> tuple:
        """Split history into (system_prompt, messages_list) for the Claude API.

        The Anthropic SDK does not accept a 'system' role inside the messages
        array — it must be passed as a separate `system=` parameter.
        Only 'user' and 'assistant' roles are allowed in the messages list.
        """
        system = ""
        messages = []
        for msg in self.history:
            if msg["role"] == "system":
                system = msg["content"]
            else:
                messages.append({"role": msg["role"], "content": msg["content"]})
        return system, messages

    def _query_claude(self, prompt: str, clear_thinking: bool = False) -> str:
        """Stream a Claude response and process MCP tags in the reply."""
        system, messages = self._claude_messages()
        messages.append({"role": "user", "content": prompt})

        try:
            full_response = ""
            is_first_chunk = True

            with self._anthropic_client.messages.stream(
                model=self.model,
                max_tokens=self._claude_max_tokens,
                system=system,
                messages=messages,
            ) as stream:
                for text in stream.text_stream:
                    if text:
                        if is_first_chunk:
                            if clear_thinking:
                                print('\r' + ' ' * 30 + '\r', end="", flush=True)
                            print("\033[1;34mNeo:\033[0m ", end='', flush=True)
                            is_first_chunk = False
                        print(text, end='', flush=True)
                        full_response += text

            print()
            return self._process_response(full_response)

        except Exception as e:
            print(f"Error while querying Claude: {e}")
            return "An error occurred while querying Claude."

    def _query_claude_raw(self, prompt: str) -> str:
        """Claude follow-up query that skips MCP tag processing.

        Used for sending command output back for summarisation so the model's
        reply cannot trigger another round of command execution.
        """
        system, messages = self._claude_messages()
        messages.append({"role": "user", "content": prompt})

        try:
            full_response = ""
            is_first_chunk = True

            with self._anthropic_client.messages.stream(
                model=self.model,
                max_tokens=self._claude_max_tokens,
                system=system,
                messages=messages,
            ) as stream:
                for text in stream.text_stream:
                    if text:
                        if is_first_chunk:
                            print("\033[1;34mNeo:\033[0m ", end='', flush=True)
                            is_first_chunk = False
                        print(text, end='', flush=True)
                        full_response += text

            print()
            return full_response.strip()

        except Exception as e:
            logging.error("Claude raw query failed: %s", e)
            return ""

    # ── Ollama / LM Studio (OpenAI-compatible) ───────────────────────────────

    def _query_lm_studio(self, prompt, clear_thinking=False):
        """Query the model, stream output to the terminal, then process MCP tags."""
        # Ollama and plain OpenAI-compatible backends don't use LM Studio's
        # instruction wrapping — only apply it when explicitly configured.
        prefix = self.lm_studio_config.get('input_prefix', '')
        suffix = self.lm_studio_config.get('input_suffix', '')
        instruction = f"{prefix} {prompt} {suffix}".strip() if (prefix or suffix) else prompt

        messages = self.history.copy()
        messages.append({"role": "user", "content": instruction})

        try:
            completion = openai.ChatCompletion.create(
                model=self.model,
                messages=messages,
                temperature=0.7,
                stream=self.is_streaming_mode,
            )

            full_response = ""
            is_first_chunk = True

            for chunk in completion:
                if 'choices' in chunk and len(chunk['choices']) > 0:
                    content = chunk['choices'][0]['delta'].get('content', '')
                    if content:
                        if is_first_chunk:
                            if clear_thinking:
                                print('\r' + ' ' * 30 + '\r', end="", flush=True)
                            print("\033[1;34mNeo:\033[0m ", end='', flush=True)
                            is_first_chunk = False

                        print(content, end='', flush=True)
                        full_response += content

            print()
            return self._process_response(full_response)

        except Exception as e:
            print(f"Error while querying LM Studio: {e}")
            return "An error occurred while querying LM Studio."

    def _query_raw(self, prompt: str) -> str:
        """Query the model and return the response text WITHOUT processing MCP tags.

        Used for follow-up messages (sending command output back for summarisation)
        so that the model's summary cannot trigger another round of command
        execution and cause an infinite loop.
        """
        messages = self.history.copy()
        messages.append({"role": "user", "content": prompt})

        try:
            completion = openai.ChatCompletion.create(
                model=self.model,
                messages=messages,
                temperature=0.7,
                stream=self.is_streaming_mode,
            )

            full_response = ""
            is_first_chunk = True

            for chunk in completion:
                if 'choices' in chunk and len(chunk['choices']) > 0:
                    content = chunk['choices'][0]['delta'].get('content', '')
                    if content:
                        if is_first_chunk:
                            print("\033[1;34mNeo:\033[0m ", end='', flush=True)
                            is_first_chunk = False
                        print(content, end='', flush=True)
                        full_response += content

            print()
            return full_response.strip()

        except Exception as e:
            print(f"Error while querying model: {e}")
            return ""

    # ── Main dispatch ─────────────────────────────────────────────────────────

    def query(self, prompt, clear_thinking=False):
        try:
            if not self.context_initialized:
                context = self.initialize_context()
                prompt = f"{context}\n\n{prompt}"

            self.history.append({"role": "user", "content": prompt})
            self._trim_history()

            if self.mode == 'claude':
                response = self._query_claude(prompt, clear_thinking)
            else:
                # Both 'lm_studio' and 'ollama' use the OpenAI-compatible API.
                response = self._query_lm_studio(prompt, clear_thinking)

            if response:
                self.history.append({"role": "assistant", "content": response})
            return response

        except Exception as e:
            import traceback
            print(f"Details: {e}")
            print(traceback.format_exc())

    def _process_response(self, response):
        """
        Process the AI response and handle MCP protocol commands.

        Args:
            response: Text response from the AI

        Returns:
            Processed response with command outputs integrated
        """
        try:
            # Process all MCP protocol tags using the MCP singleton
            mcp_results = mcp.process_response(
                response,
                require_approval=self.require_approval,
                auto_approve=self.auto_approve_all
            )

            # Check if any protocols were executed
            follow_up_messages = []

            for key, result in mcp_results.items():
                # Skip the top-level error key and any non-dict values.
                # Keys are now "terminal", "terminal_1", "terminal_2", … to
                # support multiple commands of the same protocol in one response.
                if key == "error" or not isinstance(result, dict):
                    continue

                # Recover the bare protocol name (strip the "_N" suffix if present)
                protocol = key.split("_")[0]

                # Check if the protocol was executed
                if result.get("executed", False):
                    command = result.get("command", "unknown command")
                    output = result.get("output", "No output")

                    # Create a follow-up message for this protocol.
                    # The explicit instruction is critical: small models tend to
                    # hallucinate values (wrong chip name, wrong version) instead
                    # of quoting the actual output. Wrapping in a fenced block and
                    # adding a "verbatim" instruction significantly reduces this.
                    follow_up_prompt = (
                        f"The `{protocol}` command `{command}` finished.\n"
                        f"The EXACT output is enclosed below. "
                        f"Summarise it using ONLY the values shown — do NOT substitute, "
                        f"guess, or change any names, numbers, or identifiers:\n\n"
                        f"```\n{output.strip()}\n```"
                    )
                    follow_up_messages.append(follow_up_prompt)

            # If we have follow-up messages, send them to the AI for summarisation.
            # Use the *_raw() variant — NOT the main query method — so the model's
            # summary response is never fed back into _process_response(). Without
            # this, any MCP tag in the summary would trigger another command
            # execution, causing an infinite approval/execution loop.
            if follow_up_messages:
                combined_prompt = "\n\n".join(follow_up_messages)
                self.history.append({"role": "user", "content": combined_prompt})

                if self.mode == "claude":
                    summary = self._query_claude_raw(combined_prompt)
                else:
                    summary = self._query_raw(combined_prompt)

                if summary:
                    self.history.append({"role": "assistant", "content": summary})
                return summary

        except Exception as e:
            import traceback
            print(f"\nAn unexpected error occurred while processing the response: {e}")
            print(traceback.format_exc())
            return "An error occurred while processing the command."

        return response.strip()

    def get_conversation_history(self):
        return self.history

    def reset_history(self):
        self.history = []
        self.context_initialized = False
        self.auto_approve_all = False
