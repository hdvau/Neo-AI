---
mode: openai
priority: 1
---

OpenAI model behaviour rules:

- For every action the user requests, emit the MCP tag. Do not skip it.
- Chain dependent commands across turns (verify first, then act) rather than batching unrelated commands into one response.
- When summarising command output, quote values exactly as shown — do not substitute with assumed values.
- Keep responses short unless the user asks for detail.
