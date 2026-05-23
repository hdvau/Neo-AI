---
mode: ollama
priority: 1
---

Rules for locally-hosted Ollama models:

- Always use the exact MCP tag format: `<mcp:protocol>command</mcp:protocol>`. Do not add spaces or newlines inside the tags.
- One MCP tag per response. Do not combine multiple commands into a single tag using `&&` or `;` unless the user explicitly asks for a pipeline.
- Do not guess command output. If you have not yet run a command, say so and emit the tag — do not invent results.
- Prefer short, focused commands. Avoid commands that produce large outputs (e.g. `cat` on big files); use `head`, `grep`, or `tail` instead.
- For security runbooks, recommend `--section N` (e.g. `neo-run cis-linux-assessment --section 1`) to run one section at a time — this keeps command output within context limits. Only suggest a full runbook run for models with 32k+ context.
