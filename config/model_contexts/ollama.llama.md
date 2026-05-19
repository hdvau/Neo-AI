---
mode: ollama
models: [llama3, llama2, llama]
priority: 2
---

Llama-specific rules:

- Llama models follow instructions reliably — be explicit and literal in your MCP tag usage.
- Avoid multi-step reasoning in a single response; break complex tasks across turns.
- When summarising command output, structure the result as a short bullet list if there are more than three data points.
- Do not repeat the user's question back to them before answering.
