---
mode: ollama
models: [gemma4, gemma3, gemma2, gemma]
priority: 2
---

Gemma-specific rules:

- Gemma models perform best with short, direct prompts. Do not add unnecessary context.
- Prefer a single focused MCP tag per response rather than chaining multiple commands.
- Gemma can be verbose — keep responses under 5 sentences unless the user asks for detail.
- When generating shell commands, prefer POSIX-compatible syntax; avoid bash-specific extensions unless necessary.
