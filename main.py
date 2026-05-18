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
    mode = config.get('mode', 'lm_studio')
    valid_modes = ('lm_studio', 'ollama', 'digital_ocean')

    if mode not in valid_modes:
        print(f"Error: Unknown mode '{mode}' in config.yaml. Valid modes: {', '.join(valid_modes)}")
        sys.exit(1)

    if mode == 'digital_ocean':
        do = config.get('digital_ocean_config', {})
        missing = [k for k in ('agent_id', 'agent_key', 'agent_endpoint', 'model') if not do.get(k)]
        if missing:
            print(f"Error: Missing digital_ocean_config keys: {', '.join(missing)}")
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
    parser.add_argument('--version', action='version', version='Neo AI v1.1.0')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    return parser.parse_args()

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