import readline
from src.ai_core import NeoAI


class TerminalInterface:
    def __init__(self, neo_ai, config):
        self.neo_ai = neo_ai
        self.config = config
        self.commands = ['history', 'exit', 'neo-use', 'neo-verbose', 'neo-tone']

    def completer(self, text, state):
        line = readline.get_line_buffer()
        if line.startswith('neo-use '):
            prefix = line[len('neo-use '):]
            nicks = [f"ollama:{n}" for n in self.neo_ai.list_nicknames("ollama")]
            options = [m for m in list(NeoAI.VALID_MODES) + nicks if m.startswith(prefix)]
        elif line.startswith('neo-tone '):
            prefix = line[len('neo-tone '):]
            options = [t for t in self.neo_ai.list_tones() + ['off'] if t.startswith(prefix)]
        else:
            options = [c for c in self.commands if c.startswith(text)]
        if state < len(options):
            return options[state]
        return None

    def _handle_builtin(self, user_input: str) -> bool:
        """Handle built-in commands. Returns True if consumed, False otherwise."""
        lower = user_input.lower()

        if lower == 'exit':
            print("\033[1;31mGoodbye!\033[0m")
            raise SystemExit(0)

        if lower == 'history':
            print("\033[1;33mDisplaying conversation history\033[0m")
            self.display_history()
            return True

        if lower.startswith('neo-tone'):
            parts = user_input.split()
            name = parts[1].lower() if len(parts) >= 2 else ""
            if not name:
                active = self.neo_ai._active_tone or "none"
                available = ", ".join(self.neo_ai.list_tones())
                print(f"\033[1;33mActive tone: {active}  |  Available: {available}\033[0m")
            else:
                msg = self.neo_ai.set_tone(name)
                print(f"\033[1;34m{msg}\033[0m")
            return True

        if lower.startswith('neo-verbose'):
            parts = user_input.split()
            state = parts[1].lower() if len(parts) >= 2 else ""
            if state not in ("on", "off", ""):
                print("\033[1;33mUsage: neo-verbose [on|off]\033[0m")
                return True
            msg = self.neo_ai.toggle_verbose(state)
            print(f"\033[1;34m{msg}\033[0m")
            return True

        if lower.startswith('neo-use'):
            parts = user_input.split()
            if len(parts) < 2:
                modes = ', '.join(NeoAI.VALID_MODES)
                print(f"\033[1;33mUsage: neo-use <mode> [model]\033[0m")
                print(f"  Modes: {modes}")
                print(f"  Example: neo-use claude")
                print(f"  Example: neo-use ollama mistral:latest")
                return True
            mode = parts[1].lower()
            model = parts[2] if len(parts) >= 3 else ""
            msg = self.neo_ai.switch_mode(mode, model)
            # Wrap with ANSI bold+blue — safe here because we're using plain print,
            # not prompt_toolkit's HTML parser.
            print(f"\033[1;34m{msg}\033[0m")
            return True

        return False

    def run(self):
        readline.parse_and_bind("tab: complete")
        readline.set_completer(self.completer)
        print("\033[1;34mWelcome to Neo Terminal.\033[0m")
        while True:
            try:
                user_input = input("\033[1;32mYou:\033[0m ").strip()
                if not user_input:
                    continue
                if not self._handle_builtin(user_input):
                    self.neo_ai.query(user_input)
            except SystemExit:
                break
            except KeyboardInterrupt:
                print("\n\033[1;31mInterrupted. Goodbye!\033[0m")
                break
            except Exception as e:
                print(f"\033[1;31mAn error occurred: {str(e)}\033[0m")

    def display_history(self):
        for entry in self.neo_ai.get_conversation_history():
            role = "\033[1;32mYou:\033[0m" if entry["role"] == "user" else "\033[1;34mNeo:\033[0m"
            print(f"{role} {entry['content']}")