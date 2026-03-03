# Repro Bot

A Claude Code-powered tool for triaging Metabase bug reports. Given an issue URL, it spins up a fresh Metabase instance, attempts to reproduce the bug, and posts a structured investigation report to Linear.

## Usage

In Claude Code, run against a linear ID (don't need plan mode):

```
/repro UXW-1234
```

It also works with github issues:

```
/repro https://github.com/metabase/metabase/issues/12345
```

The bot handles everything from there — downloading the right Metabase version, starting an instance, reproducing the bug, and posting results.

## What It Does

1. Fetches the issue from GitHub/Linear and extracts repro steps, version, and environment info
2. Downloads the matching Metabase JAR and starts a fresh instance on a random port
3. Attempts reproduction (up to 3 tries) using browser automation (Playwright), Clojure REPL, and/or API calls
4. If reproduced, writes a minimal failing test and generates a patch file
5. Posts a report to Linear with status: **REPRODUCED**, **NOT REPRODUCED**, or **INCONCLUSIVE**
6. Cleans up the instance, keeping logs and DB for inspection

## Setup

### Prerequisites

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code)
- [`gh` CLI](https://cli.github.com/) — authenticated (`gh auth status`)
- [`uv`](https://docs.astral.sh/uv/) — runs the MCP server
- [`jq`](https://jqlang.github.io/jq/)
- Java 11+
- [Docker](https://www.docker.com/) — only needed for non-H2 application database issues

### MCP Servers

The bot relies on three MCP servers, configured in `.mcp.json`:

- **metabase-repro** — manages Metabase instances, API calls, worktrees, and test running (code in `mcp/metabase_repro/`)
- **Linear** — reads/writes issues and comments
- **Playwright** — browser automation for UI reproduction

### Initial Setup

Clone the Metabase repo as a bare clone (no working tree):

```bash
git clone --bare https://github.com/metabase/metabase.git git/metabase
```

The first `/repro` run will create a persistent `repro/master/` worktree automatically.

## Project Layout

```
├── .claude/commands/repro.md   # The /repro slash command
├── mcp/metabase_repro/         # MCP server for Metabase operations
├── git/metabase/               # Bare clone of metabase/metabase
├── downloads/                  # Cached Metabase JARs
├── plugins/                    # Metabase driver plugins
└── repro/
    ├── master/                 # Persistent worktree (current main branch)
    └── <ISSUE-ID>/            # Per-issue working directory
        ├── source/             # Git worktree at the reported version
        ├── metabase.log        # Server log
        ├── metabase.mv.db     # H2 database (preserved after cleanup)
        ├── env.edn             # Instance config
        ├── test-diff.patch    # Failing test patch (if generated)
        ├── playwright/         # Screenshots
        └── SUGGESTIONS.md     # Self-review notes
```

## SUGGESTIONS.md

At the end of each run, it will save a SUGGESTIONS.md file to the repro subdirectory to help improve the bot over time.

If your run had a particularly challenging time on an issue, ask claude to improve it's CLAUDE.md or repro.md or MCP server based on what problems it had.

Periodically, we should ask claude to look at those suggestions in aggregate to determine ways to improve performance and reduce token usage.