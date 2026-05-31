# Neo AI — Terminal AI Assistant

Neo is an AI-powered terminal assistant for macOS and Linux. It understands natural language, executes shell commands with real-time output, and adapts to your system automatically. It supports multiple AI backends — local or cloud — and can switch between them without restarting.

---

## Features

- **Natural language → shell commands** with full real-time streaming output
- **One-shot mode** — use `neo: <prompt>` directly from any directory without entering an interactive session
- **SSH and headless compatible** — runs entirely in the current terminal, no second window needed
- **OS-aware context** — detects macOS vs Linux at startup and always uses the correct commands (`ifconfig` not `ip addr`, `brew` not `apt`, etc.)
- **Command approval** — every command requires explicit confirmation before execution
- **Multiple AI backends** — Ollama, LM Studio, OpenAI API, Anthropic Claude API
- **Hot-swap backends** — switch model or provider mid-session with `neo-use`
- **Ollama model nicknames** — define short aliases (`gemma`, `qwencode`) in config and switch with `neo-use ollama:gemma`
- **Model-specific context plugins** — drop a `.md` file into `config/model_contexts/` to inject model-aware instructions automatically; Ollama supports per-model plugin files (e.g. `ollama.gemma.md`)
- **Tone system** — switch Neo's communication style mid-session with `neo-tone` (professional, technical, minimal, or off)
- **Runbook support** — run structured Markdown health-check runbooks with `neo-run`; all commands execute without approval prompts and the AI analyses the collected output
- **Security runbooks** — 8 dedicated security runbooks: CIS hardening assessment, Docker security audit, threat-hunting for persistence mechanisms, Linux digital forensics, network threat hunting, incident response, and web log attack analysis
- **Expanded security MCP protocol** — 32 named commands across users/network/processes/filesystem/persistence/kernel/SSH/integrity categories; quick checks without writing a full runbook
- **Prompt anonymization** — automatically replace IPs, hostnames, usernames, paths, and API keys with stable placeholders before sending to external AI backends; real values are restored in responses
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
6. Also writes a `neo:` launcher for one-shot usage (see [One-shot mode](#one-shot-mode))

After that, `neo` and `neo:` are available in any shell, from any directory — no manual alias or `source` step needed.

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
neo              # start interactive session (default)
neo --classic    # start with the classic readline interface
neo --debug      # enable debug logging
```

### One-shot mode

Ask a single question directly from the shell — without entering an interactive session. Neo processes the prompt, prints the response (with command approval if needed), and exits:

```bash
neo: show me the contents of this directory
neo: how much disk space is left?
neo: which processes are listening on port 8080?
neo: create a summary of all .log files in /var/log
neo: is nginx running and when was it last restarted?
```

`neo:` is an alias installed alongside `neo`. It is identical to passing arguments directly:

```bash
neo how much free memory is available?   # works too
```

The animated thinking spinner (`⠋ ⠙ ⠹ ⠸ …`) appears while waiting for the model and stops automatically before any output is printed.

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
| `neo-verbose [on\|off]` | Toggle verbose output (show/hide MCP tags) |
| `neo-tone <name\|off>` | Switch Neo's communication tone |
| `neo-run <runbook> [--tag TAG] [--section N]` | Run a health-check runbook |
| `neo-anon [on\|off\|status]` | Toggle prompt anonymization for external backends |

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

### Tone system

Switch Neo's communication style at any point without restarting:

```
neo-tone professional   # formal, structured, precise
neo-tone technical      # terse, command-focused, no filler text
neo-tone minimal        # single-sentence answers, no explanations
neo-tone off            # revert to the default tone from PrePromt.md
```

Tones are plain `.md` files in `config/tones/`. Add your own by dropping a file there — no code changes needed. The active tone is appended to the system prompt as a third layer (after the base prompt and model-context plugins) and survives `neo-use` backend switches.

### Prompt anonymization

When using external AI backends (OpenAI, Claude) Neo can automatically replace sensitive information with stable numbered placeholders before sending any text to the API. The AI sees `[IP_1]` and `[HOST_1]` instead of your real server addresses and hostnames. Responses are optionally de-anonymized before display so the conversation stays natural.

**What gets replaced:**

| Category | Example | Placeholder |
|---|---|---|
| IPv4 / IPv6 addresses | `192.168.1.10`, `::1` | `[IP_1]`, `[IP6_1]` |
| MAC addresses | `aa:bb:cc:dd:ee:ff` | `[MAC_1]` |
| E-mail addresses | `admin@example.com` | `[EMAIL_1]` |
| API / secret keys | `sk-...`, `sk-ant-...` | `[API_KEY_1]` |
| Your hostname | `myserver` | `[HOST_1]` |
| Your username | `myuser` | `[USER_1]` |
| Home-directory paths | `/home/myuser/projects/` | `[PATH_1]` |

Placeholders are **session-stable** — the same value always gets the same placeholder so the AI can give consistent answers across follow-up messages. Standard system paths (`/etc/`, `/usr/bin/`, `/var/log/`) are left unchanged.

**Enable in `config/config.yaml`:**

```yaml
anonymize:
  enabled: true
  modes: [openai, claude]       # local backends are never affected
  deanonymize_responses: true   # restore real values in AI responses
```

**Toggle at runtime:**

```
neo-anon on       # enable for this session
neo-anon off      # disable
neo-anon status   # show current state and number of active mappings
```

Local backends (Ollama, LM Studio) are never anonymized regardless of the setting.

---

## Runbooks

Runbooks are structured Markdown files that automate repeatable health checks or diagnostic tasks. Neo executes every command block in order — **no approval prompts** (runbooks are explicitly trusted) — then sends the full output to the AI for analysis and a structured report.

### Running a runbook

```
neo-run linux-server-health                        # full run
neo-run linux-server-health --tag DAILY            # only [DAILY]-tagged sections
neo-run linux-server-health --section 3            # only section 3.x subsections
neo-run /path/to/custom-runbook.md                 # absolute or relative path
```

Tab completion suggests runbook names from `config/runbooks/`.

### Runbook format

```markdown
# My Runbook Title

## Agent Instructions
Tell the AI how to interpret the output...

## Agent Output Format
Define the exact report structure the AI should produce...

## Baseline Reference
Expected values for this specific server...

## 1. Section Title [DAILY]

### 1.1 Subsection Title

\`\`\`bash
command --to --run
\`\`\`

**Analyze:**
- threshold rule 1
- threshold rule 2
```

**Section tags** (e.g. `[DAILY]`, `[WEEKLY]`) let you filter what runs. Special sections (`Agent Instructions`, `Agent Output Format`, `Baseline Reference`) are never executed — they are passed to the AI as context only.

### Bundled runbooks

**Security assessment:**

| File | Purpose |
|---|---|
| `cis-linux-assessment.md` | CIS Level 1 compliance: filesystem, services, SSH, users, audit, SUID |
| `docker-security.md` | CIS Docker Benchmark: daemon config, runtime, image scanning, isolation |
| `threat-hunting-persistence.md` | Hunt: cron, systemd, shell profiles, SSH keys, SUID, LD_PRELOAD, kernel modules |
| `linux-forensics.md` | IR volatile evidence: processes, connections, deleted-running files, auth logs |
| `network-threat-hunting.md` | C2 beaconing, DNS exfiltration/tunneling, lateral movement, ARP anomalies |
| `incident-response.md` | Structured IR: triage → containment (approval) → evidence → eradication (approval) → recovery |
| `webserver-log-analysis.md` | nginx/Apache: SQLi, XSS, path traversal, scanner signatures, attack IPs |

**Health checks:**

| File | Purpose |
|---|---|
| `linux-server-health.md` | Disk, CPU, Docker, networking, failed logins (daily health check) |
| `homeserver-runbook.md` | Full home server audit: storage, SMART, performance, services, backups |
| `macbook.md` | macOS health: storage, battery, system load, network, security |

Place your own runbooks in `config/runbooks/` — they appear in Tab completion immediately.

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

Plugins are loaded in scoring order — `default.md` always first, then mode-specific, then model-specific — so instructions stack additively rather than replacing each other.

Bundled plugins:

| File | Applies to |
|---|---|
| `default.md` | All models — base rules, full security runbook catalog and MCP command reference |
| `claude.md` | Claude mode |
| `openai.md` | All OpenAI models |
| `openai_reasoning.md` | o1 / o3 / o4 / gpt-5 series |
| `ollama.md` | All Ollama models — includes `--section N` guidance for managing context limits |
| `ollama.gemma.md` | Ollama + gemma4 / gemma3 / gemma family |
| `ollama.qwen.md` | Ollama + qwen3 / qwen2 / qwen family |
| `ollama.llama.md` | Ollama + llama3 / llama2 / llama family |
| `ollama.mistral.md` | Ollama + mistral / mixtral / devstral family |
| `lm_studio.md` | All LM Studio models |
| `security-cloud.md` | Claude mode — extended security tool reference (35 tools) + runbook decision guide + analysis rules |
| `security-openai.md` | OpenAI mode — same extended security context as security-cloud.md |

---

## MCP Protocol

Neo uses an internal Machine Communication Protocol to interact with the system. The AI generates tagged instructions; Neo parses and executes them after your approval.

| Protocol | Purpose | Examples |
|---|---|---|
| `terminal` | Run shell commands | Any shell command |
| `files` | Read / write / list files | `read:/etc/hosts`, `write:/tmp/note.txt content` |
| `analyze` | Full system overview | CPU, memory, disk, network, services |
| `network` | Network operations | `connections`, `interfaces`, `ping:host`, `scan:192.168.1.0/24` |
| `security` | Security checks (32 commands) | `users`, `ports`, `connections`, `suid`, `authorized-keys`, `ld-preload`, `rootkits`, `nopasswd-sudo`, `deleted-running`, `world-writable`, … |

Full security command reference is in `config/model_contexts/default.md`. Quick-reference by category:

| Category | Commands |
|---|---|
| Users & accounts | `users` `groups` `sudo` `accounts` `logins` `history` `failed-logins` `nopasswd-sudo` `uid0` `shadow-perms` `inactive-accounts` |
| Network | `ports` `listening` `connections` `arp` `firewall` `fail2ban` |
| Processes | `processes` `processes-tree` `deleted-running` |
| File system | `suid` `sgid` `capabilities` `world-writable` `unowned-files` `tmp-executables` |
| Persistence | `cronjobs` `crontabs-all` `systemd-units` `systemd-timers` `authorized-keys` `ld-preload` |
| Kernel & SSH | `kernelmodules` `kernelmodules-unsigned` `ssh-config` `ssh-keys` |
| Integrity | `rootkits` |
| Parametric | `check:<path>` `vulnerabilities:<package>` |

---

## Example Session

**One-shot from any directory:**

```bash
user@myserver:~/projects$ neo: show me the contents of this directory
⠴ Thinking.
Neo: Let me list the files in your current directory.

Neo > ls -la
  ↳ Execute this command? [Enter/n]:
...
```

**Interactive session:**

```
user@neo [ollama:gemma4:latest] > find the document "report.pdf" and copy it to Downloads

Neo: Searching your home folder for report.pdf.

Neo > find "$HOME" -name "report.pdf" -maxdepth 5 2>/dev/null
  ↳ Execute this command? [Enter/n]:
/home/user/Documents/report.pdf
Neo: Done.

Neo > cp "/home/user/Documents/report.pdf" "$HOME/Downloads/"
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
│   ├── model_contexts/              # Model-specific context plugins (drop-in .md files)
│   │   ├── default.md               #   Applied to every model (incl. security runbook catalog)
│   │   ├── claude.md
│   │   ├── openai.md
│   │   ├── openai_reasoning.md      #   o1 / o3 / o4 / gpt-5 series
│   │   ├── ollama.md                #   Includes section-mode guidance for local context limits
│   │   ├── ollama.gemma.md          #   Gemma family
│   │   ├── ollama.qwen.md           #   Qwen family
│   │   ├── ollama.llama.md          #   Llama family
│   │   ├── ollama.mistral.md        #   Mistral / Mixtral family
│   │   ├── lm_studio.md
│   │   ├── security-cloud.md        #   Extended security reference for Claude (35 tools + decision guide)
│   │   └── security-openai.md       #   Extended security reference for OpenAI (identical content)
│   ├── tones/                       # Tone plugins (drop-in .md files)
│   │   ├── professional.md
│   │   ├── technical.md
│   │   ├── minimal.md
│   │   └── casual.md
│   └── runbooks/                    # Health-check and security runbooks (drop-in .md files)
│       ├── cis-linux-assessment.md  #   CIS Level 1 compliance audit
│       ├── docker-security.md       #   CIS Docker Benchmark
│       ├── threat-hunting-persistence.md  # Persistence mechanism hunt
│       ├── linux-forensics.md       #   Volatile evidence collection (IR)
│       ├── network-threat-hunting.md #  C2, DNS exfil, ARP, lateral movement
│       ├── incident-response.md     #   Full IR lifecycle (triage → recovery)
│       ├── webserver-log-analysis.md #  nginx/Apache attack pattern detection
│       ├── linux-server-health.md   #   Daily health check
│       ├── homeserver-runbook.md    #   Full home server audit
│       └── macbook.md              #   macOS health check
├── src/
│   ├── ai_core.py                   # NeoAI class, backend dispatch, history, runbooks
│   ├── model_context_loader.py      # Plugin loader for model_contexts/
│   ├── runbook_runner.py            # Runbook parser, executor, AI prompt builder
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
