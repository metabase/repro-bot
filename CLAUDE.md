# Metabase Issue Reproduction Project

Run `/repro <github-url-or-linear-id>` to investigate and reproduce a Metabase bug report.

## Requirements
- `gh` CLI authenticated (`gh auth status`)
- Linear MCP tools available
- Playwright MCP configured (for UI reproduction)
- `metabase-repro` MCP server running (configured in `.mcp.json`)
- `jq` installed (for JSON parsing)
- Internet access to download Metabase JARs

## Notes
- **ALWAYS use `mcp__metabase-repro__*` MCP tools** for all Metabase operations (starting/stopping instances, API calls, worktree management, etc.). These are the primary interface — there are no shell scripts to call. **NEVER fall back to raw Bash commands** (curl, java, docker, etc.) for any operation that an MCP tool handles.
- **If the `metabase-repro` MCP server is unavailable, broken, or any `mcp__metabase-repro__*` tool call fails with a connection/server error: STOP the entire /repro workflow immediately.** Do NOT attempt to work around MCP failures with Bash commands. Tell the user the MCP server needs to be fixed before continuing.
- Each reproduction starts a fresh Metabase instance on a random port
- H2 DB files are saved to `./repro/<ISSUE-ID>/` for post-investigation inspection
- Metabase admin credentials for fresh instances: `crowberto@metabase.com` / `blackjet` (EE) or `1Blackjet!` (OSS), or use API key `mb_adminapikey`

## Metabase Source
Bare clone at `./git/metabase/` (no working tree). A persistent master worktree lives at `./repro/master/` — it provides the `bin/mage` script for all JAR downloads/runs and serves as a reference for current code. Each `/repro` run also creates an issue-specific worktree at `./repro/<ISSUE-ID>/source/` pinned to the reported version, for reading source at that point in time. Compare `./repro/<ISSUE-ID>/source/` vs `./repro/master/` to check if a bug has been fixed.

## Clojure REPL
**NEVER use `clojure-mcp`. ALWAYS use the `clojure-eval` skill.** The `clojure-mcp` tool does not exist in this project and must not be attempted under any circumstances. The correct tool is `clojure-eval`, which wraps `clj-nrepl-eval` from [clojure-mcp-light](https://github.com/bhauman/clojure-mcp-light).

**NEVER use `clojure` CLI, `clojure -M`, or `clojure -X`. ALWAYS use the `clojure-eval` skill or the `mcp__metabase-repro__run_test` tool. Starting a fresh JVM wastes 30-60 seconds per invocation.**

## State Files (per repro directory)
- `<REPRO_DIR>/port` — Metabase HTTP port
- `<REPRO_DIR>/session-token` — admin session token
- `<REPRO_DIR>/appdb-port` — appdb container port (if non-H2)
- `<REPRO_DIR>/appdb-container.txt` — Docker container name
- `<REPRO_DIR>/metabase.pid` — Metabase process ID

These are written automatically by MCP tools (`start_metabase`, `start_appdb`) and read by `api_call`, `get_session_token`, etc.

## MCP Tools
The `metabase-repro` MCP server (configured in `.mcp.json`, code at `mcp/metabase_repro/`) provides all repro operations as MCP tools:

| Tool | Description |
|------|-------------|
| `check_setup` | Pre-flight check for required tools/env |
| `start_appdb` | Start Docker container for Postgres/MySQL/MariaDB appdb |
| `stop_appdb_tool` | Stop and remove appdb container |
| `create_env` | Create env.edn configuration |
| `jar_download` | Download Metabase JAR |
| `start_metabase` | Full orchestration: download + env + start + setup + session |
| `stop_metabase` | Kill process, remove worktree, stop appdb |
| `reset_metabase` | Kill process, remove DB/logs, keep env/worktree |
| `get_session_token` | Obtain/refresh admin session token |
| `check_setup_token` | Check if instance needs initial setup |
| `api_call` | Authenticated Metabase API call |
| `setup_master_worktree` | Create/update repro/master worktree |
| `setup_worktree` | Create issue-specific source worktree |
| `save_test_patch` | Generate diff of test changes as patch |
| `run_test` | Run Clojure/Jest/Cypress tests |
| `get_status` | Show all running repro instances |

## Scratch Files
Each investigation writes to `./repro/<ISSUE-ID>/scratch.md` (ephemeral, not committed).
