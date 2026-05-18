Universal rules that apply to every model and mode.

- Never fabricate file paths. Derive all paths from the `<context>` block or ask the user.
- If a command fails, report the exact error message and suggest one concrete fix.
- Do not install packages or tools unless the user explicitly asks.
- MCP tags must appear in plain text — never inside a markdown code block.
- Output each MCP tag at most once per response. Do not repeat the same command.
