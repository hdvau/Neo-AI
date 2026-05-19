"""
Persistent terminal executor for Neo AI.
Uses a single reusable terminal window for all commands.
"""

import platform
import subprocess
import os
import time
import logging
import tempfile
import shlex
import signal
import atexit
from prompt_toolkit import print_formatted_text, HTML

_IS_MACOS = platform.system() == "Darwin"

class PersistentTerminalExecutor:
    """Execute commands using a single persistent terminal window."""

    def __init__(self):
        """Initialize the persistent terminal executor."""
        # Use a user-specific subdirectory so multiple users on the same host
        # never collide on shared files (log, lock, fifo, pid, output).
        # /tmp/neo_<uid>/ is owned and readable only by that user.
        _base_tmp = tempfile.gettempdir()
        _uid = os.getuid() if hasattr(os, 'getuid') else 0
        self.temp_dir = os.path.join(_base_tmp, f"neo_{_uid}")
        os.makedirs(self.temp_dir, mode=0o700, exist_ok=True)
        self.output_file = os.path.join(self.temp_dir, "neo_command_output.txt")
        self.lock_file = os.path.join(self.temp_dir, "neo_command_lock")
        self.pid_file = os.path.join(self.temp_dir, "neo_terminal_pid.txt")
        self.fifo_path = os.path.join(self.temp_dir, "neo_terminal_fifo")
        self.terminal_type = self._detect_terminal_type()
        self.terminal_process = None
        self.terminal_initialized = False

        # Set up logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            filename=os.path.join(self.temp_dir, "neo_command.log"),
            filemode='a'
        )

        # Create FIFO with owner-only permissions (0o600) so other users on
        # the same host cannot inject commands through it.
        if not os.path.exists(self.fifo_path):
            try:
                os.mkfifo(self.fifo_path, 0o600)
            except Exception as e:
                logging.error(f"Failed to create FIFO: {e}")

        # Check if there's an existing terminal running
        if self._is_terminal_running():
            self.terminal_initialized = True
            logging.info("Found an existing Neo terminal session, will reuse it.")

        # Register cleanup on exit
        atexit.register(self._cleanup)

    def _detect_terminal_type(self) -> str:
        """Detect the available terminal emulator for the current platform."""
        if _IS_MACOS:
            # Prefer iTerm2 when installed; fall back to the built-in Terminal.app.
            if os.path.exists("/Applications/iTerm.app") or os.path.exists(
                os.path.expanduser("~/Applications/iTerm.app")
            ):
                return "iterm2"
            return "terminal_app"

        # Linux — probe common emulators in preference order.
        linux_terminals = [
            ("gnome-terminal", "gnome-terminal --"),
            ("konsole", "konsole -e"),
            ("xfce4-terminal", "xfce4-terminal -e"),
            ("mate-terminal", "mate-terminal -e"),
            ("terminator", "terminator -e"),
            ("tilix", "tilix -e"),
            ("kitty", "kitty -e"),
            ("alacritty", "alacritty -e"),
            ("x-terminal-emulator", "x-terminal-emulator -e"),
        ]
        for terminal_cmd, launch_cmd in linux_terminals:
            try:
                result = subprocess.run(
                    ["which", terminal_cmd],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
                if result.returncode == 0:
                    return launch_cmd
            except Exception:
                continue

        return "x-terminal-emulator -e"

    def _is_terminal_running(self) -> bool:
        """Check if our persistent terminal script process is still alive."""
        if not os.path.exists(self.pid_file):
            return False

        try:
            with open(self.pid_file, "r") as f:
                pid = int(f.read().strip())
        except (OSError, ValueError):
            return False

        # os.kill(pid, 0) raises OSError if the process no longer exists.
        # This works on both Linux and macOS.
        try:
            os.kill(pid, 0)
        except OSError:
            return False

        # Verify the running process is actually our terminal script (not a
        # recycled PID). Use platform-appropriate method.
        try:
            if _IS_MACOS:
                result = subprocess.run(
                    ["ps", "-p", str(pid), "-o", "command="],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
                )
                cmdline = result.stdout.decode(errors="replace")
            else:
                with open(f"/proc/{pid}/cmdline", "rb") as f:
                    cmdline = f.read().decode(errors="replace")

            return "neo_terminal_script" in cmdline
        except (OSError, FileNotFoundError):
            return False

    def _initialize_terminal(self):
        """Initialize the persistent terminal if not already running."""
        if self._is_terminal_running():
            logging.info("Persistent terminal is already running.")
            return

        try:
            # Write the terminal script with owner-only permissions (0o700).
            # Using bash -c instead of eval to avoid double-evaluation of the
            # command string (eval can re-expand $(...) and backtick sequences).
            script_path = os.path.join(self.temp_dir, "neo_terminal_script.sh")
            script_content = '''#!/bin/bash
echo $$ > {pid_file}
echo "Neo AI Terminal - DO NOT CLOSE THIS WINDOW"
echo "This terminal will be used for all Neo AI commands."
echo "---------------------------------------------------"

process_command() {{
    command=$(cat {fifo_path})
    rm -f {lock_file}

    echo ""
    echo "---------------------------------------------------"
    echo "Executing: $command"
    echo "---------------------------------------------------"

    bash -c "$command" 2>&1 | tee {output_file}
    EXIT_CODE=${{PIPESTATUS[0]}}

    echo "" >> {output_file}
    echo "---------------------------------------------------" >> {output_file}
    echo "Command completed with exit code: $EXIT_CODE" >> {output_file}

    touch {lock_file}

    echo "---------------------------------------------------"
    echo "Command completed. Waiting for next command..."
    echo "---------------------------------------------------"
}}

while true; do
    if [ -e {fifo_path} ]; then
        process_command
    else
        sleep 0.5
    fi
done
'''.format(
                pid_file=self.pid_file,
                fifo_path=self.fifo_path,
                lock_file=self.lock_file,
                output_file=self.output_file,
            )
            # Write with owner-only exec permissions — no group/world read.
            fd = os.open(script_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o700)
            with os.fdopen(fd, "w") as f:
                f.write(script_content)

            logging.info(f"Launching persistent terminal (platform: {platform.system()}, type: {self.terminal_type})")
            self._launch_terminal(script_path)

            # Wait for terminal to initialize
            wait_count = 0
            while not os.path.exists(self.pid_file) and wait_count < 20:
                time.sleep(0.5)
                wait_count += 1
                print(f"\rWaiting for terminal to initialize... {wait_count}/20", end="")

            print()  # New line after waiting

            if os.path.exists(self.pid_file):
                with open(self.pid_file, 'r') as f:
                    pid = f.read().strip()
                logging.info(f"Persistent terminal initialized successfully. PID: {pid}")
                #print_formatted_text(HTML(f"<ansigreen>Persistent terminal initialized successfully. PID: {pid}</ansigreen>"))
                self.terminal_initialized = True
            else:
                logging.error("Failed to initialize persistent terminal.")
                print_formatted_text(HTML("<ansired>Failed to initialize persistent terminal. Using fallback method.</ansired>"))
                self._initialize_fallback()

        except Exception as e:
            logging.error(f"Error initializing persistent terminal: {e}")
            print_formatted_text(HTML(f"<ansired>Error initializing persistent terminal: {e}</ansired>"))
            self._initialize_fallback()

    def _launch_terminal(self, script_path: str) -> None:
        """Start a persistent terminal window running script_path.

        Handles macOS (Terminal.app / iTerm2 via osascript) and Linux
        (XDG desktop environment detection + generic fallback) separately.
        """
        if _IS_MACOS:
            self._launch_terminal_macos(script_path)
        else:
            self._launch_terminal_linux(script_path)

    def _launch_terminal_macos(self, script_path: str) -> None:
        """Open a new terminal window on macOS using AppleScript (osascript)."""
        if self.terminal_type == "iterm2":
            # iTerm2: create a new window running our script.
            applescript = (
                'tell application "iTerm2"\n'
                '  create window with default profile\n'
                '  tell current session of current window\n'
                f'    write text "bash {script_path}"\n'
                '  end tell\n'
                'end tell'
            )
        else:
            # Terminal.app: open a new window and run the script in it.
            applescript = (
                'tell application "Terminal"\n'
                f'  do script "bash {script_path}"\n'
                '  activate\n'
                'end tell'
            )

        logging.info("Launching macOS terminal via osascript (%s)", self.terminal_type)
        subprocess.Popen(
            ["osascript", "-e", applescript],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    def _launch_terminal_linux(self, script_path: str) -> None:
        """Open a persistent terminal window on Linux."""
        desktop_env = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()

        if "gnome" in desktop_env or "unity" in desktop_env:
            term_cmd = f"gnome-terminal -- bash {script_path}"
        elif "kde" in desktop_env or "plasma" in desktop_env:
            term_cmd = f"konsole -e bash {script_path}"
        elif "xfce" in desktop_env:
            term_cmd = f"xfce4-terminal -e 'bash {script_path}'"
        else:
            term_cmd = f"{self.terminal_type} bash {script_path}"

        logging.info("Launching Linux terminal: %s", term_cmd)
        subprocess.Popen(
            term_cmd,
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    def _initialize_fallback(self):
        """Initialize a fallback terminal method."""
        # Create a simple script that just writes the PID to file
        script_path = os.path.join(self.temp_dir, "neo_fallback_script.sh")
        with open(script_path, 'w') as f:
            f.write(f'''#!/bin/bash
echo $$ > {self.pid_file}
echo "Neo AI Fallback Terminal"
while true; do
    sleep 1
done
''')
        # Make executable
        os.chmod(script_path, 0o755)

        # Start a background process
        subprocess.Popen(['bash', script_path],
                       stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL,
                       start_new_session=True)

        # Wait a moment
        time.sleep(1)
        if os.path.exists(self.pid_file):
            logging.info("Fallback terminal method initialized.")
            self.terminal_initialized = True

    def _cleanup(self):
        """Clean up resources on exit."""
        try:
            # Remove FIFO
            if os.path.exists(self.fifo_path):
                os.unlink(self.fifo_path)

            # Terminal will auto-close when its script exits
            if os.path.exists(self.pid_file):
                try:
                    with open(self.pid_file, 'r') as f:
                        pid = int(f.read().strip())
                    os.kill(pid, signal.SIGTERM)
                except Exception:
                    pass
                os.unlink(self.pid_file)
        except Exception as e:
            logging.error(f"Error during cleanup: {e}")

    def execute_command(self, command):
        """
        Execute a command in the persistent terminal.

        Args:
            command (str): Command to execute

        Returns:
            str: Path to the output file
        """
        # Remove any existing lock file
        if os.path.exists(self.lock_file):
            os.unlink(self.lock_file)

        # Clear the output file
        with open(self.output_file, 'w') as f:
            f.write("")

        try:
            # Make sure terminal is running - lazy initialization
            if not self._is_terminal_running():
                if not self.terminal_initialized:
                    logging.info("First command detected, initializing terminal...")
                    #print_formatted_text(HTML("<ansigreen>Initializing persistent terminal for command execution...</ansigreen>"))
                    self.terminal_initialized = True
                else:
                    logging.info("Terminal not running, restarting...")

                self._initialize_terminal()
                # Give it a moment to start
                time.sleep(2)

                # Verify it's running after initialization
                if not self._is_terminal_running():
                    logging.error("Terminal failed to initialize properly. Using direct execution.")
                    # Execute directly as fallback — use ["bash", "-c"] instead of
                # shell=True to avoid an extra shell-interpolation layer.
                    try:
                        result = subprocess.run(
                            ["bash", "-c", command], capture_output=True, text=True
                        )
                        with open(self.output_file, 'w') as f:
                            f.write(result.stdout + "\n" + result.stderr)
                        # Create lock file to signal completion
                        with open(self.lock_file, 'w') as f:
                            pass
                        return self.output_file
                    except Exception as direct_exec_error:
                        logging.error(f"Direct execution also failed: {direct_exec_error}")
                        with open(self.output_file, 'w') as f:
                            f.write(f"Error: {direct_exec_error}")
                        with open(self.lock_file, 'w') as f:
                            pass
                        return self.output_file

            logging.info(f"Sending command to persistent terminal: {command}")
           # print_formatted_text(HTML(f"<ansiyellow>Executing in persistent terminal:</ansiyellow> <ansiblue>{command}</ansiblue>"))

            # Send command to terminal via FIFO
            with open(self.fifo_path, 'w') as f:
                f.write(command)

            # Return the output file path
            return self.output_file

        except Exception as e:
            logging.error(f"Error sending command to persistent terminal: {e}")
            print_formatted_text(HTML(f"<ansired>Error: {e}</ansired>"))

            # Create error output
            with open(self.output_file, "w") as f:
                f.write(f"Error executing command: {e}\n")

            # Create lock file to indicate completion
            with open(self.lock_file, "w") as f:
                pass

            return self.output_file

    def wait_for_command_completion(self):
        """
        Wait for the command to complete by checking for the lock file.

        Returns:
            str: Command output
        """
        max_wait_time = 180  # 3 minutes max wait
        start_time = time.time()
        animation_frames = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
        frame_index = 0

        #print_formatted_text(HTML("<ansicyan>Waiting for command to complete...</ansicyan>"))

        while not os.path.exists(self.lock_file):
            elapsed_time = time.time() - start_time

            if elapsed_time > max_wait_time:
                print_formatted_text(HTML("<ansired>Command timed out after 3 minutes</ansired>"))
                # Create an empty lock file to prevent further hangs
                with open(self.lock_file, "w") as f:
                    pass
                break

            # Every 0.2 seconds, update the animation
            if int(elapsed_time * 5) % len(animation_frames) != frame_index:
                frame_index = int(elapsed_time * 5) % len(animation_frames)
                print(f"\r{animation_frames[frame_index]} Waiting for command to complete... ({int(elapsed_time)}s)", end="")

            time.sleep(0.1)

        print()  # New line after waiting animation

        # Read the output file
        try:
            if os.path.exists(self.output_file):
                with open(self.output_file, "r") as f:
                    return f.read()
            else:
                return "No output was captured. The command may have failed to execute properly."
        except Exception as e:
            return f"Error reading command output: {str(e)}"

# Function for simple command execution (without terminal)
def execute_command(command: str) -> str:
    """Execute a command silently and return its output as a string.

    Used for internal context gathering (pwd, ls at startup). Does not print
    anything to the terminal.
    """
    try:
        logging.debug(f"Executing simple command: {command}")
        result = subprocess.run(
            ["bash", "-c", command],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return result.stdout
        else:
            return f"Error: Command failed with exit code {result.returncode}\n{result.stderr}"
    except subprocess.TimeoutExpired:
        return "Error: Command execution timed out after 30 seconds"
    except FileNotFoundError:
        return "Error: bash not found — cannot execute command"
    except PermissionError:
        return f"Error: Permission denied when executing: {command}"
    except Exception as e:
        return f"Error: {str(e)}"


def execute_command_inline(command: str, timeout: int = 120) -> str:
    """Execute a command and stream its output directly to the current terminal.

    This is the default execution path for user-requested commands. It works
    in any environment — SSH sessions, headless servers, macOS, Linux — because
    it never opens a second terminal window.

    Output is printed line by line as it arrives (real-time streaming) and also
    returned as a string so the AI can summarise the result.

    Args:
        command: Shell command to execute.
        timeout:  Max seconds to wait (default 120). Long-running commands
                  (backups, large downloads) can increase this via config.

    Returns:
        Combined stdout + stderr output as a string.
    """
    output_lines: list[str] = []
    try:
        proc = subprocess.Popen(
            ["bash", "-c", command],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,   # merge stderr into stdout stream
            text=True,
            bufsize=1,                  # line-buffered
        )

        # Stream output line by line so the user sees progress in real-time.
        assert proc.stdout is not None
        for line in proc.stdout:
            print(line, end="", flush=True)
            output_lines.append(line)

        proc.wait(timeout=timeout)
        exit_code = proc.returncode

    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        timeout_msg = f"\n[neo] Command timed out after {timeout}s\n"
        print(timeout_msg, end="")
        output_lines.append(timeout_msg)
        exit_code = -1
    except FileNotFoundError:
        msg = "Error: bash not found\n"
        print(msg, end="")
        return msg
    except Exception as e:
        msg = f"Error: {e}\n"
        print(msg, end="")
        return msg

    if exit_code != 0:
        exit_line = f"[exit code {exit_code}]\n"
        output_lines.append(exit_line)

    return "".join(output_lines)

# Create a singleton instance
terminal_executor = PersistentTerminalExecutor()

def execute_command_in_terminal(command):
    """
    Execute a command in the persistent terminal.

    Args:
        command (str): Command to execute

    Returns:
        str: Path to the output file
    """
    return terminal_executor.execute_command(command)

def wait_for_command_completion(temp_file):
    """
    Wait for a command to complete and read its output.

    Args:
        temp_file (str): Path to the output file

    Returns:
        str: Command output
    """
    return terminal_executor.wait_for_command_completion()