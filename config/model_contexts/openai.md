---
mode: openai
priority: 1
---

OpenAI model behaviour rules:

- Use a single MCP tag per response where possible. Chain dependent commands across turns rather than batching them.
- When summarising command output, quote values exactly as shown — do not substitute with assumed values.
- Keep responses short unless the user asks for detail.
