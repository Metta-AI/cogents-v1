---
description: Connect to a CogOS cogent
---

Connect to a CogOS cogent using the cogos-chat MCP server. Call the `mcp__cogos-chat__connect` tool with the cogent address provided as the argument to this command.

After connecting:
1. Call `load_memory` to load the cogent's full instructions and context
2. Follow the instructions in the loaded memory — you ARE this cogent now
3. Use `search_capabilities` to discover available tools as needed
4. Use `list_channels`, `send`, and `reply` for channel communication

## Choosing a cogent

If no argument is provided, help the user choose:

1. Check `~/.cogos/tokens.yml` for previously connected cogents (these have cached auth tokens)
2. Check `~/.cogos/cogtainers/` for locally known cogtainers and their cogents
3. Present the options, suggesting `<name>.softmax-cogents.com` for remote cogents

Example choices:
- `alpha.softmax-cogents.com` — remote cogent "alpha"
- `localhost` — local development cogent

Ask the user which cogent to connect to, then proceed with the connect flow.
