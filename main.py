"""
Main entry point for Neo AI terminal assistant.
This file initializes the Neo AI core and UI components.
"""

import os
import sys
import yaml
import argparse
from src.ai_core import NeoAI
from src.terminal_interface import TerminalInterface

try:
    from src.terminal_ui import ImprovedTerminalUI
    IMPROVED_UI_AVAILABLE = True
except ImportError:
    IMPROVED_UI_AVAILABLE = False
    print("Note: Improved UI not available, defaulting to classic interface.")
    print("To install improved UI requirements: pip install prompt_toolkit pygments")

def load_config():
    """Load configuration from config.yaml file."""
    script_dir = os.path.dirname(os.path.realpath(__file__))
    config_path = os.path.join(script_dir, 'config', 'config.yaml')

    if os.path.exists(config_path):
        with open(config_path, "r") as config_file:
            return yaml.safe_load(config_file)
    else:
        print("Error: 'config/config.yaml' is missing.")
        print("Copy config/config.yaml.example to config/config.yaml and fill in your values.")
        sys.exit(1)


def _validate_config(config: dict) -> None:
    """Check that the required keys are present for the configured mode."""
    import os as _os
    mode = config.get('mode', 'lm_studio')
    valid_modes = ('lm_studio', 'ollama', 'claude', 'openai')

    if mode not in valid_modes:
        print(f"Error: Unknown mode '{mode}' in config.yaml. Valid modes: {', '.join(valid_modes)}")
        sys.exit(1)

    if mode == 'openai':
        openai_cfg = config.get('openai_config', {})
        api_key = openai_cfg.get('api_key') or _os.environ.get('OPENAI_API_KEY')
        if not api_key:
            print("Error: An OpenAI API key is required for openai mode.")
            print("  Option 1: set 'openai_config.api_key' in config.yaml")
            print("  Option 2: export OPENAI_API_KEY=sk-...")
            sys.exit(1)
        if not openai_cfg.get('model'):
            print("Error: 'openai_config.model' is required in config.yaml.")
            print("  Example: gpt-4o")
            sys.exit(1)

    elif mode == 'claude':
        claude = config.get('claude_config', {})
        api_key = claude.get('api_key') or _os.environ.get('ANTHROPIC_API_KEY')
        if not api_key:
            print("Error: An Anthropic API key is required for Claude mode.")
            print("  Option 1: set 'claude_config.api_key' in config.yaml")
            print("  Option 2: export ANTHROPIC_API_KEY=sk-ant-...")
            sys.exit(1)
        if not claude.get('model'):
            print("Error: 'claude_config.model' is required in config.yaml.")
            print("  Example: claude-opus-4-5")
            sys.exit(1)

    elif mode == 'ollama':
        ollama = config.get('ollama_config', {})
        if not ollama.get('model'):
            print("Error: 'ollama_config.model' is required in config.yaml.")
            print("Example: llama3.2  —  run 'ollama list' to see available models.")
            sys.exit(1)

    else:  # lm_studio — support both nested and legacy flat-key format
        lm = config.get('lm_studio_config', {})
        api_url = lm.get('api_url') or config.get('api_url')
        if not api_url:
            print("Error: 'lm_studio_config.api_url' is required in config.yaml.")
            sys.exit(1)

def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='Neo AI - Your Linux Terminal Assistant')
    parser.add_argument('--classic', action='store_true', help='Use classic terminal interface')
    parser.add_argument('--version', action='version', version='Neo AI v1.2.0')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    parser.add_argument('prompt', nargs='*', help='One-shot prompt — run once and exit')
    return parser.parse_args()

def _run_oneshot(neo_ai, prompt_text: str) -> None:
    """Execute a single prompt and exit (non-interactive mode)."""
    import threading
    import itertools
    import time

    _FRAMES = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']

    stop = threading.Event()

    def _spin():
        for f in itertools.cycle(_FRAMES):
            if stop.is_set():
                break
            print(f'\r{f} Thinking.', end='', flush=True)
            time.sleep(0.1)
        print('\r' + ' ' * 20 + '\r', end='', flush=True)

    def _stop_spinner():
        stop.set()
        t.join()

    t = threading.Thread(target=_spin, daemon=True)
    t.start()
    neo_ai._pre_output_cb = _stop_spinner
    try:
        neo_ai.query(prompt_text, clear_thinking=True)
    finally:
        stop.set()
        t.join()
        neo_ai._pre_output_cb = None


def main():
    """Main entry point for Neo AI."""
    try:
        # Parse command line arguments
        args = parse_arguments()

        # Load configuration
        config = load_config()

        # Validate required config keys per mode.
        _validate_config(config)

        # Initialize NeoAI
        neo_ai = NeoAI(config)

        # ── One-shot mode ────────────────────────────────────────────────────
        if args.prompt:
            prompt_text = ' '.join(args.prompt)
            _run_oneshot(neo_ai, prompt_text)
            sys.exit(0)

        # ── Interactive mode ─────────────────────────────────────────────────
        # Choose interface based on argument and availability
        if args.classic or not IMPROVED_UI_AVAILABLE:
            # Use classic terminal interface
            terminal = TerminalInterface(neo_ai, config)
        else:
            # Use improved terminal UI
            terminal = ImprovedTerminalUI(neo_ai, config)

        # Run the selected interface
        terminal.run()

    except KeyError as e:
        print(f"Error: Missing configuration key: {e}. Please check your 'config.yaml' file.")
        sys.exit(1)

    except FileNotFoundError:
        print("Error: The 'config.yaml' file is missing.")
        sys.exit(1)

    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()