# `@deepseek-harness/mcp`

MCP server exposing DeepSeek V4-Pro / V4-Flash with all 10 protocol contract rules enforced. Drop into Claude Desktop, Cursor, Cline, Roo Code, ChatWise, Cherry Studio, or any MCP-aware client.

```bash
npx -y @deepseek-harness/mcp
```

## Wire it up

### Claude Desktop / Cursor / Cline / Roo Code

Add to your MCP config (`~/.config/Claude/claude_desktop_config.json`, Cursor settings → MCP, Cline `cline_mcp_settings.json`, etc.):

```json
{
  "mcpServers": {
    "deepseek-harness": {
      "command": "npx",
      "args": ["-y", "@deepseek-harness/mcp"],
      "env": { "DEEPSEEK_API_KEY": "sk-..." }
    }
  }
}
```

### ChatWise / Cherry Studio

Settings → MCP Servers → Add → command: `npx -y @deepseek-harness/mcp` · env: `DEEPSEEK_API_KEY=sk-...`

## Tools exposed (4)

| name | what it does | API call? |
|---|---|---|
| `deepseek_chat` | Non-streaming chat completion with all guards on | yes |
| `deepseek_chat_stream` | Streaming completion, server-side aggregated to one final message | yes |
| `validate_message_history` | Pre-flight contract audit on `messages[]` | **no** (zero cost) |
| `estimate_cache_hit` | Pre-flight cache hit estimator | **no** (zero cost) |

## Why this MCP server vs raw DeepSeek

DeepSeek V4 ships with [16 documented protocol quirks](https://github.com/HenryZ838978/deepseek-harness/tree/main/reports). This MCP server enforces all of them so you don't have to:

- thinking auto-disabled (saves 30-300 reasoning tokens per call)
- `max_tokens` always set (prevents reasoning-runaway → V8 `Invalid string length`)
- multi-turn `reasoning_content` preserved (avoids the documented 400)
- streaming chunks aggregated correctly (parallel tool interleave + empty chunks tolerated)
- cache hit fields normalised across DeepSeek-native and OpenAI-shape

## Build from source

```bash
cd packages/mcp
npm install
npm run build
node dist/index.js   # or `npm start`
```

License: MIT.
