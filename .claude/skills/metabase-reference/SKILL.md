---
name: metabase-reference
description: Reference material for Metabase reproduction — REPL recipes, API patterns, domain quirks (pivot tables, serialization, H2 tips), edge case handling, and MCP tools table. Invoke at Phase 4 start.
---

# Metabase Reference

## REPL Recipes

**Inspect tables**: `(t2/select [:model/Table :id :name :db_id] :db_id 1)`

**Check settings**: `(t2/select-one :model/Setting :key "site-name")`

**Create saved question**:
```clojure
(t2/insert-returning-instance! :model/Card
  {:name "Test Question" :database_id 1
   :dataset_query {:database 1 :type :native :native {:query "SELECT 1"}}
   :display :table :visualization_settings {} :creator_id 1 :collection_id nil})
```

**Run query**:
```clojure
(require '[metabase.query-processor :as qp])
(qp/process-query {:database 1 :type :native :native {:query "SELECT * FROM ORDERS LIMIT 5"}})
```

**Toggle feature flag**: `(t2/update! :model/Setting :key "enable-pivoted-filters" {:value "true"})`
Note: `t2/update!` may return `0` even when successful. Verify with `t2/select-one`.

**Check permissions**: `(t2/select :model/Permissions :group_id 1)`

**Compile query to SQL**:
```clojure
(require '[metabase.query-processor.compile :as qp.compile])
(qp.compile/compile {:database 1 :type :query :query {:source-table 1 :filter [:= [:field 1 nil] 42]}})
```

**Load test/dev namespaces** (advanced):
```clojure
(require '[clojure.java.io :as io])
(.addURL (.getContextClassLoader (Thread/currentThread))
         (io/as-url (io/file "./repro/<ISSUE-ID>/source/test")))
(.addURL (.getContextClassLoader (Thread/currentThread))
         (io/as-url (io/file "./repro/<ISSUE-ID>/source/dev")))
(require '[metabase.test :as mt])
```

Key test/dev namespaces: `metabase.test` (`mt`) — `mt/user-http-request`, `mt/id`, `mt/with-temp`; `dev` — `dev/pprint-sql`, `dev/explain-query`.

## API Call Patterns

```
api_call(method="GET", path="/database")
api_call(method="GET", path="/database", jq_filter=".data[].name")
api_call(method="POST", path="/card", body='{"name":"test","dataset_query":{"database":1,"type":"native","native":{"query":"SELECT 1"}}}')
api_call(method="GET", path="/database/1/metadata")  # All tables+fields in one call
```

**Visualization settings**: `graph.tooltip_columns` values must use column reference format: `["[\"name\",\"COLUMN_NAME\"]"]`, not bare names.

**Avoid large responses**: Never call `/table` without a narrow `jq_filter`. For field discovery:
```
api_call(method="GET", path="/database/1/fields", jq_filter="[.[] | select(.table_name == \"ORDERS\") | {id, name, table: .table_name}]")
```

## Domain Knowledge

**Pivot tables**: "Old pivot" = `table.pivot: true` on Table visualization (3-column only: 2 dimensions + 1 metric, code: `data_grid.js` → `pivot()`). "New pivot" = `PivotTable` visualization type (code: `data_grid.js` → `multiLevelPivot()`). Separate code paths, separate bugs.

**Serialization sort-by quirk**: `sort-by` with a single key that has ties (e.g., `:created_at`) produces non-deterministic order. Recurring source of serialization diff bugs.

**Appdb as data warehouse**: The Postgres appdb can double as a data warehouse — register via `POST /api/database` with same connection details. Use REPL + `next.jdbc` to `CREATE SCHEMA` and `CREATE TABLE` for multi-schema testing.

## H2 Tips

- Does NOT support `report-timezone`
- Reserves SQL keywords (`value`, `count`, `key`, `type`) as column names/aliases — use `amount`, `qty`, `cnt` instead
- May reject NULL insertions even after dropping NOT NULL constraints
- Does NOT support `DATETRUNC()` — use `CAST(col AS DATE)` for date-typed columns
- `FORMATDATETIME()` returns text, not a date type — avoid when testing date formatting
- No `pg_sleep()` — for timing-dependent issues, use code analysis instead
- In Sample Database, `CATEGORY` is in `PRODUCTS`, not `ORDERS` — join via `PRODUCTS P ON O.PRODUCT_ID = P.ID`

## Edge Case Decision Table

| Scenario | Handling |
|----------|----------|
| No linked Linear issue | Print report to terminal, ask user for Linear ID |
| JAR download fails | Report error and version string; suggest checking version format |
| Metabase fails to start within 5 min | Report last 30 lines of `metabase.log`, stop investigation |
| Metabase needs clean restart | `reset_metabase` then `start_metabase` again |
| Frontend-only issue | Use playwright-cli; INCONCLUSIVE only if Playwright unavailable |
| Driver-specific issue | Note appdb used; INCONCLUSIVE if required driver unavailable |
| No repro steps in issue | Attempt based on title/description; note absence in report |
| Prior auto-reproduce comment | Note prior investigation, proceed with fresh investigation |
| Version not found | Try latest stable via `gh release list`; note fallback in report. Never use `master`. |
| Upgrade / version-switch | `stop_metabase` → `start_metabase` with new version + same port |

## MCP Tools Reference

| Tool | Description |
|------|-------------|
| `check_setup` | Pre-flight check for required tools/env |
| `start_appdb` | Start Docker container for Postgres/MySQL/MariaDB appdb |
| `stop_appdb_tool` | Stop and remove appdb container |
| `create_env` | Create env.edn configuration |
| `jar_download` | Download Metabase JAR |
| `start_metabase` | Full orchestration: download + env + start + setup + session |
| `stop_metabase` | Kill process (preserves DB, env, worktree) |
| `reset_metabase` | Kill process, remove DB/logs, keep env/worktree |
| `get_session_token` | Obtain/refresh admin session token |
| `check_setup_token` | Check if instance needs initial setup |
| `api_call` | Authenticated Metabase API call |
| `setup_master_worktree` | Create/update repro/master worktree |
| `setup_worktree` | Create issue-specific source worktree |
| `save_test_patch` | Generate diff of test changes as patch |
| `run_test` | Run Clojure/Jest/Cypress tests |
| `repl_eval` | Evaluate Clojure code via socket REPL |
| `get_status` | Show all running repro instances |
| `cleanup` | Remove source worktree, stop appdb, clear state |
