# /auto-improve - Make Future Repros Better

Analyze past reproduction runs and implement concrete improvements to the repro workflow.

## Step 1: Gather Input from SUGGESTIONS.md Files

Glob for `repro/*/SUGGESTIONS.md` and read **all** of them. These are the structured output from Phase 8 of each repro run — already distilled and actionable.

**Do NOT read raw transcripts (.jsonl).** SUGGESTIONS.md already extracts the signal. Only reference transcripts if a specific SUGGESTIONS.md item is unclear and needs more context.

## Step 2: Categorize Findings

Sort each suggestion into one of these buckets:

| Category | Files affected | Examples |
|----------|---------------|----------|
| **MCP server bugs/improvements** | `mcp/metabase_repro/*.py` | Tool errors, missing params, bad defaults, unhelpful error messages |
| **Prompt/command improvements** | `.claude/commands/repro.md` | Missing steps, unclear instructions, wrong ordering, missing edge cases |
| **CLAUDE.md knowledge gaps** | `CLAUDE.md` | Facts Claude should know but doesn't (e.g., H2 timezone limits, version tag formats, socket REPL vs nREPL) |
| **New MCP tools needed** | `mcp/metabase_repro/*.py`, `mcp/metabase_repro/server.py` | Functionality gaps that cause fallback to raw Bash commands |
| **Permission/workflow issues** | Various | Actions that trigger unnecessary user prompts, sandbox violations |
| **Memory updates** | `memory/*.md` | Stable patterns or lessons learned that should persist across sessions |

## Step 3: Deduplicate and Prioritize

- Count how many runs hit the **same issue** (look for similar suggestions across different SUGGESTIONS.md files)
- Estimate **token waste per occurrence** (e.g., a retry loop wastes ~500 tokens each time; reading a huge file wastes thousands)
- Rank by: `frequency × waste per occurrence`
- Focus on the top items — don't try to fix everything in one pass

## Step 4: Enter Plan Mode

Enter plan mode and present a concrete implementation plan:

- Group changes **by file**
- Include **specific code snippets** or text additions (not vague descriptions)
- Include **verification steps** (how to confirm each change works)
- Call out any changes that might affect existing repro behavior

## Step 5: Implement Changes

After plan approval, implement the changes. Test MCP server changes where possible.

## Step 6: Mark Suggestions as Addressed

After implementation, append a status line to each processed `SUGGESTIONS.md`:

```
---
**Auto-improve run (YYYY-MM-DD):** Addressed items: <list of fixed items>. Remaining: <list of deferred items>.
```

## Step 7: Update Memory

Write any stable patterns or lessons to memory files (`/Users/nvoxland/.claude/projects/-Users-nvoxland-src-metabase-auto-recreate/memory/`) so future sessions benefit. Only write things confirmed across multiple runs — not one-off observations.
