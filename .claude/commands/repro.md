# /repro — Metabase Issue Auto-Reproduction

Investigate and reproduce a Metabase bug report against a fresh, isolated Metabase instance. Post findings as a structured Linear comment.

**Input**: `$ARGUMENTS` — a GitHub issue URL or Linear ID.

**Usage**: `/repro <github-issue-url-or-linear-id>`

Examples:
- `/repro https://github.com/metabase/metabase/issues/12345`
- `/repro MB-12345`

## Rules
- **No commits**: The worktree is ephemeral — discard any source edits when the worktree is removed in Phase 7.
- **MCP tools only**: Use `mcp__metabase-repro__*` for ALL Metabase ops. Never raw Bash (curl, java, docker). `curl` is not available — use `api_call`. If any MCP tool fails (connection error OR output error like "auto-setup failed"), **STOP immediately** and report the exact error.
- **No clojure CLI**: Use `repl_eval` or `run_test`. Never `clojure -M/-X` (wastes 30-60s per invocation).
- **Local code search only**: Grep/Glob against `./repro/` worktrees. Never `gh search code`.
- **No subagents for code search**: Direct Grep (~100 tokens) vs subagent (50K-100K tokens).
- **Browser**: `playwright-cli` via Bash. Never `mcp__playwright__*`. See `.claude/skills/playwright-cli/SKILL.md`.
- **Linear**: Call `mcp__linear-server__*` tools directly, not via subagents (subagents can't access MCP tools).
- **No web search**: Never use WebSearch/WebFetch for issue details. All data from `gh` CLI or Linear MCP.
- **File reads**: Read whole files or large 500+ line chunks — never scan in 60-line windows. Anti-pattern: reading the same file 5+ times with small offsets. Read the whole file once.
- **File searches**: Never search outside `./repro/`. Never `find /` or search the home directory.
- **Git commands**: Use `git -C <path>` instead of `cd <path> && git ...`.
- **Parallelism**: ALWAYS batch independent tool calls in the same turn. Saves 30%+ on turns. Common parallel batches: multiple Grep calls, `git log` + `git show`, independent `repl_eval` calls, `setup_worktree` + `start_appdb`.
- **No `wait-for-selector`**: `playwright-cli` does NOT have a `wait-for-selector` command. Use `snapshot` + `click` instead.
- **Time budget**: ~25 min total. Prioritize reproduction over exploration.

> **MCP tool schemas**: At the **start of the run**, pre-fetch all MCP tool schemas in a single `ToolSearch` call: `select:mcp__metabase-repro__check_setup,mcp__metabase-repro__setup_master_worktree,mcp__metabase-repro__setup_worktree,mcp__metabase-repro__start_appdb,mcp__metabase-repro__start_metabase,mcp__metabase-repro__stop_metabase,mcp__metabase-repro__api_call,mcp__metabase-repro__get_session_token,mcp__metabase-repro__repl_eval,mcp__metabase-repro__run_test,mcp__metabase-repro__save_test_patch,mcp__metabase-repro__cleanup,mcp__metabase-repro__get_status,mcp__metabase-repro__browser_snapshot,mcp__linear-server__list_issues,mcp__linear-server__list_comments,mcp__linear-server__get_issue,mcp__linear-server__save_comment,mcp__linear-server__save_issue,mcp__linear-server__list_issue_labels,mcp__linear-server__create_attachment`. Do NOT fetch schemas one-at-a-time.

> **CI mode**: When `GITHUB_ACTIONS_RUN_URL` is set, this runs in GitHub Actions CI. On catastrophic failure (MCP errors, startup failures, unrecoverable errors), post to Linear before stopping:
> ```markdown
> ## Repro-Bot CI Failure
> **Phase**: <phase number and name>
> **Error**: <exact error message>
> **CI Run**: [View logs](${GITHUB_ACTIONS_RUN_URL})
>
> <Additional context about what was attempted>
> ```
> If a Linear issue ID has been resolved, post to that issue. Otherwise log to console. SUGGESTIONS.md should still be written even if reproduction failed.

---

## Phase 0: Pre-flight Check

```
mcp__metabase-repro__check_setup()
```

If this fails with "No such tool available", wait 5 seconds and retry once. If it fails again, STOP: "The metabase-repro MCP server is not available." If it reports missing items, STOP — the user will fix before re-running.

Then verify playwright-cli:
```bash
playwright-cli --version
```
If missing, STOP: "Run `npm install -g @playwright/cli@latest && playwright-cli install --skills`."

---

## Phase 1: Input Routing

**GitHub URL** (`https://github.com/metabase/metabase/issues/\d+`):
```bash
gh issue view <ISSUE_NUM> --repo metabase/metabase --json number,title,body,labels,state
```
Then search Linear: `mcp__linear-server__list_issues` matching issue number or title keywords.

**Linear ID** (`[A-Z]+-\d+`):
```
mcp__linear-server__get_issue(id: "<LINEAR-ID>")
```
Linear syncs the full GitHub body — do NOT separately call `gh issue view`.

**Cross-link resolution**: Resolve both GitHub and Linear identifiers before proceeding.

> **REQUIRED**: A linked Linear issue is **mandatory**. If none found, STOP: "No linked Linear issue found. Please create or link one before running /repro." In CI mode, log to console.

**Fetch all comments** (Linear mirrors GitHub comments):
```
mcp__linear-server__list_comments(issueId: "<LINEAR-ID>")
```
IMPORTANT: Ignore previous Repro-Bot Investigation comments.

---

## Phase 2: Issue Parsing

Extract from the issue body and all Linear comments:
- Steps to reproduce, expected vs. actual behavior
- Version info (e.g. "Metabase 1.50.2", "v0.50.2", "version 50")
- Stack traces, API endpoints, DB driver specifics
- Workarounds, developer notes hinting at root cause

**Classify**:
- **Frontend-heavy**: UI elements, screenshots → primary: Playwright
- **Backend-heavy**: stack traces, SQL, data correctness → primary: REPL or API
- **Mixed**: use both
- **Upgrade/conversion**: version switch → see Phase 4

**Detect appdb type** (default: Postgres):
- **H2 only if**: issue explicitly mentions H2/embedded database/MB_DB_TYPE=h2
- **MySQL/MariaDB only if**: issue explicitly mentions as appdb
- Distinguish **appdb** (Metabase metadata) from **data warehouse** (user data)

**External system dependencies**: If the issue needs infrastructure beyond a local Metabase (remote DBs as data warehouse, LDAP/SAML, SMTP, S3, etc.), skip to Phase 6 with INCONCLUSIVE. **Not blockers**: Postgres/MySQL/MariaDB as appdb (supported via Docker).

> **Exception**: If external system is only needed for timing conditions (e.g. `pg_sleep`), proceed with code analysis. Can be REPRODUCED via code analysis if root cause is identifiable from source.

---

## Phase 3: Start Fresh Metabase Instance

### Set Up Master Worktree
```
mcp__metabase-repro__setup_master_worktree()
```

### Determine Version

| Issue says | Pass to tools | What happens |
|------------|-------------|--------------|
| `v1.50.2` or `1.50.2` | `1.50.2` | Downloads EE v1.50.2 |
| `v0.50.2` or `0.50.2` | `0.50.2` | Downloads OSS v0.50.2 |
| `version 50` or `50` | `50` | Queries GitHub for latest `1.50.x` EE |
| No version | *latest stable* | `gh release list --repo metabase/metabase -L 5` → use latest `v1.x.y`. Never `master`. |

Default to **EE** (`1.x.y`). Use **OSS** (`0.x.y`) only if issue says "OSS" or uses `v0.x.y`.

### Set Up Worktree and Appdb

```
mcp__metabase-repro__setup_worktree(repro_dir="repro/<ISSUE-ID>", version_ref="v1.50.2")
```

`setup_worktree` auto-normalizes EE→OSS tags and fetches missing tags.

**Default (Postgres)**: Start appdb then create env:
```
mcp__metabase-repro__start_appdb(repro_dir="repro/<ISSUE-ID>", db_type="postgres")
mcp__metabase-repro__create_env(repro_dir="repro/<ISSUE-ID>", db_type="postgres")
```

**H2**: Skip `start_appdb` — env is created automatically by `start_metabase`.

### Start Metabase

> **IMPORTANT**: `setup_worktree` MUST complete before `start_metabase` so test/dev
> namespaces are on the classpath. Do NOT parallelize these two calls.

```
mcp__metabase-repro__start_metabase(repro_dir="repro/<ISSUE-ID>", version="<VERSION>")
```

Output includes: edition, port, credentials, session token, nREPL port. Never use `java -jar` directly.

### Verify REPL
```
mcp__metabase-repro__repl_eval(repro_dir="repro/<ISSUE-ID>", code="(+ 1 2 3)")
```
Expected: `6`.

### Pre-Configured Users

**EE** (`1.x.y`): `crowberto@metabase.com` / `blackjet` (admin), `rasta@metabase.com` / `blueberries` (user). API keys: `mb_adminapikey`, `mb_userapikey`.

**OSS** (`0.x.y`): `crowberto@metabase.com` / `1Blackjet!` (admin). No API keys.

If setup seems wrong: `check_setup_token`. If token expires: `get_session_token`.

---

## Phase 4: Reproduction (max 3 attempts)

> **Primary goal**: Reproduce (or confirm not reproducible) the reported behavior. Root cause is nice-to-have — don't spend more than ~5 extra minutes on it.

Invoke the `metabase-reference` skill for REPL recipes, API patterns, domain quirks, and edge case handling.

### Strategy Selection

| Issue Type | Primary Strategy |
|------------|-----------------|
| UI / frontend behavior | **playwright-cli** + **REPL** for data setup |
| Setup steps in issue | **REPL** for data setup, **Playwright** for UI verification |
| API / endpoint behavior | **REPL** (invoke handlers directly) or MCP `api_call` (note: `path` should NOT include `/api/` — it's prepended automatically, e.g. `path="/collection/root"`) |
| Query results / SQL generation | **REPL**: `qp/process-query` or `qp.compile/compile` |
| Wrong data / DB state | **REPL**: `t2/select` to inspect |
| Permissions / auth flows | **REPL** + **Playwright** |
| Code logic / edge case | **REPL**: read source then invoke functions |
| Checking if fixed | Compare source + **REPL** to test both versions |

> **Code analysis budget**: When investigating via code analysis, compare the buggy version's source with master in at most 10-12 targeted file reads. Do NOT trace full git history — if the bug is clear from source comparison, that's sufficient evidence. Save git archaeology for ambiguous cases.

> **Backend bugs**: For backend-classified bugs, limit Playwright to 1-2 screenshots for evidence. Do NOT iterate on UI reproduction if REPL already confirmed the bug.

> **Timing / race-condition bugs**: If reproduction requires simulating slow API responses or race conditions that can't be triggered locally, proceed with code analysis. Note in report that root cause is confirmed via code review but not empirically observable in a single-instance environment.

> **Time-series bugs**: Test at multiple data densities: ~12 points (monthly/1yr), ~36 (monthly/3yr), ~60 (monthly/5yr). Bug often manifests at specific density where ECharts switches interval logic.

### Upgrade / Version-Switch Scenarios

1. Start initial version via `start_metabase`, set up state
2. Note the port, `stop_metabase(repro_dir="repro/<ISSUE-ID>")`
3. `start_metabase(repro_dir="repro/<ISSUE-ID>", version="<NEW>", port=<SAME>)`
4. Metabase runs migrations automatically. Repeat to switch multiple times.

### Browser Automation (playwright-cli)

**Token reduction rules**:
- Create questions/dashboards/data via API or REPL — NEVER use Playwright for creation UIs
- Navigate directly to `/question/<ID>` or `/dashboard/<ID>`
- **Snapshot via MCP tool**: Use `mcp__metabase-repro__browser_snapshot(repro_dir="repro/<ISSUE-ID>", name="descriptive-name")` instead of `playwright-cli snapshot` via Bash. The MCP tool saves full YAML to file and returns only a compact summary with interactive element refs — keeping large YAML out of context. Use `Read` on the saved YAML file when you need full page structure. NEVER use `playwright-cli snapshot` directly via Bash. NEVER snapshot pivot tables, large data views, or home page.
- NEVER use `&` (background) with playwright-cli

**Login and navigate** (use port from `start_metabase`):
```bash
playwright-cli open http://localhost:<PORT>/auth/login
playwright-cli cookie-set metabase.SESSION "<session-token>" --domain=localhost
playwright-cli goto http://localhost:<PORT>/question/1
playwright-cli screenshot --filename=./repro/<ISSUE-ID>/playwright/screenshot.png
```

Get session token from `get_session_token` or read `./repro/<ISSUE-ID>/session-token`.

> **"Start exploring" modal**: Metabase shows this on first native question view. Snapshot to find button ref and click to dismiss.

> **Chart interaction**: Hover on the img element ref from snapshot for tooltips. Check bottom of snapshot YAML for tooltip table rows.

> **playwright-cli single expressions**: `run-code` takes one expression — no semicolons. Use separate calls or shell `&&`.

> **playwright-cli resize**: Use `playwright-cli resize <w> <h>`, not `run-code` with `page.setViewportSize()`.

> **playwright-cli network**: `network` accumulates ALL requests since page load, not just recent ones. Output grows over time.

### REPL Access (repl_eval MCP tool)

The REPL is the **primary investigation tool**. After a timeout, skip arithmetic pings — just send your next command.

```
mcp__metabase-repro__repl_eval(repro_dir="repro/<ISSUE-ID>", code="(require '[toucan2.core :as t2]) (t2/count :model/Database)")
```

**REPL expression rules**: Send one expression per `repl_eval` call. Multi-expression evals frequently timeout. Split into separate (parallel if independent) calls.

Test/dev namespaces (`metabase.test`, `dev`, enterprise test namespaces) are available natively on the classpath — no manual setup needed.

> **REPL-first**: Prefer REPL over API calls for data setup and state inspection. Use API only when testing the HTTP layer.

> **Multi-schema setup**: If bug involves a picker that auto-hides with one schema (look for `useAutoSelectOnlyItem`), register the Postgres appdb as data warehouse via `POST /api/database`, then use REPL + `next.jdbc` to create schemas/tables.

> **CSV upload limitation**: `api_call` doesn't support multipart. Simulate uploads via REPL + `next.jdbc`.

> **Source worktree path**: Source code is at `./repro/<ISSUE-ID>/source/` (NOT `./repro/<ISSUE-ID>/`). The repro dir contains DB, logs, env, screenshots.

> **Codebase guidance**: Both `./repro/<ISSUE-ID>/source/` and `./repro/master/` contain a `CLAUDE.md` with instructions for navigating the Metabase codebase.

### Documentation Reference

```
WebFetch https://www.metabase.com/docs/latest/<relevant-section>
```

### After Each Attempt

Evaluate: what was tested, actual result, whether it matches reported behavior. Self-critique: "Did I test the right thing?"

> **Code analysis as reproduction**: If the defective code path is unambiguously identified in source AND either (a) a fix exists in a newer version, or (b) the logic error is self-evident, classify as REPRODUCED (via code analysis). Note in the report that reproduction was via source review, not live testing.

**Stop when**: REPRODUCED, NOT REPRODUCED, or after 3 inconclusive attempts → INCONCLUSIVE.

---

## Phase 5: Write Failing Test

> **Gate**: Only if status is REPRODUCED. Otherwise skip to Phase 6.

Invoke the `write-test` skill. Continue to Phase 6 after completion.

---

## Phase 6: Report & Post

### Classification

- **REPRODUCED** — reported behavior was observed
- **NOT REPRODUCED** — instance behaved correctly
- **INCONCLUSIVE** — environment constraints, missing driver, etc.

### Compose Linear Comment

```markdown
## Repro-Bot Investigation

**Status**: REPRODUCED / NOT REPRODUCED / INCONCLUSIVE
**Metabase Version**: <version tested>
**Application Database**: H2 / Postgres / MySQL / MariaDB

### Summary
<1-2 sentences>

### Reproduction Method
<Browser UI / API call / REPL / Code analysis — brief description>

### Key Findings
- <up to 5 bullets>

### Evidence
<Most relevant: API response, REPL output, or screenshot description>

### Root Cause Hypothesis (if identified)
<If REPRODUCED and clear: likely cause>
<If unclear: "Root cause not determined — reproduction steps above demonstrate the bug.">
<If NOT REPRODUCED: why it may work locally but fail in reported environment>
<If INCONCLUSIVE: what additional setup needed>

### Failing Test
<If written: describe test, file, confirm it fails. Note patch attached.>
<If not: explain why>

### Attempts
| # | Approach | Hypothesis | Result |
|---|----------|-----------|--------|
| 1 | ... | ... | ... |

### Approaches Not Tried
<List skipped approaches with reasons. Omit if all were attempted.>

### Next Steps
- <up to 3 actionable items>
```

### Post to Linear

> **IMPORTANT**: Do NOT sync to GitHub. Prefix with `[internal]` to prevent mirroring.

```
mcp__linear-server__save_comment(issueId: "<LINEAR-ID>", body: "<comment body>")
```

### Label the Issue

| Status | Label |
|--------|-------|
| REPRODUCED | `.Auto Repro Success` |
| NOT REPRODUCED | `.Auto Repro Failed` |
| INCONCLUSIVE | `.Auto Repro Inconclusive` |

The `labels` parameter REPLACES all labels — always include existing labels. Use the **exact full label names** above (e.g. `.Auto Repro Success`, NOT `.Auto Repro`). Fetch labels **once** with `list_issue_labels` at the start of Phase 6. Do not re-fetch — do NOT retry with partial names or variations if denied.

If a Playwright screenshot was captured, describe it in the comment. Do NOT attach via `create_attachment` with base64 (known to fail).

If `./repro/<ISSUE-ID>/test-diff.patch` exists, attach:
```
mcp__linear-server__create_attachment(
  issue: "<LINEAR-ID>",
  base64Content: "<base64 of test-diff.patch>",
  filename: "<ISSUE-ID>-failing-test.patch",
  contentType: "text/x-patch",
  title: "Failing test patch"
)
```

### CI Run Link

If `GITHUB_ACTIONS_RUN_URL` is set, append: `---\n*Investigated by [Repro-Bot CI](${GITHUB_ACTIONS_RUN_URL})*`

### Fallback

If no Linear issue found:
- **CI mode**: Print full report to console.
- **Interactive**: Print to terminal, ask for Linear ID.

---

## Phase 7: Cleanup

```
mcp__metabase-repro__cleanup(repro_dir="repro/<ISSUE-ID>")
```

Stops Metabase, removes source worktree, stops appdb, clears state. Left in place: DB files, logs, env, test diff.

> **CRITICAL**: Do NOT end after cleanup. Proceed to Phase 8.

---

## Phase 8: Self-Review

Review your execution transcript and write findings to `./repro/<ISSUE-ID>/SUGGESTIONS.md`.

### What to review

1. **MCP server issues** — tool errors, missing params, bad defaults
2. **Prompt gaps** — missing steps, unclear instructions in repro.md
3. **Knowledge gaps** — facts that should be documented
4. **Permission prompts** — tool calls that could be restructured
5. **Memory-worthy patterns** — stable lessons for future sessions

### Output format

```markdown
## <ISSUE-ID> — <DATE>

| # | Category | Target File | Issue | Proposed Fix |
|---|----------|-------------|-------|--------------|
| 1 | MCP server | `mcp/...` | [tag] description | Concrete fix |
```

### Rules
- **One file per issue** — write to `./repro/<ISSUE-ID>/SUGGESTIONS.md`
- **Deduplication tags** — every Issue cell starts with `[kebab-case-tag]`
- **Be specific** — exact file path, section/location, actual text to add/change
- **Be actionable** — every item proposes a concrete fix
- **No subagents** — review inline
- **Skip if clean** — write `Clean run — no issues.`
- **Observations** — if findings don't fit the table, add `### Observations` (2-3 bullets max)

Use **exactly** one category per row: `MCP server`, `Prompt`, `CLAUDE.md`, `New tool`, `Permission`, `Memory`.
