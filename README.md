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
- **Ollama model nicknames** — define short aliases (`gemma`, `qwencode`) in config and switch with `neo-use ollama:gemma`
- **Model-specific context plugins** — drop a `.md` file into `config/model_contexts/` to inject model-aware instructions automatically
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

**Requirements:** Python 3.10+, one of the backends above.

```bash
git clone https://github.com/hdvau/Neo-AI.git
cd Neo-AI
bash install.sh
```

The installer:
1. Checks Python 3.10+
2. Creates a `.venv` virtual environment inside the project directory
3. Installs all dependencies via `pip`
4. Copies `config/config.yaml.example` → `config/config.yaml` on first run
5. Writes a `neo` launcher to `/usr/local/bin` (or `~/.local/bin` as fallback)

After that, `neo` is available in any shell, from any directory — no manual alias or `source` step needed.

**Update an existing installation:**

```bash
git pull
bash install.sh   # safe to re-run — updates deps in place
```

**Uninstall:**

```bash
bash uninstall.sh
```

---

## Configuration

Edit `config/config.yaml` (created automatically on first install):

```bash
nano config/config.yaml
```

### Ollama (local, no key needed)

```yaml
mode: "ollama"
ollama_config:
  api_url: "http://localhost:11434/v1"   # supports remote hosts
  model: "llama3.2"                      # default for: neo-use ollama

  models:                                # optional nicknames (see below)
    gemma:    "gemma4:latest"
    qwencode: "qwen3-coder"
    mistral:  "mistral:latest"
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

```bash
neo              # start with the improved UI (default)
neo --classic    # start with the classic readline interface
neo --debug      # enable debug logging
```

The prompt shows your active backend and model:

```
user@neo [ollama:gemma4:latest] >
```

### Built-in commands

| Command | Description |
|---|---|
| `help` | Show available commands |
| `history` | Display conversation history |
| `clear` | Clear the screen |
| `exit` | Quit Neo |
| `neo-use <mode> [model]` | Switch AI backend at runtime |
| `neo-use ollama:<nickname>` | Switch to an Ollama model by nickname |
| `neo-verbose [on\|off]` | Toggle verbose output |

### Switching backends mid-session

Switch without losing your conversation history:

```
neo-use ollama
neo-use ollama mistral:latest     # direct model name
neo-use ollama:gemma              # nickname (resolves to gemma4:latest)
neo-use ollama:qwencode           # nickname (resolves to qwen3-coder)
neo-use openai gpt-4o
neo-use claude
neo-use lm_studio
```

Tab completion works after `neo-use ` — all modes and configured Ollama nicknames are suggested automatically.

### Ollama model nicknames

Define short aliases in `config.yaml` so you never have to type full model identifiers:

```yaml
ollama_config:
  model: "llama3.2"         # default
  models:
    gemma:    "gemma4:latest"
    qwencode: "qwen3-coder"
    mistral:  "mistral:latest"
```

Then switch with:
```
neo-use ollama:gemma
neo-use ollama:qwencode
```

Lookups are case-insensitive. Unknown nicknames print the list of available ones.

### Verbose mode

By default, MCP protocol tags are hidden and only the clean response is shown. Toggle for debugging:

```
neo-verbose          # toggle
neo-verbose on       # show raw model output including MCP tags
neo-verbose off      # back to clean output (default)
```

---

## Model Context Plugins

Neo automatically injects model-specific instructions into the system prompt. Plugins live in `config/model_contexts/` as plain `.md` files with optional YAML front-matter:

```markdown
---
mode: openai
models: [o1, o3, o4, gpt-5]
priority: 2
---

Output each MCP tag exactly once. Do not narrate your reasoning steps...
```

**Resolution:** `default.md` always loads first, then mode-specific files, then model-specific files — each layer appends to the previous so overrides are additive.

**To add your own:** drop a `.md` file into `config/model_contexts/` — no code changes needed. Neo picks it up on next start (or after `neo-use`).

Bundled plugins:

| File | Applies to |
|---|---|
| `default.md` | All models |
| `claude.md` | Claude mode |
| `openai.md` | All OpenAI models |
| `openai_reasoning.md` | o1 / o3 / o4 / gpt-5 series |
| `ollama.md` | All Ollama models |
| `lm_studio.md` | All LM Studio models |

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
user@neo [ollama:gemma4:latest] > find the document "report.pdf" and copy it to Downloads

Neo: Searching your home folder for report.pdf.

Neo > find "$HOME" -name "report.pdf" -maxdepth 5 2>/dev/null
  ↳ Execute this command? [Enter/n]:
/Users/user/Documents/report.pdf
Neo: Done.

Neo > cp "/Users/user/Documents/report.pdf" "$HOME/Downloads/"
  ↳ Execute this command? [Enter/n]:
Neo: Done.

user@neo [ollama:gemma4:latest] > neo-use ollama:qwencode
Switched to ollama — model: qwen3-coder

user@neo [ollama:qwen3-coder] >
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
├── pyproject.toml                   # Package definition and entry point (`neo`)
├── install.sh                       # Installer — sets up .venv and `neo` command
├── uninstall.sh                     # Removes `neo` launcher and .venv
├── requirements.txt                 # Pinned dependencies (reference)
├── config/
│   ├── config.yaml.example          # Template — copied to config.yaml on install
│   ├── PrePromt.md                  # Base system prompt loaded at startup
│   └── model_contexts/              # Model-specific context plugins (drop-in .md files)
│       ├── default.md
│       ├── claude.md
│       ├── openai.md
│       ├── openai_reasoning.md
│       ├── ollama.md
│       └── lm_studio.md
├── src/
│   ├── ai_core.py                   # NeoAI class, backend dispatch, history
│   ├── model_context_loader.py      # Plugin loader for model_contexts/
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
