import logging
import os
import platform
import re
import shutil
from pathlib import Path
from src.command_executor import execute_command_in_terminal, execute_command
from src.utils import load_persistent_memory
from src.mcp_protocol import mcp  # Import the MCP singleton
from src.model_context_loader import ModelContextLoader
import openai
from src.command_executor import wait_for_command_completion
from src.approval_handler import ApprovalHandler
from src.anonymizer import PromptAnonymizer

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
            self._openai_client = None

        elif self.mode == 'openai':
            openai_cfg = config.get('openai_config', {})
            api_key = openai_cfg.get('api_key') or os.environ.get('OPENAI_API_KEY', '')
            self._openai_client = openai.OpenAI(
                base_url=openai_cfg.get('api_url', 'https://api.openai.com/v1'),
                api_key=api_key,
            )
            self.model = openai_cfg.get('model', 'gpt-4o')
            # Reasoning models (o1, o3, gpt-5.x …) only accept temperature=1.
            # Use 1 as the safe default; users can lower it for non-reasoning models.
            self.temperature = openai_cfg.get('temperature', 1)

        elif self.mode == 'ollama':
            ollama_cfg = config.get('ollama_config', {})
            self._openai_client = openai.OpenAI(
                base_url=ollama_cfg.get('api_url', 'http://localhost:11434/v1'),
                api_key=ollama_cfg.get('api_key', 'ollama'),
            )
            self.model = ollama_cfg['model']
            self.temperature = ollama_cfg.get('temperature', 0.7)

        else:
            # lm_studio mode — support both nested (lm_studio_config.*)
            # and the legacy flat-key format (api_url / api_key / model).
            lm_cfg = config.get('lm_studio_config', {})
            self._openai_client = openai.OpenAI(
                base_url=lm_cfg.get('api_url') or config.get('api_url', ''),
                api_key=lm_cfg.get('api_key') or config.get('api_key', 'lm-studio'),
            )
            self.model = lm_cfg.get('model') or config.get('model', '')
            self.temperature = lm_cfg.get('temperature', 0.7)

        self.lm_studio_config = config.get('lm_studio_config', {})
        self.history = []
        self.context_initialized = False
        # Called once (then cleared) before the first terminal output of a query.
        # Used by the UI to stop the thinking spinner before any text appears.
        self._pre_output_cb = None

        # ── Anonymizer ────────────────────────────────────────────────────────
        # Replaces PII / server-critical data with stable placeholders before
        # any text is sent to an external AI backend.  Only active for modes
        # listed in config.anonymize.modes (default: openai, claude).
        anon_cfg = config.get('anonymize', {})
        self._anonymize_enabled: bool = anon_cfg.get('enabled', False)
        self._anonymize_modes: set = set(anon_cfg.get('modes', ['openai', 'claude']))
        self._deanonymize_responses: bool = anon_cfg.get('deanonymize_responses', True)
        self._anonymizer = PromptAnonymizer()
        self._anonymizer.seed(
            username=os.environ.get('USER', os.environ.get('USERNAME', '')),
            hostname=platform.node(),
        )
        # Verbose mode: when False (default) MCP tags are stripped from the
        # displayed response so the terminal stays clean.  When True every
        # raw token the model generates is shown as-is.
        self.verbose: bool = False
        # Maximum number of messages kept in history to prevent unbounded memory
        # growth and token-limit breaches. Keeps the last N message pairs.
        self._max_history_messages: int = config.get('max_history_messages', 40)

        # Active tone — name and content loaded from config/tones/<name>.md.
        # Empty string means no tone injection (model uses its default style).
        self._active_tone: str = ""
        self._tone_content: str = ""

        # Directory that holds tone .md files.
        self._tones_dir: Path = (
            Path(__file__).parent.parent / "config" / "tones"
        )

        # Path to the live config file — used by set_tone() to persist the
        # active tone across sessions.
        self._config_path: Path = (
            Path(__file__).parent.parent / "config" / "config.yaml"
        )

        # Restore persisted tone from config (if any).
        _saved_tone = config.get('tone', '')
        if _saved_tone:
            self.set_tone(_saved_tone)

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

        After loading the base prompt, any matching model-context plugins from
        config/model_contexts/ are appended automatically.
        """
        import os as _os

        script_dir = _os.path.dirname(_os.path.realpath(__file__))
        project_root = _os.path.join(script_dir, "..")

        candidates = [
            config.get("system_prompt_path"),
            _os.path.join(project_root, "config", "PrePromt.md"),
        ]

        base_text = None
        for path in candidates:
            if path and _os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        base_text = f.read().strip()
                    logging.info("System prompt loaded from: %s", path)
                    break
                except OSError as e:
                    logging.warning("Could not read system prompt from %s: %s", path, e)

        if not base_text:
            logging.warning(
                "config/PrePromt.md not found — using minimal fallback system prompt. "
                "The model may not generate MCP tags correctly."
            )
            base_text = (
                "You are Neo, a Linux terminal AI assistant. "
                "Use MCP protocol tags to execute commands: "
                "<mcp:terminal>command</mcp:terminal>. "
                "Always use these tags when the user asks you to run something."
            )

        # Store the base prompt so switch_mode() can rebuild without it.
        self._base_system_prompt: str = base_text
        self.history = [{"role": "system", "content": self._build_system_prompt()}]

    def _build_system_prompt(self) -> str:
        """Combine the base PrePromt, model-context plugins, and active tone.

        Called once at startup and again whenever mode, model, or tone changes.
        Layer order:
          1. PrePromt.md         — core identity and MCP rules
          2. model_contexts/     — backend/model-specific behaviour
          3. tones/<name>.md     — active tone override (if any)
        """
        parts = [self._base_system_prompt]

        extra = ModelContextLoader.load(self.mode, self.model)
        if extra:
            parts.append(extra)

        if self._tone_content:
            parts.append(f"## Active tone\n\n{self._tone_content}")

        return "\n\n---\n\n".join(parts)

    # ── Verbose toggle ────────────────────────────────────────────────────────

    @staticmethod
    def _strip_mcp_tags(text: str) -> str:
        """Replace/remove <mcp:…>…</mcp:…> blocks for clean terminal display.

        terminal tags: replaced with a fenced bash code block so the user
          always sees the command, even if they decline execution or the
          model used a tag where plain text was expected.
        All other tags (files, analyze, …): removed silently.
        """
        # Replace terminal tags with a visible code block
        cleaned = re.sub(
            r'[ \t]*<mcp:terminal>(.*?)</mcp:terminal>[ \t]*',
            lambda m: f'\n```bash\n{m.group(1).strip()}\n```\n',
            text,
            flags=re.DOTALL,
        )
        # Remove all other MCP tags silently
        cleaned = re.sub(r'[ \t]*<mcp:\w+>.*?</mcp:\w+>[ \t]*', '', cleaned, flags=re.DOTALL)
        # Collapse runs of 3+ newlines down to two (preserve paragraph breaks)
        cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
        return cleaned.strip()

    def toggle_verbose(self, state: str = "") -> str:
        """Toggle or explicitly set verbose mode.

        Args:
            state: "on" / "off" to set explicitly, or "" to toggle.

        Returns:
            A human-readable status string.
        """
        if state == "on":
            self.verbose = True
        elif state == "off":
            self.verbose = False
        else:
            self.verbose = not self.verbose

        status = "on" if self.verbose else "off"
        detail = (
            "Raw model output shown (including MCP tags)."
            if self.verbose
            else "MCP tags hidden — clean output mode."
        )
        return f"Verbose {status}. {detail}"

    # ── Tone ──────────────────────────────────────────────────────────────────

    def list_tones(self) -> list:
        """Return available tone names (stems of .md files in config/tones/)."""
        if not self._tones_dir.is_dir():
            return []
        return sorted(p.stem for p in self._tones_dir.glob("*.md"))

    def set_tone(self, name: str = "") -> str:
        """Load and activate a tone, or clear the active tone.

        Args:
            name: Tone name (filename stem from config/tones/).
                  Pass "" or "off" to clear the active tone.

        Returns:
            A human-readable status string (plain text, no ANSI codes).
        """
        if not name or name.lower() == "off":
            self._active_tone = ""
            self._tone_content = ""
            self._refresh_system_prompt()
            self._persist_tone("")
            return "Tone cleared — using default model style."

        tone_file = self._tones_dir / f"{name}.md"
        if not tone_file.exists():
            available = ", ".join(self.list_tones()) or "none"
            return f"Unknown tone '{name}'. Available: {available}"

        try:
            self._tone_content = tone_file.read_text(encoding="utf-8").strip()
            self._active_tone = name
            self._refresh_system_prompt()
            self._persist_tone(name)
            return f"Tone set to '{name}'."
        except OSError as exc:
            return f"Could not load tone '{name}': {exc}"

    def _persist_tone(self, name: str) -> None:
        """Write the active tone name to config.yaml so it survives restarts."""
        if not self._config_path.exists():
            return
        try:
            raw = self._config_path.read_text(encoding="utf-8")
            import re as _re
            if _re.search(r'^tone\s*:', raw, flags=_re.MULTILINE):
                raw = _re.sub(
                    r'^(tone\s*:).*$',
                    f'tone: "{name}"',
                    raw,
                    flags=_re.MULTILINE,
                )
            else:
                raw = raw.rstrip('\n') + f'\ntone: "{name}"\n'
            self._config_path.write_text(raw, encoding="utf-8")
        except OSError as exc:
            logging.warning("Could not persist tone to config.yaml: %s", exc)

    def _persist_mode(self, mode: str, model: str) -> None:
        """Write the active mode and model back to config.yaml.

        Updates the top-level 'mode:' key and the model entry inside the
        relevant backend config block (ollama_config.model, etc.) so that
        the chosen backend survives restarts.
        """
        if not self._config_path.exists():
            return
        try:
            raw = self._config_path.read_text(encoding="utf-8")
            import re as _re

            # ── top-level mode: ──────────────────────────────────────────────
            if _re.search(r'^mode\s*:', raw, flags=_re.MULTILINE):
                raw = _re.sub(
                    r'^(mode\s*:).*$',
                    f'mode: "{mode}"',
                    raw,
                    flags=_re.MULTILINE,
                )
            else:
                raw = raw.rstrip('\n') + f'\nmode: "{mode}"\n'

            # ── backend-specific model key ───────────────────────────────────
            # Each backend lives under a YAML block like:
            #   ollama_config:
            #     model: "qwen3-coder"
            # We update only the first `model:` line inside that block.
            cfg_block = {
                'ollama':    'ollama_config',
                'openai':    'openai_config',
                'claude':    'claude_config',
                'lm_studio': 'lm_studio_config',
            }.get(mode)

            if cfg_block and model:
                # Match the block header, then find the first `model:` inside.
                pattern = _re.compile(
                    rf'(^{_re.escape(cfg_block)}\s*:.*?)(^\s+model\s*:)[^\n]*',
                    _re.MULTILINE | _re.DOTALL,
                )
                def _replace_model(m):
                    indent = _re.match(r'(\s+)', m.group(2)).group(1)
                    return m.group(1) + f'{indent}model: "{model}"'
                raw = pattern.sub(_replace_model, raw, count=1)

            self._config_path.write_text(raw, encoding="utf-8")
        except OSError as exc:
            logging.warning("Could not persist mode to config.yaml: %s", exc)

    def _fire_pre_output_cb(self) -> None:
        """Call and clear _pre_output_cb exactly once before any terminal output."""
        if self._pre_output_cb:
            self._pre_output_cb()
            self._pre_output_cb = None

    # ── Anonymizer helpers ────────────────────────────────────────────────────

    def _should_anonymize(self) -> bool:
        """True when anonymization is enabled and the current mode is external."""
        return self._anonymize_enabled and self.mode in self._anonymize_modes

    def _anon_messages(self, messages: list) -> list:
        """Return a copy of *messages* with all content anonymised (if active)."""
        if not self._should_anonymize():
            return messages
        return [
            {**msg, 'content': self._anonymizer.anonymize(msg.get('content') or '')}
            for msg in messages
        ]

    def _anon(self, text: str) -> str:
        """Anonymise a single string (if active)."""
        if not self._should_anonymize():
            return text
        return self._anonymizer.anonymize(text)

    def _deanon(self, text: str) -> str:
        """De-anonymise a response string (if active and configured)."""
        if not self._should_anonymize() or not self._deanonymize_responses:
            return text
        return self._anonymizer.deanonymize(text)

    def toggle_anonymize(self, state: str = '') -> str:
        """Toggle or explicitly set anonymization mode.

        Args:
            state: ``"on"`` / ``"off"`` to set explicitly, ``""`` to toggle,
                   ``"status"`` to report current state without changing it.

        Returns:
            A human-readable status string.
        """
        if state == 'status':
            enabled = 'on' if self._anonymize_enabled else 'off'
            modes   = ', '.join(sorted(self._anonymize_modes))
            count   = self._anonymizer.mapping_count
            header  = (
                f"Anonymization: {enabled}  |  Active for: {modes}  |  "
                f"Mappings this session: {count}"
            )
            detail = self._anonymizer.summary()
            return f"{header}\n{detail}"
        if state == 'on':
            self._anonymize_enabled = True
        elif state == 'off':
            self._anonymize_enabled = False
        else:
            self._anonymize_enabled = not self._anonymize_enabled

        enabled = 'on' if self._anonymize_enabled else 'off'
        modes   = ', '.join(sorted(self._anonymize_modes))
        return f"Anonymization {enabled}. Active for: {modes}."

    def _refresh_system_prompt(self) -> None:
        """Rebuild and update the system prompt entry in history."""
        if self.history and self.history[0]["role"] == "system":
            self.history[0]["content"] = self._build_system_prompt()
            logging.debug(
                "System prompt refreshed (mode=%s model=%s tone=%s)",
                self.mode, self.model, self._active_tone or "none",
            )

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

    def _print_streamed(
        self,
        full_response: str,
        clear_thinking: bool = False,
        strip_tags: bool = True,
    ) -> None:
        """Print a fully-collected model response to the terminal.

        In verbose mode the raw text (including MCP tags) is shown.
        In clean mode MCP tags are stripped before display.
        """
        self._fire_pre_output_cb()
        if clear_thinking:
            print('\r' + ' ' * 30 + '\r', end="", flush=True)

        display = full_response if self.verbose else self._strip_mcp_tags(full_response)
        if display:
            print("\033[1;34mNeo:\033[0m ", end='', flush=True)
            print(display)

    def _query_claude(self, prompt: str, clear_thinking: bool = False) -> str:
        """Stream a Claude response and process MCP tags in the reply."""
        system, messages = self._claude_messages()
        messages.append({"role": "user", "content": prompt})
        system   = self._anon(system)
        messages = self._anon_messages(messages)

        try:
            full_response = ""

            with self._anthropic_client.messages.stream(
                model=self.model,
                max_tokens=self._claude_max_tokens,
                system=system,
                messages=messages,
            ) as stream:
                if self.verbose:
                    # Stream tokens in real-time (placeholders visible — verbose is debug mode)
                    is_first_chunk = True
                    for text in stream.text_stream:
                        if text:
                            if is_first_chunk:
                                self._fire_pre_output_cb()
                                if clear_thinking:
                                    print('\r' + ' ' * 30 + '\r', end="", flush=True)
                                print("\033[1;34mNeo:\033[0m ", end='', flush=True)
                                is_first_chunk = False
                            print(text, end='', flush=True)
                            full_response += text
                    print()
                    full_response = self._deanon(full_response)
                else:
                    # Collect silently, deanonymize, then print clean
                    for text in stream.text_stream:
                        full_response += text
                    full_response = self._deanon(full_response)
                    self._print_streamed(full_response, clear_thinking=clear_thinking)

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
        system   = self._anon(system)
        messages = self._anon_messages(messages)

        try:
            full_response = ""

            with self._anthropic_client.messages.stream(
                model=self.model,
                max_tokens=self._claude_max_tokens,
                system=system,
                messages=messages,
            ) as stream:
                if self.verbose:
                    is_first_chunk = True
                    for text in stream.text_stream:
                        if text:
                            if is_first_chunk:
                                print("\033[1;34mNeo:\033[0m ", end='', flush=True)
                                is_first_chunk = False
                            print(text, end='', flush=True)
                            full_response += text
                    print()
                    full_response = self._deanon(full_response)
                else:
                    for text in stream.text_stream:
                        full_response += text
                    full_response = self._deanon(full_response)
                    self._print_streamed(full_response)

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
        messages = self._anon_messages(messages)

        try:
            completion = self._openai_client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
                stream=self.is_streaming_mode,
            )

            full_response = ""

            if self.verbose:
                is_first_chunk = True
                for chunk in completion:
                    content = chunk.choices[0].delta.content or '' if chunk.choices else ''
                    if content:
                        if is_first_chunk:
                            self._fire_pre_output_cb()
                            if clear_thinking:
                                print('\r' + ' ' * 30 + '\r', end="", flush=True)
                            print("\033[1;34mNeo:\033[0m ", end='', flush=True)
                            is_first_chunk = False
                        print(content, end='', flush=True)
                        full_response += content
                print()
                full_response = self._deanon(full_response)
            else:
                for chunk in completion:
                    content = chunk.choices[0].delta.content or '' if chunk.choices else ''
                    full_response += content
                full_response = self._deanon(full_response)
                self._print_streamed(full_response, clear_thinking=clear_thinking)

            return self._process_response(full_response)

        except Exception as e:
            print(f"Error while querying {self.mode} ({self.model}): {e}")
            return f"An error occurred while querying {self.mode}."

    def _query_raw(self, prompt: str) -> str:
        """Query the model and return the response text WITHOUT processing MCP tags.

        Used for follow-up messages (sending command output back for summarisation)
        so that the model's summary cannot trigger another round of command
        execution and cause an infinite loop.
        """
        messages = self.history.copy()
        messages.append({"role": "user", "content": prompt})
        messages = self._anon_messages(messages)

        try:
            completion = self._openai_client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
                stream=self.is_streaming_mode,
            )

            full_response = ""

            if self.verbose:
                is_first_chunk = True
                for chunk in completion:
                    content = chunk.choices[0].delta.content or '' if chunk.choices else ''
                    if content:
                        if is_first_chunk:
                            print("\033[1;34mNeo:\033[0m ", end='', flush=True)
                            is_first_chunk = False
                        print(content, end='', flush=True)
                        full_response += content
                print()
                full_response = self._deanon(full_response)
            else:
                for chunk in completion:
                    content = chunk.choices[0].delta.content or '' if chunk.choices else ''
                    full_response += content
                full_response = self._deanon(full_response)
                self._print_streamed(full_response)

            return full_response.strip()

        except Exception as e:
            print(f"Error while querying {self.mode} ({self.model}): {e}")
            return ""

    # ── Runtime mode switching ────────────────────────────────────────────────

    VALID_MODES = ('ollama', 'lm_studio', 'openai', 'claude')

    def _resolve_nickname(self, base_mode: str, nickname: str) -> tuple:
        """Resolve a model nickname to its full name.

        Looks up *nickname* (case-insensitive) in the ``models`` dict of the
        matching mode config block.  Returns ``(resolved_model, error_str)``
        where *error_str* is ``None`` on success or a human-readable message
        listing available nicknames when the lookup fails.

        Example config::

            ollama_config:
              models:
                gemma:    gemma4
                qwencode: qwen3-coder
        """
        cfg_key = f"{base_mode}_config"
        models_map: dict = self.config.get(cfg_key, {}).get("models", {})

        if not models_map:
            return "", (
                f"No model nicknames configured for '{base_mode}'. "
                f"Add a 'models:' block under '{cfg_key}' in config.yaml."
            )

        # Case-insensitive lookup
        needle = nickname.lower()
        for alias, full_name in models_map.items():
            if alias.lower() == needle:
                return str(full_name), None

        available = ", ".join(models_map.keys())
        return "", (
            f"Unknown nickname '{nickname}' for mode '{base_mode}'. "
            f"Available: {available}"
        )

    def list_nicknames(self, base_mode: str) -> dict:
        """Return the nickname → model mapping for *base_mode* (for UI completion)."""
        cfg_key = f"{base_mode}_config"
        return dict(self.config.get(cfg_key, {}).get("models", {}))

    def switch_mode(self, mode: str, model: str = "") -> str:
        """Switch backend/model at runtime without restarting.

        Conversation history is preserved so the user can continue the
        session after switching. Returns a human-readable status string.

        Args:
            mode:  One of 'ollama', 'lm_studio', 'openai', 'claude'.
            model: Optional model override (e.g. 'gpt-4o', 'mistral:latest').
                   When omitted the value from config.yaml is used.
        """
        # Handle "mode:nickname" shorthand (e.g. "ollama:gemma")
        if ":" in mode:
            base_mode, nickname = mode.split(":", 1)
            base_mode = base_mode.strip().lower()
            nickname = nickname.strip()
            if base_mode not in self.VALID_MODES:
                return (
                    f"Unknown mode '{base_mode}'. "
                    f"Valid modes: {', '.join(self.VALID_MODES)}"
                )
            resolved, err = self._resolve_nickname(base_mode, nickname)
            if err:
                return err
            # Delegate to the normal path with the resolved model name
            return self.switch_mode(base_mode, resolved)

        if mode not in self.VALID_MODES:
            return (
                f"Unknown mode '{mode}'. "
                f"Valid modes: {', '.join(self.VALID_MODES)}"
            )

        try:
            if mode == 'claude':
                if not _ANTHROPIC_AVAILABLE:
                    return (
                        "The 'anthropic' package is not installed. "
                        "Run: pip install anthropic"
                    )
                claude_cfg = self.config.get('claude_config', {})
                api_key = (
                    claude_cfg.get('api_key')
                    or os.environ.get('ANTHROPIC_API_KEY', '')
                )
                if not api_key:
                    return (
                        "No Anthropic API key found. "
                        "Set claude_config.api_key in config.yaml "
                        "or export ANTHROPIC_API_KEY."
                    )
                self._anthropic_client = _anthropic_sdk.Anthropic(api_key=api_key)
                self._claude_max_tokens = claude_cfg.get('max_tokens', 4096)
                self.model = model or claude_cfg.get('model', 'claude-opus-4-5')

            elif mode == 'openai':
                openai_cfg = self.config.get('openai_config', {})
                api_key = (
                    openai_cfg.get('api_key')
                    or os.environ.get('OPENAI_API_KEY', '')
                )
                if not api_key:
                    return (
                        "No OpenAI API key found. "
                        "Set openai_config.api_key in config.yaml "
                        "or export OPENAI_API_KEY."
                    )
                self._openai_client = openai.OpenAI(
                    base_url=openai_cfg.get('api_url', 'https://api.openai.com/v1'),
                    api_key=api_key,
                )
                self.model = model or openai_cfg.get('model', 'gpt-4o')
                self.temperature = openai_cfg.get('temperature', 1)

            elif mode == 'ollama':
                ollama_cfg = self.config.get('ollama_config', {})
                self._openai_client = openai.OpenAI(
                    base_url=ollama_cfg.get('api_url', 'http://localhost:11434/v1'),
                    api_key=ollama_cfg.get('api_key', 'ollama'),
                )
                self.model = model or ollama_cfg.get('model', '')
                self.temperature = ollama_cfg.get('temperature', 0.7)
                if not self.model:
                    return (
                        "Specify a model name, e.g.: "
                        "neo-use ollama mistral:latest"
                    )

            else:  # lm_studio
                lm_cfg = self.config.get('lm_studio_config', {})
                self._openai_client = openai.OpenAI(
                    base_url=lm_cfg.get('api_url') or self.config.get('api_url', ''),
                    api_key=lm_cfg.get('api_key') or self.config.get('api_key', 'lm-studio'),
                )
                self.model = (
                    model
                    or lm_cfg.get('model')
                    or self.config.get('model', '')
                )
                self.temperature = lm_cfg.get('temperature', 0.7)

            self.mode = mode
            logging.info("Switched to mode=%s model=%s", self.mode, self.model)
            self._refresh_system_prompt()
            self._persist_mode(mode, self.model)
            return f"Switched to {mode} — model: {self.model}"

        except Exception as e:
            logging.error("switch_mode failed: %s", e)
            return f"Failed to switch mode: {e}"

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
            self._fire_pre_output_cb()
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
                    output = result.get("output", "")

                    # When the command produced no output (e.g. rm, mv, mkdir)
                    # there is nothing for the model to summarise.  Asking it
                    # to do so just makes it echo the command back ("completed
                    # with no output") which is redundant noise.  Print a
                    # simple "Done." and skip the model round-trip entirely.
                    if not output.strip():
                        print("\033[1;34mNeo:\033[0m Done.")
                        continue

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

    # ── Runbook support ───────────────────────────────────────────────────────

    def _query_oneshot(self, prompt: str) -> str:
        """Query the model with a minimal analysis-only system prompt + *prompt*.

        Intentionally does NOT include the main PrePromt.md system prompt
        (which instructs the model to use MCP tags for command execution).
        Without that instruction the model just analyses text and returns
        findings — which is exactly what runbook section analysis needs.

        No conversation history is included and the result is NOT added to
        self.history, keeping each section query fully independent.
        """
        # Minimal system prompt — analysis only, no tool/command execution.
        analysis_system = (
            "You are a server health-check analyst. "
            "Analyse the command output provided and report findings concisely. "
            "Do NOT execute any commands or use any tool calls. "
            "Just read the text and report what you find."
        )

        anon_prompt = self._anon(prompt)

        try:
            if self.mode == "claude":
                full_response = ""
                with self._anthropic_client.messages.stream(
                    model=self.model,
                    max_tokens=self._claude_max_tokens,
                    system=analysis_system,
                    messages=[{"role": "user", "content": anon_prompt}],
                ) as stream:
                    for text in stream.text_stream:
                        full_response += text
                return self._deanon(full_response).strip()
            else:
                messages = [
                    {"role": "system", "content": analysis_system},
                    {"role": "user", "content": anon_prompt},
                ]
                completion = self._openai_client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=self.temperature,
                    stream=False,
                )
                return self._deanon(completion.choices[0].message.content).strip()
        except Exception as e:
            logging.error("_query_oneshot failed: %s", e)
            print(f"\033[33m[runbook] AI query failed: {e}\033[0m", flush=True)
            return ""

    def run_runbook(
        self,
        path_str: str,
        tag_filter: str = "",
        section_filter: str = "",
        show_raw: bool = False,
        progress_cb=None,
    ) -> str:
        """Parse and execute a runbook, then analyse output section by section.

        Each major section (Disk Health, Performance, Docker, …) is analysed
        independently right after its commands finish — keeping each AI query
        small enough for local models. A final summary is produced from all
        section analyses.

        Raw command output is always saved to a log file so findings can be
        verified against actual data. Pass show_raw=True to also print it to
        the terminal before each section's AI analysis.

        All commands execute without approval prompts (runbooks are trusted).

        Args:
            path_str:       Path or stem name of the runbook file.
            tag_filter:     Optional tag filter (e.g. "DAILY").
            section_filter: Optional section number prefix (e.g. "3").
            show_raw:       Print raw command output to terminal before analysis.
            progress_cb:    Optional callable(message: str) for live progress.

        Returns:
            The final summary as a string.
        """
        import os as _os
        from pathlib import Path as _Path
        from datetime import datetime as _dt
        from src.runbook_runner import RunbookRunner

        runner = RunbookRunner(
            command_timeout=self.config.get('command_timeout', 60)
        )

        if not progress_cb:
            def progress_cb(msg):
                print(f"\033[90m{msg}\033[0m", flush=True)

        # Always write raw output to a log file for verification.
        uid = _os.getuid() if hasattr(_os, 'getuid') else 0
        ts  = _dt.now().strftime('%Y%m%d_%H%M%S')
        rb_stem = _Path(path_str).stem
        log_path = _Path(f"/tmp/neo_{uid}") / f"runbook_{rb_stem}_{ts}.log"

        try:
            runbook, section_groups = runner.run_sectioned(
                path_str,
                tag_filter=tag_filter or None,
                section_filter=section_filter or None,
                progress_cb=progress_cb,
                log_path=log_path,
            )
        except FileNotFoundError as exc:
            return str(exc)

        print(f"\033[90mRaw output saved to: {log_path}\033[0m\n", flush=True)

        if not section_groups:
            print("\033[1;34mNeo:\033[0m No sections matched the given filters.")
            return ""

        # ── Per-section analysis ──────────────────────────────────────────────
        section_analyses = []

        for group in section_groups:
            title  = group['title']
            output = group['output']

            if show_raw:
                print(f"\033[90m{'─' * 60}\033[0m")
                print(f"\033[90mRAW OUTPUT — {title}\033[0m")
                print(f"\033[90m{'─' * 60}\033[0m")
                print(output)
                print()

            print(f"\n\033[90mAnalysing: {title}…\033[0m", flush=True)

            section_prompt = (
                f"Analyse the '{title}' section of the '{runbook.title}' "
                f"health-check runbook.\n\n"
                f"RULES — follow strictly:\n"
                f"- Base your findings ONLY on the exact text in the command "
                f"output below. Do NOT infer, guess, or add information not "
                f"present in the output.\n"
                f"- When you flag an issue, quote the EXACT value from the "
                f"output (e.g. '71% used', 'await 10.54 ms').\n"
                f"- If the output is empty or shows '(no output)', report "
                f"UNKNOWN — do not invent findings.\n"
                f"- Use WARNING / CRITICAL labels only when the output clearly "
                f"exceeds the stated thresholds.\n\n"
                f"Command output:\n{output}"
            )

            analysis = self._query_oneshot(section_prompt)

            if analysis:
                section_analyses.append(f"## {title}\n{analysis}")
                print(f"\033[1;34mNeo [{title}]:\033[0m {analysis}\n")
            else:
                section_analyses.append(f"## {title}\n(no analysis returned)")

        # ── Final summary ─────────────────────────────────────────────────────
        print("\033[90mCreating final summary…\033[0m\n", flush=True)

        combined_analyses = "\n\n".join(section_analyses)

        # If a "System Identity" section exists, inject its raw command output
        # directly into the summary prompt so the AI can reliably populate
        # header fields (hostname, OS, date) without hunting through analysis text.
        identity_raw = ""
        for group in section_groups:
            if "identity" in group["title"].lower():
                identity_raw = group["output"]
                break

        if runbook.output_format:
            identity_block = (
                f"SYSTEM IDENTITY (raw command output — use these exact values "
                f"for Hostname / OS / Date fields in the report header):\n"
                f"{identity_raw}\n\n"
            ) if identity_raw else ""
            summary_prompt = (
                f"You have analysed each section of the '{runbook.title}' runbook.\n"
                f"{identity_block}"
                f"Here are the per-section findings:\n\n"
                f"{combined_analyses}\n\n"
                f"Now produce the final consolidated report using exactly "
                f"this structure:\n\n"
                f"{runbook.output_format}"
            )
        else:
            summary_prompt = (
                f"You have analysed each section of the '{runbook.title}' runbook.\n"
                f"Per-section findings:\n\n{combined_analyses}\n\n"
                f"Produce a concise executive summary:\n"
                f"- Overall status (OK / WARNING / CRITICAL)\n"
                f"- Top issues requiring attention\n"
                f"- Recommended actions"
            )

        if runbook.agent_instructions:
            summary_prompt = (
                f"Instructions: {runbook.agent_instructions}\n\n"
                + summary_prompt
            )

        # Use _query_oneshot() — the same minimal system prompt used for
        # section analysis — so the model stays in "analyst" mode and does
        # not try to execute MCP commands or follow history from PrePromt.md.
        summary = self._query_oneshot(summary_prompt)

        # Print and store in history so the user can ask follow-up questions.
        if summary:
            print(f"\033[1;34mNeo:\033[0m {summary}")
            self.history.append({"role": "user",      "content": summary_prompt})
            self.history.append({"role": "assistant", "content": summary})
            self._trim_history()
        else:
            print("\033[1;34mNeo:\033[0m (no summary returned)")

        # Save the full AI report (per-section analyses + summary) alongside
        # the raw log so findings can be reviewed later without re-running.
        report_path = log_path.parent / f"runbook_{rb_stem}_{ts}_report.md"
        try:
            report_lines = [
                f"# Runbook Report: {runbook.title}",
                f"Generated: {_dt.now().strftime('%Y-%m-%d %H:%M:%S')}",
                f"Raw log: {log_path}",
                "",
                "---",
                "",
                "## Per-section Analysis",
                "",
                combined_analyses,
                "",
                "---",
                "",
                "## Executive Summary",
                "",
                summary or "(no summary returned)",
            ]
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text("\n".join(report_lines), encoding="utf-8")
            print(f"\033[90mAI report saved to:  {report_path}\033[0m\n", flush=True)
        except OSError as exc:
            logging.warning("Could not save runbook report: %s", exc)

        return summary or ""
