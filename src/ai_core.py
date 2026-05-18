import httpx
import jwt
import json
import logging
import os
import time
from src.command_executor import execute_command_in_terminal, execute_command
from src.utils import load_persistent_memory
from src.mcp_protocol import mcp  # Import the MCP singleton
import openai
from src.token_manager import TokenManager
from src.command_executor import wait_for_command_completion
from src.approval_handler import ApprovalHandler

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

        if self.mode == 'digital_ocean':
            self.token_manager = TokenManager(
                agent_id=config['digital_ocean_config']['agent_id'],
                agent_key=config['digital_ocean_config']['agent_key'],
                auth_api_url="https://cluster-api.do-ai.run/v1"
            )
            self.access_token = self.token_manager.get_valid_access_token()
            self.token_timestamp = time.time()
            self.agent_endpoint = config['digital_ocean_config']['agent_endpoint']
            self.model = config['digital_ocean_config']['model']

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

    def _ensure_valid_token(self):
        """Check that the token is still valid and renew it if necessary"""
        if self.mode != 'digital_ocean':
            return

        # Check token every 15 minutes or in case of 401 error
        current_time = time.time()
        token_age = current_time - self.token_timestamp

        if token_age > 900:  # 15 minutes
            try:
                logging.info("Token age > 15 minutes, refreshing...")
                self.access_token = self.token_manager.get_valid_access_token()
                self.token_timestamp = current_time
            except Exception as e:
                logging.error(f"Error refreshing token: {e}")
                # Attempt to completely reset token management
                self.token_manager = TokenManager(
                    agent_id=self.config['digital_ocean_config']['agent_id'],
                    agent_key=self.config['digital_ocean_config']['agent_key'],
                    auth_api_url="https://cluster-api.do-ai.run/v1"
                )
                self.access_token = self.token_manager.get_valid_access_token()
                self.token_timestamp = current_time

    def initialize_context(self):
        context_commands = [
            "pwd",
            "ls"
        ]
        context_data = load_persistent_memory()
        initial_context = "<context>\n"

        for command in context_commands:
            result = execute_command(command)
            initial_context += f"Command: {command}\nResult:\n{result}\n"

        full_context = f"{context_data}\n\n{initial_context}</context>"
        self.context_initialized = True
        return full_context

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

    def _query_digitalocean(self, prompt, clear_thinking=False):
        self._ensure_valid_token()

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": self.history + [{"role": "user", "content": prompt}],
            "stream": True,
        }

        max_retries = 2
        retry_count = 0

        while retry_count < max_retries:
            try:
                with httpx.stream(
                        "POST",
                        f"{self.agent_endpoint}/chat/completions",
                        json=payload,
                        headers=headers,
                        timeout=30.0
                ) as response:
                    response.raise_for_status()

                    is_first_chunk = True
                    assistant_response = ""

                    for line in response.iter_lines():
                        line = line.strip()
                        if line.startswith("data:"):
                            line = line[len("data:"):].strip()

                        if line:
                            try:
                                chunk = json.loads(line)
                                if "choices" in chunk and chunk["choices"]:
                                    content = chunk["choices"][0].get("delta", {}).get("content", "")
                                    if content:
                                        if is_first_chunk:
                                            if clear_thinking:
                                                print('\r' + ' ' * 30 + '\r', end="", flush=True)
                                            print("\033[1;34mNeo:\033[0m ", end="", flush=True)
                                            is_first_chunk = False
                                        print(content, end="", flush=True)
                                        assistant_response += content
                            except json.JSONDecodeError:
                                if line == "[DONE]":
                                    break
                                continue
                    print()

                    if assistant_response.strip():
                        self.history.append({"role": "assistant", "content": assistant_response.strip()})
                        return self._process_response(assistant_response.strip())
                    return ""

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 401 and retry_count < max_retries:
                    retry_count += 1
                    # Force token refresh
                    self.token_manager = TokenManager(
                        agent_id=self.config['digital_ocean_config']['agent_id'],
                        agent_key=self.config['digital_ocean_config']['agent_key'],
                        auth_api_url="https://cluster-api.do-ai.run/v1"
                    )
                    self.access_token = self.token_manager.get_valid_access_token()
                    self.token_timestamp = time.time()

                    # Update header with new token
                    headers["Authorization"] = f"Bearer {self.access_token}"
                    continue
                else:
                    print(f"Details: {e}")
                    break

            except httpx.ReadTimeout:
                retry_count += 1
                if retry_count < max_retries:
                    self.access_token = self.token_manager.get_valid_access_token()
                    self.token_timestamp = time.time()
                    headers["Authorization"] = f"Bearer {self.access_token}"
                    continue
                else:
                    print("Failed after multiple attempts.")
                    break

            except Exception as e:
                import traceback
                print(f"\nDetailed error: {e}")
                print(traceback.format_exc())
                break

        return "Sorry, I couldn't get a response. Please try again."

    def _query_digitalocean_raw(self, prompt: str) -> str:
        """DigitalOcean follow-up query that skips MCP tag processing.

        Mirrors _query_raw() for the DO backend — returns plain text only,
        preventing the same infinite-loop risk as in the Ollama/LM Studio path.
        """
        self._ensure_valid_token()
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": self.history + [{"role": "user", "content": prompt}],
            "stream": True,
        }
        try:
            with httpx.stream(
                "POST",
                f"{self.agent_endpoint}/chat/completions",
                json=payload,
                headers=headers,
                timeout=30.0,
            ) as response:
                response.raise_for_status()
                is_first_chunk = True
                assistant_response = ""
                for line in response.iter_lines():
                    line = line.strip()
                    if line.startswith("data:"):
                        line = line[len("data:"):].strip()
                    if line:
                        try:
                            chunk = json.loads(line)
                            if "choices" in chunk and chunk["choices"]:
                                content = chunk["choices"][0].get("delta", {}).get("content", "")
                                if content:
                                    if is_first_chunk:
                                        print("\033[1;34mNeo:\033[0m ", end="", flush=True)
                                        is_first_chunk = False
                                    print(content, end="", flush=True)
                                    assistant_response += content
                        except json.JSONDecodeError:
                            if line == "[DONE]":
                                break
                print()
                return assistant_response.strip()
        except Exception as e:
            logging.error("DO raw query failed: %s", e)
            return ""

    def query(self, prompt, clear_thinking=False):
        try:
            if not self.context_initialized:
                context = self.initialize_context()
                prompt = f"{context}\n\n{prompt}"

            self.history.append({"role": "user", "content": prompt})
            self._trim_history()

            if self.mode == 'digital_ocean':
                return self._query_digitalocean(prompt, clear_thinking)
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
        This replaces the old system tag processing with the new MCP protocol.

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

            # Log the MCP results for debugging
           # print(f"DEBUG - MCP results: {mcp_results}")

            # Check if any protocols were executed
            follow_up_messages = []

            for protocol, result in mcp_results.items():
                # Skip error key or non-dict results
                if protocol == "error" or not isinstance(result, dict):
                    continue

                # Check if the protocol was executed
                if result.get("executed", False):
                    command = result.get("command", "unknown command")
                    output = result.get("output", "No output")

                    # Create a follow-up message for this protocol
                    follow_up_prompt = f"The {protocol} command '{command}' was executed. Here is the result:\n{output}"
                    follow_up_messages.append(follow_up_prompt)

            # If we have follow-up messages, send them to the AI for summarisation.
            # Use _query_raw() — NOT _query_lm_studio() — so the model's summary
            # response is never fed back into _process_response(). Without this,
            # any MCP tag in the summary would trigger another command execution,
            # causing an infinite approval/execution loop.
            if follow_up_messages:
                combined_prompt = "\n\n".join(follow_up_messages)
                self.history.append({"role": "user", "content": combined_prompt})

                if self.mode == "digital_ocean":
                    summary = self._query_digitalocean_raw(combined_prompt)
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