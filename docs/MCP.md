# Drift Detector — MCP server (read facade)

A **read-only MCP server** over the artifacts a scan produces (`inventory.json`, `audit.json`)
plus two **live checks**. It lets any MCP host — Claude Code, Claude Desktop, Cursor, Copilot
agents — query your integration data on demand. No LLM tokens in the server itself.

## Why
The deterministic pipeline writes the data; this lets assistants **read** it — and, crucially,
**prevent drift at generation time**: an assistant about to add `axios@0.21.1` or `php:7.4` calls
`check_dependency` / `check_runtime` first, sees it's vulnerable/EOL, and never writes it.

## Tools
| Tool | Args | Returns |
|---|---|---|
| `list_repos` | — | repos + their APIs / runtimes / package counts |
| `query_integrations` | `vendor?`, `repo?` | who calls a vendor / what a repo calls, with `file:line` |
| `get_findings` | `repo?`, `status?` | audit findings (CVE / EOL / vendor-sunset) |
| `check_dependency` | `ecosystem`, `name`, `version` | **live** OSV check — is this exact version vulnerable? |
| `check_runtime` | `product`, `version` | **live** endoflife.date check |

`check_dependency` / `check_runtime` are the prevention tools; the rest read the artifacts.

## Prerequisite
`uv` (or python ≥ 3.11). `bin/drift-mcp` self-installs the MCP SDK into an isolated
`.venv-mcp` on first launch (the core plugin stays dependency-light).

## Wire it into a host
Point the server at a scanned folder's state dir. Replace `<PLUGIN>` with the plugin path
(`ls -d ~/.claude/plugins/cache/*/drift-detector` for the installed copy, or your repo checkout)
and `<FOLDER>` with the folder you scan.

**Claude Code** — a `.mcp.json` in your project:
```json
{
  "mcpServers": {
    "drift-detector": {
      "command": "<PLUGIN>/bin/drift-mcp",
      "args": ["--state", "<FOLDER>/.drift-detector"]
    }
  }
}
```

**Cursor** (`.cursor/mcp.json`) / **Claude Desktop** (`claude_desktop_config.json`) — same shape:
```json
{ "mcpServers": { "drift-detector": {
  "command": "<PLUGIN>/bin/drift-mcp",
  "args": ["--state", "<FOLDER>/.drift-detector"] } } }
```

Then in that host: *"which repos call Shopify?"*, *"is `laravel/framework:9` end-of-life?"*, or —
while coding — *"before I add this dependency, check it."*

## Note
MCP servers are **session-scoped** (they answer while the host is connected) — this is the
read/prevention facade, **not** the continuous guarantee. Keep the weekly `run` (cron/CI) for that.
