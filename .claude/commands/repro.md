# /repro — Metabase Issue Auto-Reproduction

Investigate and reproduce a Metabase bug report against a fresh, isolated Metabase instance. Post findings as a structured Linear comment.

**Input**: `$ARGUMENTS` — a GitHub issue URL or Linear ID.

**Usage**: `/repro <github-issue-url-or-linear-id>`

Examples:
- `/repro https://github.com/metabase/metabase/issues/12345`
- `/repro MB-12345`

> **Note**: Do not commit any changes. The worktree is ephemeral — any source edits made during investigation (e.g. adding debug logging) should be discarded when the worktree is removed in Phase 7.

> **CRITICAL**: Use `mcp__metabase-repro__*` MCP tools for ALL Metabase operations (starting/stopping instances, API calls, worktree management, test running). These tools handle state management, authentication, and process lifecycle automatically — no shell scripts needed. **NEVER fall back to raw Bash** (curl, java -jar, docker run, etc.) for any operation that an MCP tool handles. `curl` is not available — use the `api_call` MCP tool for all Metabase API requests. If any `mcp__metabase-repro__*` tool fails — whether with a connection/server error OR an error in its output (e.g. "auto-setup failed", "could not obtain session token") — **STOP the entire /repro workflow immediately** and report the exact error to the user so the MCP server code can be fixed. Do NOT attempt to work around MCP tool failures with manual curl/bash commands.

> **Browser automation**: Use `playwright-cli` (installed as a Claude Code skill) for all browser automation. Run commands via the Bash tool (e.g. `playwright-cli goto https://...`). Do NOT use playwright-cli tools (`mcp__playwright__*`) — they are not configured. See the skill documentation at `.claude/skills/playwright-cli/SKILL.md` for the full command reference.

> **Tooling assumption**: The Linear MCP tools (`mcp__linear-server__*`) are already connected and authenticated. Call them directly from the main agent — do NOT delegate Linear MCP calls to subagents (Task tool), as subagents cannot access MCP tools. Do not search for a Linear CLI, check for API keys, or verify authentication. If a Linear MCP call fails, report the error and move on.

> **Source exploration**: NEVER use Task/Explore agents for code analysis. Use direct Grep calls — they cost ~100 tokens vs 50K-100K for a subagent. Start with targeted Grep searches (specific component/function names). Multiple sequential Grep calls are always cheaper than a single Explore agent.

> **File searches**: NEVER search outside the project directory. Always scope Grep/Glob/find to `./repro/` or specific subdirectories. Never use `find /` or search the home directory — it wastes turns and triggers permission prompts.

> **Code search**: ALWAYS search Metabase source code using Grep/Glob against local worktrees (`./repro/master/`, `./repro/<ISSUE-ID>/source/`). NEVER use `gh api search/code` or `gh search code` — these GitHub code search APIs are slow, rate-limited, and return incomplete results.

> **Time budget**: Aim to complete the entire workflow in **~25 minutes**. Prioritize reproduction over exploration — once the bug is reproduced (or confirmed not reproduced), move quickly to test writing and reporting. Do not spend time on deep root cause analysis, git history, migration archaeology, or alternate reproduction paths beyond what's needed to confirm the bug.

> **Git commands**: Use `git -C <path>` instead of `cd <path> && git ...` to avoid permission denials on directory changes.

> **MCP tool schemas**: When entering a new phase that needs MCP tools, batch-fetch all needed schemas in a single `ToolSearch` call (e.g., `select:tool1,tool2,tool3`) rather than fetching one at a time. Each ToolSearch round-trip costs 3 messages.

> **CI mode**: When the `GITHUB_ACTIONS_RUN_URL` environment variable is set, this workflow is running in GitHub Actions CI. In CI mode:
> - If **any phase fails catastrophically** (MCP tool errors, preflight failures, Metabase startup failures, or unrecoverable errors), post the error to Linear as an internal-only comment before stopping. The comment must include:
>   1. A summary of what failed and the exact error message
>   2. Which phase the failure occurred in
>   3. A link to the CI run: `[CI Run](${GITHUB_ACTIONS_RUN_URL})`
> - Use this format for CI failure comments:
>   ```markdown
>   ## Repro-Bot CI Failure
>   **Phase**: <phase number and name>
>   **Error**: <exact error message>
>   **CI Run**: [View logs](${GITHUB_ACTIONS_RUN_URL})
>
>   <Additional context about what was attempted>
>   ```
> - If a Linear issue ID has been resolved, post the failure comment to that issue. If not (e.g., failure happened before Linear resolution in Phase 1), log the error to the console — it will be captured in the CI run logs.
> - The SUGGESTIONS.md file should still be written (Phase 8) even if the reproduction failed, to capture what went wrong for `/auto-improve`.

---

## Phase 0: Pre-flight Check

Run this **before anything else** — before fetching issues, before any MCP calls. If it fails, stop immediately.

```
mcp__metabase-repro__check_setup()
```

If this tool call itself fails with "No such tool available", the MCP server may still be initializing. **Wait 5 seconds and retry once.** If it fails a second time with the same error, **STOP immediately** and tell the user: "The metabase-repro MCP server is not available. Please check `.mcp.json` and restart it before running /repro."

If it fails with a different error (connection refused, server crashed, etc.), **STOP immediately** with the same message — no retry needed.

If the check reports missing items, **STOP the entire /repro workflow immediately.** Do NOT continue to any subsequent steps. Do NOT attempt to diagnose, work around, or check individual components yourself — the user will fix the issue before re-running.

### Verify Playwright CLI

After pre-flight passes, verify `playwright-cli` is available by running:
```bash
playwright-cli --version
```

If this fails, **STOP immediately** and tell the user: "playwright-cli is not available. Run `npm install -g @playwright/cli@latest && playwright-cli install --skills` and restart before running /repro. Playwright is required for reproducing frontend issues."

Do NOT continue with a code-analysis-only approach — Playwright is a hard requirement.

---

## Phase 1: Input Routing

Determine input type and fetch issue data:

**GitHub URL** (matches `https://github.com/metabase/metabase/issues/\d+`):
```bash
gh issue view <ISSUE_NUM> --repo metabase/metabase --json number,title,body,labels,state
```
Then search Linear for the linked issue via `mcp__linear-server__list_issues`.

**Linear ID** (matches `[A-Z]+-\d+`, e.g. `MB-1234`):
```
mcp__linear-server__get_issue(id: "<LINEAR-ID>")
```
Linear already syncs the full GitHub issue body — do NOT separately call `gh issue view`. Just extract the GitHub URL from the Linear issue description or attachments for use in the final report.

**Cross-link resolution**:
- If starting from GitHub: search Linear for a linked issue via `mcp__linear-server__list_issues` with a query matching the GitHub issue number or title keywords. Also check the GitHub issue body/comments for a Linear link.
- If starting from Linear: extract the GitHub URL from the issue description or attachments. Do NOT fetch GitHub separately — Linear has all the content.

Resolve both GitHub and Linear identifiers before proceeding.

> **REQUIRED**: A linked Linear issue is **mandatory**. If no Linear issue can be found for the GitHub issue (no cross-link in the issue body/comments, and `list_issues` search returns no match), **STOP the entire /repro workflow immediately**. Tell the user: "No linked Linear issue found for this GitHub issue. Please create or link a Linear issue before running /repro — the investigation report must be posted to Linear." In CI mode, log this message to the console. Do NOT proceed to Phase 2 or beyond.

> **IMPORTANT**: NEVER use web search (WebSearch, WebFetch) to look up issue details. All issue data must come from the `gh` CLI (for GitHub) or Linear MCP tools (for Linear). If both fail, stop and report the error to the user — do not fall back to searching the web.

**Fetch all comments from Linear** (Linear mirrors GitHub comments, plus may have additional Linear-only comments):
```
mcp__linear-server__list_comments(issueId: "<LINEAR-ID>")
```
This is the primary source for all comment data — no need to separately fetch GitHub comments.

IMPORTANT: Do not consider anything from previous Repro-Bot Investigation comments.

---

## Phase 2: Issue Parsing

Extract from **the issue body and all Linear comments** (which include synced GitHub comments plus any Linear-only discussion):
- Steps to reproduce (comments may refine or correct the original steps)
- Expected vs. actual behavior
- Environment and version info (e.g. "Metabase 1.50.2", "v0.50.2", "version 50")
- Stack traces or API endpoints mentioned
- DB driver specifics (Postgres, MySQL, H2, etc.)
- Workarounds or additional context from comments
- Developer/maintainer notes hinting at root cause

**Classify the issue**:
- **Frontend-heavy**: mentions specific UI elements, screenshots only, no API/SQL → primary strategy: Playwright
- **Backend-heavy**: stack traces, SQL, query results, data correctness → primary strategy: REPL or API calls
- **Mixed**: use both
- **Upgrade/conversion**: bug occurs after upgrading between versions or switching between OSS and EE → version-switch strategy (see Phase 4)

**Detect application database requirements**: The default appdb is **Postgres** — it is what most people use and doesn't have limitations that H2 does. Scan the issue body and comments for explicit overrides:

- **Use H2 only if**: the issue explicitly mentions H2 (e.g., "H2 database", "using H2", "MB_DB_TYPE=h2", "embedded database", "default database")
- **Use MySQL/MariaDB only if**: the issue explicitly mentions MySQL or MariaDB as the application database (e.g., "MB_DB_TYPE=mysql", "MB_DB_TYPE=mariadb", "appdb is MySQL")

**Important**: Distinguish **application database** (where Metabase stores its own metadata) from **data warehouse** (databases users connect to query their data). Only appdb mentions trigger a change from the Postgres default. Data warehouse requirements remain blockers (see below).

Note the appdb type (postgres, h2, mysql, or mariadb) for Phase 3.

**Check for external system dependencies**: If the issue requires infrastructure beyond a local Metabase instance, **stop before attempting reproduction**. Post an INCONCLUSIVE report explaining what external systems are needed. Examples of blockers:
- Remote databases (Postgres, MySQL, BigQuery, Redshift, Snowflake, etc.) as the **data warehouse**
- LDAP / SAML / SSO identity providers
- SMTP mail server (for subscription/alert issues)
- Git-based serialization remote
- S3 or other object storage
- Specific Docker or Kubernetes setups
- Load balancers or reverse proxies

**NOT blockers** (supported via Docker):
- Postgres, MySQL, or MariaDB as the **application database** (appdb)

> **Exception**: If the external system is only needed to create timing conditions (e.g., `pg_sleep` for simulating slow queries), the issue may still be investigable via code analysis. Note the limitation and proceed to Phase 4. The issue can be REPRODUCED via code analysis if the root cause is identifiable from source code without requiring runtime timing verification.

Do not attempt to set up external data warehouses or other external systems. Skip directly to Phase 6 with status INCONCLUSIVE and note the required infrastructure.

---

## Phase 3: Start Fresh Metabase Instance

### Set Up Master Worktree

Ensure the persistent master worktree exists and is up to date. This provides the `bin/mage` script used for all JAR downloads/runs, and serves as a reference for comparing current code against the issue's version.

```
mcp__metabase-repro__setup_master_worktree()
```

### Determine Version

Determine the VERSION string to pass from the issue:

| Issue says | Pass to tools | What start_metabase does |
|------------|-------------|----------------|
| `v1.50.2` or `1.50.2` | `1.50.2` | Downloads EE v1.50.2 |
| `v0.50.2` or `0.50.2` | `0.50.2` | Downloads OSS v0.50.2 |
| `version 50` or just `50` | `50` | Queries GitHub releases for latest `1.50.x` EE |
| No version mentioned | *latest stable* | Query `gh release list --repo metabase/metabase -L 5` to find the latest `v1.x.y` release, then use that version number (e.g. `1.52.3`). Do NOT use `master` — master builds cannot be downloaded via `mage jar-download`. |

**Edition heuristic** (only needed when the issue says a bare version like "50" or "v50"):
- Default to **EE** (`1.x.y`) — `mage` does this automatically when given a bare number like `50`
- Use **OSS** (`0.x.y`) only if the issue explicitly mentions "OSS" or "open source" or uses a `v0.x.y` version

No manual git tag resolution is needed — mage handles it all.

### Set Up Isolated Repro Directory and Source Worktree

Each run gets a fresh git worktree. The worktree provides source code at the issue's version for reading/grepping during investigation. It does NOT compile Metabase.

```
mcp__metabase-repro__setup_worktree(repro_dir="repro/<ISSUE-ID>", version_ref="v1.50.2")
```

For `version_ref`, use the git tag matching the version (e.g. `v1.50.2`). If no version was specified in the issue, use the tag for the latest stable release.

> **Tag resolution**: `setup_worktree` auto-normalizes EE tags (`v1.x.y` → `v0.x.y`) and fetches missing tags automatically. No manual git fetch needed.

### Start Application Database

**Default (Postgres)** — unless a different appdb was explicitly requested in Phase 2:

```
mcp__metabase-repro__start_appdb(repro_dir="repro/<ISSUE-ID>", db_type="postgres")
```

Then create the env file:
```
mcp__metabase-repro__create_env(repro_dir="repro/<ISSUE-ID>", db_type="postgres")
```

**If MySQL/MariaDB was explicitly requested**: Call `start_appdb` and `create_env` with the appropriate `db_type` (`mysql` or `mariadb`).

**If H2 was explicitly requested**: Skip `start_appdb` — the env file is created automatically by `start_metabase`.

### Start Metabase

This single tool orchestrates everything: JAR download, env file creation (if not already done), startup, health check, auto-setup (EE/OSS), and session token acquisition.

```
mcp__metabase-repro__start_metabase(repro_dir="repro/<ISSUE-ID>", version="<VERSION>")
```

The tool output tells you:
- Edition (EE or OSS)
- Port number
- Credentials (crowberto@metabase.com / blackjet or 1Blackjet!)
- Session token

> **IMPORTANT**: Never try to start Metabase directly via `java -jar` as a fallback. The MCP tool handles env vars, config files, REPL port setup, and OSS auto-setup.

### Verify REPL Connection

After Metabase starts, verify the socket REPL is reachable using the `repl_eval` MCP tool:
```
mcp__metabase-repro__repl_eval(repro_dir="repro/<ISSUE-ID>", code="(+ 1 2 3)")
```
Expected: `6`. If it returns an error, check `./repro/<ISSUE-ID>/metabase.log` for errors.

### Pre-Configured Users and API Keys

**Check `start_metabase` output** to determine which setup path was used:

**EE jars** (version `1.x.y`) — `mage jar-download --run` uses a config file that auto-sets up:

| User | Password | Role |
|------|----------|------|
| `crowberto@metabase.com` | `blackjet` | Superuser (admin) |
| `rasta@metabase.com` | `blueberries` | Regular user |

Pre-created API keys: `mb_adminapikey` (admin), `mb_userapikey` (all-users).

**OSS jars** (version `0.x.y`) — auto-runs `/api/setup`:

| User | Password | Role |
|------|----------|------|
| `crowberto@metabase.com` | `1Blackjet!` | Superuser (admin) |

No pre-created API keys or secondary users for OSS. Use session token for API calls.

### Check Setup Token (if needed)

If you suspect the instance wasn't set up properly:
```
mcp__metabase-repro__check_setup_token(repro_dir="repro/<ISSUE-ID>")
```

### Refresh Session Token (if needed)

`start_metabase` automatically saves the session token. If it expires:
```
mcp__metabase-repro__get_session_token(repro_dir="repro/<ISSUE-ID>")
```

> Note: JAR download + first startup typically takes 1–3 minutes.

---

## Phase 4: Reproduction (max 3 attempts)

> **Primary goal**: Reproduce (or confirm not reproducible) the reported behavior. Root cause analysis is **nice to have** — do it if it falls out naturally from reproduction work or light code reading, but do NOT spend more than ~5 extra minutes on it. Once you can confirm REPRODUCED / NOT REPRODUCED / INCONCLUSIVE, move to Phase 5. Do NOT investigate migrations, DB internals, git history, or alternate reproduction paths beyond what's needed to confirm the bug.

Select strategy based on issue classification. Strategies can be combined within one attempt.

### Strategy Selection

| Issue Type | Primary Strategy |
|------------|-----------------|
| UI / frontend behavior | **playwright-cli** + **REPL** for data setup |
| Setup steps described in issue | **REPL** for data setup, **Playwright** for UI verification |
| API / endpoint behavior | **REPL** (invoke handler functions directly) or MCP `api_call` |
| Query results / SQL generation | **REPL**: `qp/process-query` or `qp.compile/compile` |
| Wrong data / DB state | **REPL**: `t2/select` to inspect, compare expected vs actual |
| Permissions / auth flows | **REPL**: inspect/modify permission groups + **Playwright** for UI |
| Data model / metadata | **REPL**: `t2/select-one :model/Table` |
| Code logic / edge case | **REPL**: read source then invoke functions directly |
| Checking if bug is fixed | Compare source + **REPL** to test both versions' behavior |

### Upgrade / Version-Switch Scenarios

If the issue involves upgrading between versions or converting between OSS and EE, you can start and stop different versions of Metabase against the same database:

1. **Start the initial version** normally via `start_metabase` — this creates the DB and sets up data
2. **Set up state** — create questions, dashboards, or whatever data the issue requires on the initial version
3. **Note the port** from `start_metabase` output — you'll reuse it
4. **Stop the process** (preserves the database, env, and worktree):
   ```
   mcp__metabase-repro__stop_metabase(repro_dir="repro/<ISSUE-ID>")
   ```
5. **Start the new version** with the same port to reuse the existing DB:
   ```
   mcp__metabase-repro__start_metabase(repro_dir="repro/<ISSUE-ID>", version="<NEW-VERSION>", port=<SAME-PORT>)
   ```
6. Metabase will run migrations automatically on startup if upgrading to a newer version

This works for:
- Upgrading from an older version to a newer one (e.g., 1.50.2 → 1.52.3)
- Downgrading (though Metabase may not support this cleanly)
- Switching between OSS (0.x.y) and EE (1.x.y) editions

You can repeat steps 3–5 to switch versions multiple times in a single investigation.

> **H2 slow query limitation**: H2 does not have `pg_sleep()`. For timing-dependent issues requiring slow queries, skip browser reproduction of the timing aspect and use code analysis instead. Cross-joins (e.g., `SYSTEM_RANGE(1,N) a, SYSTEM_RANGE(1,N) b`) are impractical for controlled delays in H2.

> **H2 reserved keywords**: H2 reserves `value`, `count`, `key`, `type` as SQL keywords — avoid using them as column aliases in native SQL test queries. Use `amount`, `qty`, `cnt`, etc. instead.

> **playwright-cli single expressions**: Each `playwright-cli run-code` call must contain a single expression — no semicolons between statements. Avoid async chaining with `.then()` — `run-code` only supports simple synchronous-looking expressions. For bounding box access or hover, use `playwright-cli hover <ref>` on known element refs instead. Use separate `run-code` calls, or chain with `&&` at the shell level.

> **REPL-first approach**: Prefer the REPL over API calls for data setup and state inspection. The REPL is faster (no HTTP overhead), more expressive (full Clojure), and gives direct access to internals. Use API calls only when testing the HTTP layer specifically. Use Playwright only for visual/UI verification.

> **Multi-schema setup**: If the bug involves a picker or component that auto-hides with only one schema/item (look for `useAutoSelectOnlyItem` in source), you need a multi-schema DB. Register the Postgres appdb as a data warehouse via `POST /api/database` with the same connection details, then use REPL + `next.jdbc` to `CREATE SCHEMA` and `CREATE TABLE` within it.

> **CSV upload / multipart limitation**: The `api_call` MCP tool does not support multipart form data, so CSV uploads via `POST /api/upload/csv` will not work. Instead, simulate uploads by creating the schema and table directly via REPL + `next.jdbc`.

> **Source worktree path**: The source code for the issue's version is at `./repro/<ISSUE-ID>/source/` (NOT `./repro/<ISSUE-ID>/`). The repro directory `./repro/<ISSUE-ID>/` contains H2 DB, logs, env file, and the `playwright/` screenshot directory — source is always in the `source/` subdirectory.

> **Codebase guidance**: Both `./repro/<ISSUE-ID>/source/` and `./repro/master/` contain a `CLAUDE.md` file with detailed instructions for navigating the Metabase codebase — read it when exploring source code. It documents conventions, key directories, and patterns that will help you find what you need faster.

### Browser Automation (playwright-cli)

Use `playwright-cli` via the Bash tool for all browser automation. After logging in, navigate directly to the target page — do NOT snapshot intermediate pages (home, browse) unless they're part of the reproduction.

**Token reduction rules**:
- **ALWAYS** create questions, dashboards, filters, and all data setup via API (`api_call` MCP tool) or REPL — NEVER use Playwright to navigate creation UIs (e.g. "New Question" flows). Reserve Playwright exclusively for the final UI interaction that demonstrates the bug. If you find yourself clicking through creation flows in Playwright, stop and switch to the API.
- Navigate directly to `/question/<ID>` or `/dashboard/<ID>` instead of clicking through menus
- **Snapshot only for interaction or proof**: Only use `playwright-cli snapshot` when you (a) need element refs to click/fill/hover, or (b) need to capture DOM state that proves the bug (e.g. tooltip content, accessibility tree issues). NEVER snapshot just to see where you are or verify navigation — use `playwright-cli screenshot` for that (fixed token cost). NEVER snapshot pivot tables, large data views, or the home page.
- When reading snapshot YAML, use the Read tool with `offset`/`limit` — full Metabase page YAMLs can be very large
- NEVER use `&` (background) operators with playwright-cli commands — they cause permission denials

**Commands** (use the port from `start_metabase` output):
```bash
# Login via session cookie (skip the login UI entirely — saves 3-4 tool calls)
playwright-cli open http://localhost:<PORT>/auth/login
playwright-cli cookie-set metabase.SESSION "<session-token>" --domain=localhost
playwright-cli goto http://localhost:<PORT>/question/1
# Take screenshot to verify page loaded / capture bug visually
playwright-cli screenshot --filename=./repro/<ISSUE-ID>/playwright/screenshot.png
# Only snapshot when you need element refs to interact with (click, fill, hover)
playwright-cli snapshot
playwright-cli fill <ref> "value"
playwright-cli click <ref>
# Close browser when done
playwright-cli close
```

Get the session token from the `get_session_token` MCP tool or read `./repro/<ISSUE-ID>/session-token`.

**Avoid snapshotting the home page**: The home page has a very large DOM. After cookie-based login, immediately `playwright-cli goto` the target URL (e.g. `/question/<ID>`, `/dashboard/<ID>`).

**"Start exploring" modal**: Metabase shows a "Start exploring" modal when viewing a saved native question for the first time. Be prepared for an extra click to dismiss it — snapshot to find the button ref and click it.

**Chart interaction**: Metabase charts (ECharts) render into a canvas/img element. To trigger tooltips, use `playwright-cli hover <ref>` on the img element ref from a snapshot — do NOT use `run-code` with `page.mouse.move()`. The tooltip content will appear in the subsequent `snapshot` call DOM — check the bottom of the YAML for table elements.

**Tooltip inspection via snapshot**: Tooltip content often appears at the bottom of the accessibility snapshot YAML as table elements, even if not visible in screenshots. Always check the full snapshot for tooltip table rows before attempting complex hover interactions.

### REPL Access (repl_eval MCP tool)

> **NEVER use `clojure` CLI, `clojure -M`, or `clojure -X`. ALWAYS use the `repl_eval` MCP tool or `mcp__metabase-repro__run_test`. Starting a fresh JVM wastes 30-60 seconds per invocation.**

The REPL is the **primary investigation tool** — prefer it over API calls for data setup, state inspection, and root cause exploration. After a REPL timeout, do NOT send arithmetic pings like `(+ 1 1)` — just send your next real command. Use the `repl_eval` MCP tool which connects directly to the socket REPL:

```
mcp__metabase-repro__repl_eval(repro_dir="repro/<ISSUE-ID>", code="(require '[toucan2.core :as t2]) (t2/count :model/Database)")
```

**When to use the REPL**:
- **Before any API call**: Consider if the REPL is faster/more direct
- **Data setup**: Use `t2/insert!` to create test data rather than clicking through UI
- **State inspection**: Use `t2/select` to verify DB state after UI actions
- **Query testing**: Use `qp/process-query` to test queries directly
- **Root cause exploration**: Evaluate suspect functions with test inputs
- **Environment modification**: Change settings, toggle features, modify data on-the-fly

**Important**: The JAR runs production namespaces only. Test/dev namespaces (`metabase.test`, `dev`) are NOT on the classpath by default. Production namespaces available out of the box:
- `toucan2.core` (as `t2`) — DB queries: `t2/select`, `t2/select-one`, `t2/insert!`
- `metabase.query-processor` (as `qp`) — run queries end-to-end
- `metabase.query-processor.compile` (as `qp.compile`) — compile to SQL only

### Common REPL Recipes

**Inspect database schema/tables**:
```clojure
(t2/select [:model/Table :id :name :db_id] :db_id 1)
```

**Check current settings**:
```clojure
(t2/select-one :model/Setting :key "site-name")
```

**Create a saved question via REPL** (faster than UI/API):
```clojure
(t2/insert-returning-instance! :model/Card
  {:name "Test Question"
   :database_id 1
   :dataset_query {:database 1 :type :native :native {:query "SELECT 1"}}
   :display :table
   :visualization_settings {}
   :creator_id 1
   :collection_id nil})
```

**Run a query and inspect results**:
```clojure
(require '[metabase.query-processor :as qp])
(qp/process-query {:database 1 :type :native :native {:query "SELECT * FROM ORDERS LIMIT 5"}})
```

**Toggle a feature flag**:
```clojure
(t2/update! :model/Setting :key "enable-pivoted-filters" {:value "true"})
```

**Check user permissions**:
```clojure
(t2/select :model/Permissions :group_id 1)
```

**Test query compilation**:
```clojure
(require '[metabase.query-processor.compile :as qp.compile])
(qp.compile/compile {:database 1
                     :type :query
                     :query {:source-table 1
                             :filter [:= [:field 1 nil] 42]}})
```

**Loading test/dev namespaces** (advanced — only if needed):
Since the worktree has full source, you can add source paths to the running classpath:
```clojure
(require '[clojure.java.io :as io])
(.addURL (.getContextClassLoader (Thread/currentThread))
         (io/as-url (io/file "./repro/<ISSUE-ID>/source/test")))
(.addURL (.getContextClassLoader (Thread/currentThread))
         (io/as-url (io/file "./repro/<ISSUE-ID>/source/dev")))
;; Now you can require test/dev namespaces:
(require '[metabase.test :as mt])
(require '[dev])
```

Key test/dev namespaces (after loading):
- `metabase.test` (as `mt`) — `mt/user-http-request`, `mt/id`, `mt/with-temp`
- `dev` — `dev/pprint-sql`, `dev/explain-query`

### HTTP API Calls

**Use the MCP `api_call` tool** for all API interactions — it handles authentication automatically:
```
mcp__metabase-repro__api_call(repro_dir="repro/<ISSUE-ID>", method="GET", path="/database")
mcp__metabase-repro__api_call(repro_dir="repro/<ISSUE-ID>", method="GET", path="/database", jq_filter=".data[].name")
mcp__metabase-repro__api_call(repro_dir="repro/<ISSUE-ID>", method="GET", path="/health")
```

For POST/PUT requests with JSON bodies:
```
mcp__metabase-repro__api_call(repro_dir="repro/<ISSUE-ID>", method="POST", path="/card", body='{"name":"test","dataset_query":{"database":1,"type":"native","native":{"query":"SELECT 1"}}}')
```

**Visualization settings format**: When setting `graph.tooltip_columns` or similar column-reference settings via API, values must use column reference format: `["[\"name\",\"COLUMN_NAME\"]"]`, not bare column names like `["COLUMN_NAME"]`.

**Efficient schema discovery** — get all tables and fields in one call:
```
mcp__metabase-repro__api_call(repro_dir="repro/<ISSUE-ID>", method="GET", path="/database/1/metadata")
```

**Avoid large API responses**: Never call `/table` without a narrow jq_filter — it returns all system tables (400K+ chars). For field discovery, use:
```
api_call(method="GET", path="/database/1/fields", jq_filter="[.[] | select(.table_name == \"ORDERS\") | {id, name, table: .table_name}]")
```

### Documentation Reference

When encountering Metabase-specific terminology (dashboards, questions, models, segments, metrics, subscriptions, etc.):
```
WebFetch https://www.metabase.com/docs/latest/<relevant-section>
```

Use web search for version-specific behavior, known issues, or unfamiliar error messages.

### After Each Attempt

Evaluate:
- What was tested
- Actual result
- Whether it matches the reported behavior
- Self-critique: "Did I actually test the right thing?"

**Stop when**: REPRODUCED, NOT REPRODUCED, or after 3 inconclusive attempts → INCONCLUSIVE.

---

## Phase 5: Write Failing Test

> **Gate**: Only run this phase when the reproduction status is **REPRODUCED**. A root cause hypothesis is helpful but not required — if the reproduction steps make the failing behavior clear enough to encode as a test, proceed even without a root cause. If the status is NOT REPRODUCED or INCONCLUSIVE, skip to Phase 6.

> **NEVER use `clojure` CLI, `clojure -M`, or `clojure -X`. ALWAYS use the `repl_eval` MCP tool or `mcp__metabase-repro__run_test`. Starting a fresh JVM wastes 30-60 seconds per invocation.**

> **Reference**: The `CLAUDE.md` file in `./repro/<ISSUE-ID>/source/` contains detailed instructions for writing and running both backend (Clojure) and frontend (TypeScript/Jest/Cypress) tests — including conventions, test locations, commands, and patterns. **Read it before writing any test.**

### Determine Test Type

Based on the issue classification from Phase 2 and the root cause, decide what kind of test to write. You may write **one or both**:

| Bug Type | Test Type | Location |
|----------|-----------|----------|
| Backend logic, query processor, API | **Clojure unit test** | `test/metabase/...` |
| Frontend UI behavior, rendering | **Jest unit/component test** | `frontend/test/...` or co-located `*.unit.spec.ts`/`*.unit.spec.tsx` |
| End-to-end user workflow, UI interaction | **Cypress acceptance test** | `e2e/test/scenarios/...` |
| Mixed (backend causes wrong data, frontend renders it wrong) | **Both** — Clojure test for the data bug + frontend/e2e test for the UI |

### Find Relevant Test File

Use the root cause hypothesis to identify the source file(s) involved, then locate the corresponding test file. Metabase mirrors source structure:

**Backend (Clojure)**:

| Source path | Test path |
|------------|-----------|
| `src/metabase/foo/bar.clj` | `test/metabase/foo/bar_test.clj` |
| `src/metabase/foo/bar/baz.clj` | `test/metabase/foo/bar/baz_test.clj` |

**Frontend (TypeScript)**:

| Source path | Test path |
|------------|-----------|
| `frontend/src/metabase/foo/Bar.tsx` | `frontend/src/metabase/foo/Bar.unit.spec.tsx` (co-located) or `frontend/test/metabase/foo/Bar.unit.spec.tsx` |
| UI workflow / interaction | `e2e/test/scenarios/<category>/foo.cy.spec.ts` |

Use Grep to search for existing tests related to the buggy function/component. If no test file exists at the expected path, check for related test files in the same directory. Consult `CLAUDE.md` in the source worktree for the project's conventions on test file placement.

### Choose Test Approach

**Backend (Clojure)**:

| Root Cause Type | Test Approach |
|----------------|--------------|
| Query processor bug | `mt/process-query` or `qp/process-query` |
| API endpoint bug | `mt/user-http-request` |
| Model / data bug | `mt/with-temp` + `t2/select` |
| Pure logic / edge case | Direct function call with specific inputs |

**Frontend (TypeScript)**:

| Root Cause Type | Test Approach |
|----------------|--------------|
| Component rendering bug | Jest + React Testing Library — render component, assert DOM |
| User interaction bug | Cypress — visit page, interact, assert visible result |
| Data display / formatting | Jest unit test on the formatting/transform function |
| State management bug | Jest — test reducer/action/selector with specific inputs |

Look at existing tests in the identified test file for patterns to follow — imports, fixtures, helpers, assertion style.

### Write the Test

Add a new test to the appropriate test file in `./repro/<ISSUE-ID>/source/`. The test should:

- **Be minimal** — only test the specific failing behavior
- **Follow existing patterns** in the file (imports, fixtures, helpers, assertion style)
- **Have a descriptive name** referencing the issue: e.g., Clojure: `(deftest issue-12345-test ...)`, Jest: `it("should handle X (issue #12345)")`, Cypress: `it("should not show X when Y (metabase#12345)")`
- **Include a description** explaining the expected behavior (Clojure `testing` string, or descriptive `it`/`describe` text)
- **Assert the correct/expected behavior** — the test should FAIL against the buggy code (since it asserts what _should_ happen, not what currently happens)

### Run the Test

Use the MCP tool which auto-detects the test type from the file extension:

```
mcp__metabase-repro__run_test(repro_dir="repro/<ISSUE-ID>", test_file="test/metabase/foo/bar_test.clj")
```

- **Clojure tests** (`.clj`): Connects to the running REPL (port 3000 + PORT), adds test/dev paths to the classpath automatically, requires the namespace, and runs the tests.
- **Jest tests** (`.unit.spec.ts(x)`): Runs `yarn test-unit` in the source worktree.
- **Cypress tests** (`.cy.spec.ts`): Runs `yarn test-cypress-run` with `CYPRESS_BASE_URL` set to the running instance.

The tool reports whether the test **failed** (expected — demonstrates the bug) or **passed** (unexpected — test may not be targeting the bug correctly). If it passes, revisit the test logic.

### Generate and Save Diff

```
mcp__metabase-repro__save_test_patch(repro_dir="repro/<ISSUE-ID>")
```

This captures all changes (including new untracked files) and saves them to `./repro/<ISSUE-ID>/test-diff.patch`.

### If Test Writing Fails

**Edit tool failures**: If the Edit tool fails with "file not read" or similar errors, re-read the file with the Read tool and retry the Edit once. If it still fails, use the Write tool to write the complete file. Do NOT fall back to Bash workarounds (`cat >>`, `cp`, `python3 -c`) — these trigger permission denials in CI and waste many turns.

If you can't write a useful failing test (can't find the right file, test doesn't fail as expected, REPL errors, root cause is too vague), note the attempt and reason in the report but **do not block the workflow**. Move on to Phase 6.

If the test cannot be run via `run_test` (classpath issues, large file timeouts, enterprise path issues), write a minimal inline REPL snippet that reproduces the assertion logic without the test framework and confirm it produces the wrong output. Document this as equivalent test evidence in the report.

If `run_test` fails twice, do NOT attempt manual classloader manipulation. Write an inline REPL snippet instead or skip test execution — the patch file is still valuable.

---

## Phase 6: Report & Post

### Classification

Choose one:
- **REPRODUCED** — the reported behavior was observed
- **NOT REPRODUCED** — the reported behavior was not observed; instance behaved correctly
- **INCONCLUSIVE** — could not determine due to environment constraints, missing driver, etc.

### Compose Linear Comment

```markdown
## Repro-Bot Investigation

**Status**: REPRODUCED / NOT REPRODUCED / INCONCLUSIVE
**Metabase Version**: <version tested>
**Application Database**: H2 / Postgres / MySQL / MariaDB

### Summary
<1-2 sentences describing what was found>

### Reproduction Method
<Browser UI / API call / REPL / Code analysis — and brief description of what was done>

### Key Findings
- <bullet point>
- <bullet point>
- <up to 5 total>

### Evidence
<Paste the most relevant evidence: API response, REPL output, or screenshot description>
<If browser reproduction: describe what was observed in the UI, reference any screenshot>

### Root Cause Hypothesis (if identified)
<If REPRODUCED and root cause is clear: likely cause based on findings>
<If root cause is unclear: omit this section or write "Root cause not determined — reproduction steps above demonstrate the bug.">
<If NOT REPRODUCED: why it may work locally but fail in the reported environment>
<If INCONCLUSIVE: what additional environment or setup would be needed>

### Failing Test
<If a test was written: describe what the test does, which file it was added to, and confirm it fails against the buggy code. Note that a patch file is attached.>
<If no test was written: explain why — root cause unclear, couldn't identify correct test location, REPL errors, status was not REPRODUCED, etc.>

### Attempts

Include ALL attempts, even unsuccessful ones. This helps developers understand what was ruled out.

| # | Approach | Hypothesis | Result |
|---|----------|-----------|--------|
| 1 | ... | ... | ... |
| 2 | ... | ... | ... |

### Approaches Not Tried
<List any reproduction approaches that were considered but not attempted, with the reason why each was skipped (e.g., "Tried to use pg_sleep for timing but H2 doesn't support it", "Considered Cypress e2e test but the bug is purely backend"). Omit this section only if every considered approach was attempted.>

### Next Steps
- <actionable item 1>
- <actionable item 2>
- <up to 3 total>

```

### Post to Linear

> **IMPORTANT**: Do NOT sync to GitHub. These are internal investigation comments and must stay Linear-only. If the Linear API supports a `doNotSyncToGithub` or similar flag, use it. Otherwise, prefix the comment body with `[internal]` to signal it should not be mirrored.

```
mcp__linear-server__save_comment(issueId: "<LINEAR-ID>", body: "<comment body>")
```

### Label the Issue

Apply a label based on the reproduction outcome:

| Status | Label |
|--------|-------|
| REPRODUCED | `.Auto Repro Success` |
| NOT REPRODUCED | `.Auto Repro Failed` |
| INCONCLUSIVE | `.Auto Repro Inconclusive` |

Retrieve the issue's current labels from the Phase 1 data (the `labels` array in the
`get_issue`/`list_issues` response). Add the appropriate repro label to that list, then pass
all labels together:

```
mcp__linear-server__save_issue(id: "<LINEAR-ID>", labels: ["<existing-label-1>", "<existing-label-2>", ..., "<repro-label>"])
```

**IMPORTANT**: The `labels` parameter REPLACES all labels — it is not additive. Always include
the issue's existing labels to avoid wiping them.

**IMPORTANT**: Only add the exact labels listed in the table above (`.Auto Repro Success`,
`.Auto Repro Failed`, `.Auto Repro Inconclusive`). Do NOT add any other labels such as
`.Reproduced`, `.Not Reproduced`, etc.

If a Playwright screenshot was captured, describe it in the comment body. Do NOT attempt to attach screenshots via `create_attachment` with base64 content — this is known to fail with "Invalid base64 content" errors and wastes turns.

> **Linear subscription note**: Creating a comment via the Linear API will auto-subscribe the authenticated API user to the issue. This is a known Linear limitation — there is no `doNotSubscribe` parameter. The user should manually unsubscribe from issues or adjust their Linear notification settings if this is unwanted.

If a test diff exists at `./repro/<ISSUE-ID>/test-diff.patch`, attach it to the Linear issue:
```
mcp__linear-server__create_attachment(
  issue: "<LINEAR-ID>",
  base64Content: "<base64-encoded contents of test-diff.patch>",
  filename: "<ISSUE-ID>-failing-test.patch",
  contentType: "text/x-patch",
  title: "Failing test patch"
)
```

### CI Run Link

If `GITHUB_ACTIONS_RUN_URL` is set (CI mode), append to the Linear comment body:

```markdown
---
*Investigated by [Repro-Bot CI](${GITHUB_ACTIONS_RUN_URL})*
```

### Fallback

If no Linear issue was found or resolved:
- **In CI mode** (`GITHUB_ACTIONS_RUN_URL` is set): Print the full report to the console. Do NOT ask the user — there is no interactive user in CI.
- **In interactive mode**: Print the full report to terminal and ask: "Could not find a linked Linear issue. What is the Linear ID for this issue? (e.g., MB-1234)"

---

## Phase 7: Cleanup

Stop the Metabase instance and clean up resources:

```
mcp__metabase-repro__cleanup(repro_dir="repro/<ISSUE-ID>")
```

`cleanup` stops the Metabase process (if still running), removes the source worktree (`./repro/<ISSUE-ID>/source/`) to reclaim disk space, stops any appdb Docker container, and clears state.

The following are **intentionally left in place** for post-investigation inspection:
- H2 DB: `./repro/<ISSUE-ID>/metabase.mv.db`
- Server logs: `./repro/<ISSUE-ID>/metabase.*.log`
- Env file: `./repro/<ISSUE-ID>/env.edn`
- Test diff (if generated): `./repro/<ISSUE-ID>/test-diff.patch`

No user notification needed — the Linear comment is the deliverable.

> **CRITICAL**: Do NOT end the conversation after cleanup. You MUST proceed to Phase 8 (Self-Review) to write SUGGESTIONS.md. The workflow is not complete until SUGGESTIONS.md is written.

---

## Phase 8: Self-Review

After cleanup, review your own execution transcript and append findings to `./repro/<ISSUE-ID>/SUGGESTIONS.md`. This creates a per-issue record of improvement suggestions that `/auto-improve` later consolidates into tooling and prompt changes.

### What to review

Scan the full conversation for:

1. **MCP server issues** — tool errors, missing params, bad defaults, unhelpful error messages, or missing functionality that forced a bash fallback.
2. **Prompt gaps** — missing steps, unclear instructions, wrong ordering, or missing edge cases in `.claude/commands/repro.md`.
3. **Knowledge gaps** — facts that should be in `CLAUDE.md` but weren't (e.g., H2 timezone limits, version tag formats).
4. **Permission prompts** — any tool call that required user approval and could be restructured to avoid it.
5. **Memory-worthy patterns** — stable lessons learned that should persist across sessions.

### Output format

Write findings to `./repro/<ISSUE-ID>/SUGGESTIONS.md`:

```markdown
## <ISSUE-ID> — <DATE>

| # | Category | Target File | Issue | Proposed Fix |
|---|----------|-------------|-------|--------------|
| 1 | MCP server | `mcp/metabase_repro/metabase.py` | [start-timeout] `start_metabase` doesn't report last log lines on timeout | Add: read last 30 lines of `metabase.log` and include in error response when startup exceeds 5 min |
| 2 | Prompt | `.claude/commands/repro.md` | [version-fallback] Phase 2 doesn't explain what to do when version tag has no JAR | In Phase 2, after version extraction, add: "If `jar_download` fails, try the latest stable release via `gh release list`" |
| 3 | CLAUDE.md | `CLAUDE.md` | [h2-json] H2 doesn't support JSON column type | Add to CLAUDE.md Notes section: "H2 doesn't support JSON columns — use TEXT and cast in queries" |
| 4 | Permission | `.claude/commands/repro.md` | [curl-approval] Used `curl` instead of `api_call`, triggered approval | In Phase 4, add reminder: "NEVER use curl/wget — always use `api_call` MCP tool" |
| 5 | Memory | `memory/metabase-quirks.md` | [ee-token-log] EE token errors flood the log but are harmless without a license | Persist: "Ignore 'Token validation failed' log messages in OSS/unlicensed runs" |
```

### Category reference

Use **exactly** one of these categories per row (must match `/auto-improve` buckets):

| Category | Meaning | Typical target file |
|----------|---------|---------------------|
| `MCP server` | Bug or improvement in MCP tool code | `mcp/metabase_repro/*.py` |
| `Prompt` | Change needed in the repro command | `.claude/commands/repro.md` |
| `CLAUDE.md` | Knowledge gap — fact that should be documented | `CLAUDE.md` |
| `New tool` | Missing MCP tool functionality causing bash fallback | `mcp/metabase_repro/server.py` |
| `Permission` | Action that triggered unnecessary user approval | Various |
| `Memory` | Stable pattern to persist in memory files | `memory/*.md` |

### Rules
- **One file per issue** — write to `./repro/<ISSUE-ID>/SUGGESTIONS.md`, not the project root
- **Deduplication tags** — every Issue cell must start with a `[kebab-case-tag]` (e.g., `[socket-repl]`, `[ee-oss-tags]`, `[api-truncation]`). These tags enable frequency counting across runs via grep.
- **Be specific in proposed fixes** — every item must include:
  1. The **exact file path** to change
  2. The **exact section/location** within that file (e.g., "Phase 3, after the `start_metabase` call")
  3. The **actual text to add or change** (or a close approximation) — not "update the prompt" but the literal addition/edit
- **Be actionable** — every item must propose a concrete fix (tool change, prompt change, or behavioral rule)
- **No subagents** — do this review inline; you have the full transcript in context
- **Skip if clean** — if the run had no issues worth noting, write: `## <ISSUE-ID> — <DATE>\n\nClean run — no issues.`
- **Observations** — if there are findings that don't fit the table (e.g., "code analysis approach was effective"), add them as a `### Observations` section with 2-3 bullets max. Do not add a freeform "Notes" section.

---

## Edge Case Handling

| Scenario | Handling |
|----------|----------|
| No linked Linear issue | Print report to terminal, ask user for Linear ID |
| JAR download fails | Report the error and the version string that was tried; suggest checking version format |
| Metabase fails to start within 5 minutes | Report the last 30 lines of `metabase.log`, stop investigation |
| Metabase needs a clean restart | Use `mcp__metabase-repro__reset_metabase(repro_dir="repro/<ISSUE-ID>")` then `start_metabase` again |
| Frontend-only issue (no API/SQL) | Use playwright-cli; mark INCONCLUSIVE only if Playwright is unavailable |
| Driver-specific issue (MySQL, etc.) | Note which appdb was used; mark INCONCLUSIVE with a note about environment requirements if the required driver isn't available |
| Issue has no repro steps | Attempt reproduction based on title and description alone; note the absence of steps in report |
| Prior auto-reproduce comment exists | Note the prior investigation in the report, proceed anyway with fresh investigation |
| Version not found / download error | Try latest stable release as fallback (query `gh release list`); note the version fallback in the report. Do NOT use `master`. |
| Upgrade / version-switch issue | Use `stop_metabase` to stop the process, then `start_metabase` with new version and same port. See Phase 4 "Upgrade / Version-Switch Scenarios". |
