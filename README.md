# Neo AI — Terminal AI Assistant

Neo is an AI-powered terminal assistant for macOS and Linux. It understands natural language, executes shell commands with real-time output, and adapts to your system automatically. It supports multiple AI backends — local or cloud — and can switch between them without restarting.

---

## Features

- **Natural language → shell commands** with full real-time streaming output
- **SSH and headless compatible** — runs entirely in the current terminal, no second window needed
- **OS-aware context** — detects macOS vs Linux at startup and always uses the correct commands (`ifconfig` not `ip addr`, `brew` not `apt`, etc.)
- **Command approval** — every command requires explicit confirmation before execution
- **Multiple AI backends** — Ollama, LM Studio, OpenAI API, Anthropic Claude API
- **Hot-swap backends** — switch model or provider mid-session with `neo-use`
- **Clean output by default** — MCP protocol tags are hidden; toggle verbose mode with `neo-verbose`
- **Conversation history** with configurable length and automatic trimming
- **Persistent memory** loaded as context at startup
- **Path-safe file operations** — directory traversal protection on all file reads/writes

---

## Supported AI Backends

| Mode | Provider | API key required |
|---|---|---|
| `ollama` | Local [Ollama](https://ollama.com) server | No |
| `lm_studio` | Local [LM Studio](https://lmstudio.ai) | No |
| `openai` | OpenAI API | Yes — `OPENAI_API_KEY` |
| `claude` | Anthropic API | Yes — `ANTHROPIC_API_KEY` |

---

## Installation

**Requirements:** Python 3.8+, pip, one of the backends above.

```bash
git clone https://github.com/hdvau/Neo-AI.git
cd Neo-AI
./install.sh
```

Add the alias to your shell profile:

```bash
echo "alias neo='source $(pwd)/venv/bin/activate && python3 $(pwd)/main.py'" >> ~/.zshrc
# or ~/.bashrc for bash
source ~/.zshrc
```

---

## Configuration

Copy the example and fill in your values:

```bash
cp config/config.yaml.example config/config.yaml
nano config/config.yaml
```

### Ollama (local, no key needed)

```yaml
mode: "ollama"
ollama_config:
  api_url: "http://localhost:11434/v1"   # supports remote hosts
  model: "mistral:latest"
```

### LM Studio (local, no key needed)

```yaml
mode: "lm_studio"
lm_studio_config:
  api_url: "http://127.0.0.1:1234/v1"
  model: "your-model-name"
```

### OpenAI

```yaml
mode: "openai"
openai_config:
  api_key: "sk-..."          # or export OPENAI_API_KEY
  model: "gpt-4o"
  temperature: 1             # required for o1/o3/gpt-5.x reasoning models
```

### Anthropic Claude

```yaml
mode: "claude"
claude_config:
  api_key: "sk-ant-..."      # or export ANTHROPIC_API_KEY
  model: "claude-opus-4-5"
  max_tokens: 4096
```

### Common settings

```yaml
command_approval:
  require_approval: true     # prompt before every command
  auto_approve_all: false    # DANGER: skips all prompts

stream: true
max_history_messages: 40
command_timeout: 120         # seconds per command
```

---

## Usage

Start Neo:

```bash
neo
# or with the classic interface:
neo --classic
```

The prompt shows your active backend and model:

```
dha@neo [ollama:mistral:latest] >
```

### Built-in commands

| Command | Description |
|---|---|
| `help` | Show available commands |
| `history` | Display conversation history |
| `clear` | Clear the screen |
| `exit` | Quit Neo |
| `neo-use <mode> [model]` | Switch AI backend at runtime |
| `neo-verbose [on\|off]` | Toggle verbose output |

### Switching backends mid-session

Switch without losing your conversation history:

```
neo-use claude
neo-use openai gpt-4o
neo-use ollama mistral:latest
neo-use lm_studio
```

Tab completion works after `neo-use ` — press Tab to see available modes.

### Verbose mode

By default, MCP protocol tags are hidden and only the clean response is shown. Toggle for debugging:

```
neo-verbose          # toggle
neo-verbose on       # show raw model output including MCP tags
neo-verbose off      # back to clean output (default)
```

---

## MCP Protocol

Neo uses an internal Machine Communication Protocol to interact with the system. The AI generates tagged instructions; Neo parses and executes them after your approval.

| Protocol | Purpose | Examples |
|---|---|---|
| `terminal` | Run shell commands | Any shell command |
| `files` | Read / write / list files | `read:/etc/hosts`, `write:/tmp/note.txt content` |
| `analyze` | Full system overview | CPU, memory, disk, network, services |
| `network` | Network operations | `connections`, `interfaces`, `ping:host`, `scan:192.168.1.0/24` |
| `security` | Security checks | `users`, `ports`, `listening` |

---

## Example Session

```
dha@neo [claude:claude-opus-4-5] > find the document "report.pdf" and copy it to Downloads

Neo:  Searching your home folder for report.pdf.

  ↳ Execute this command? [Enter/n]: ✓
──────────────────────────────────────────────────
/Users/dha/Documents/report.pdf
──────────────────────────────────────────────────

Neo:  Found it at /Users/dha/Documents/report.pdf. Copying it to Downloads now.

  ↳ Execute this command? [Enter/n]: ✓
──────────────────────────────────────────────────
──────────────────────────────────────────────────

Neo:  Done — report.pdf is now in your Downloads folder.
```

---

## Security

- **Explicit approval** required before any command runs
- **No auto-approve by default** — set `auto_approve_all: true` only if you understand the risk
- **Path traversal protection** on all file protocol operations
- **API keys** stay in your local `config/config.yaml` (gitignored) or environment variables
- `config/config.yaml` is excluded from git — never committed

---

## Project Structure

```
Neo-AI/
├── main.py                          # Entry point, config loading, validation
├── config/
│   ├── config.yaml.example          # Template — copy to config.yaml
│   └── PrePromt.md                  # System prompt loaded at startup
├── src/
│   ├── ai_core.py                   # NeoAI class, backend dispatch, history
│   ├── approval_handler.py          # Command approval prompts
│   ├── command_executor.py          # Inline command execution (streaming)
│   ├── terminal_interface.py        # Classic readline UI
│   ├── terminal_ui.py               # Improved prompt_toolkit UI
│   ├── utils.py                     # Persistent memory, helpers
│   └── mcp_protocol/
│       ├── core.py                  # MCP tag parser and dispatcher
│       ├── registry.py              # Handler registry
│       └── handlers/
│           ├── terminal_protocol.py
│           ├── files_protocol.py
│           ├── analyze_protocol.py
│           ├── network_protocol.py
│           └── security_protocol.py
└── tests/                           # pytest test suite
```

---

## Contributing

Pull requests are welcome. Clone from [hdvau/Neo-AI](https://github.com/hdvau/Neo-AI) — this is the actively maintained fork with all current features.

## License

BSD 3-Clause — see [LICENSE](LICENSE).
