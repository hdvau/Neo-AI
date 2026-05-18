---
mode: lm_studio
priority: 1
---

Rules for locally-hosted LM Studio models:

- Always use the exact MCP tag format: `<mcp:protocol>command</mcp:protocol>`. Do not add extra whitespace or markdown formatting around tags.
- One MCP tag per response unless the commands are completely independent and the user asked for multiple actions at once.
- Do not invent command output. Emit the tag, wait for the result, then summarise the actual output.
- Prefer simple, single-purpose commands. For large files use `head -n 40` or `grep` rather than reading the whole file.
