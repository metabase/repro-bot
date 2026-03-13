---
name: write-test
description: Write a failing test for a reproduced Metabase bug. Invoked from the /repro workflow when status is REPRODUCED. Determines test type (Clojure/Jest/Cypress), finds the right test file, writes a minimal failing test, runs it, and saves a patch.
allowed-tools: Read, Edit, Write, Grep, Glob, mcp__metabase-repro__run_test, mcp__metabase-repro__save_test_patch, mcp__metabase-repro__repl_eval
---

# Write Failing Test

This skill is invoked from the `/repro` workflow. The issue ID, repro dir, reproduction status, and root cause are in conversation context from prior phases.

## Determine Test Type

| Bug Type | Test Type | Location |
|----------|-----------|----------|
| Backend logic, query processor, API | **Clojure unit test** | `test/metabase/...` |
| Frontend UI behavior, rendering | **Jest unit/component test** | `frontend/test/...` or co-located `*.unit.spec.ts`/`*.unit.spec.tsx` |
| End-to-end user workflow, UI interaction | **Cypress acceptance test** | `e2e/test/scenarios/...` |
| Mixed (backend + frontend) | **Both** — Clojure test for data + frontend/e2e test for UI |

## Find Relevant Test File

Use the root cause to identify source file(s), then locate the corresponding test file:

**Backend**: `src/metabase/foo/bar.clj` → `test/metabase/foo/bar_test.clj`
**Frontend**: `frontend/src/metabase/foo/Bar.tsx` → `frontend/src/metabase/foo/Bar.unit.spec.tsx` or `frontend/test/metabase/foo/Bar.unit.spec.tsx`
**E2E**: UI workflow → `e2e/test/scenarios/<category>/foo.cy.spec.ts`

Use Grep to search for existing tests related to the buggy function/component. Consult `CLAUDE.md` in the source worktree for test conventions.

## Choose Test Approach

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

Look at existing tests in the file for patterns to follow.

## Write the Test

Add a new test to the appropriate test file in `./repro/<ISSUE-ID>/source/`. The test should:
- **Be minimal** — only test the specific failing behavior
- **Follow existing patterns** in the file (imports, fixtures, helpers, assertion style)
- **Have a descriptive name** referencing the issue: e.g., `(deftest issue-12345-test ...)`, `it("should handle X (issue #12345)")`, `it("should not show X when Y (metabase#12345)")`
- **Assert the correct/expected behavior** — the test should FAIL against the buggy code

## Run the Test

```
mcp__metabase-repro__run_test(repro_dir="repro/<ISSUE-ID>", test_file="test/metabase/foo/bar_test.clj")
```

- **Clojure tests** (`.clj`): Connects to running REPL, adds test/dev paths, requires namespace, runs tests.
- **Jest tests** (`.unit.spec.ts(x)`): Runs `yarn test-unit` in the source worktree.
- **Cypress tests** (`.cy.spec.ts`): Runs `yarn test-cypress-run` with `CYPRESS_BASE_URL` set.

The tool reports whether the test **failed** (expected — demonstrates the bug) or **passed** (unexpected — revisit test logic).

## Generate and Save Diff

```
mcp__metabase-repro__save_test_patch(repro_dir="repro/<ISSUE-ID>")
```

Saves all changes (including new untracked files) to `./repro/<ISSUE-ID>/test-diff.patch`.

## Troubleshooting

- **Edit tool failures**: Re-read the file and retry once. If still failing, use Write tool for the complete file. Do NOT use Bash workarounds (`cat >>`, `cp`, `python3 -c`).
- **Bash restrictions in CI**: Many Bash commands are blocked. Always use `run_test` MCP tool — do NOT attempt raw shell commands.
- **Can't write a useful test**: Note the attempt and reason in the report, move on to Phase 6.
- **`run_test` fails twice**: Write an inline REPL snippet instead or skip test execution — the patch is still valuable.
- **Large enterprise tests**: If `run_test` times out on a large file in `enterprise/backend/test/`, write a minimal inline REPL snippet instead.
- **Node version errors in CI**: Do NOT attempt manual yarn/jest/cypress. Document as "verified by code review, could not execute in CI due to Node version mismatch".
- **Jest/Cypress tooling failures**: Save the test patch — it's valid evidence even without execution. Note the tooling error in the report.
- **`run_test` returns nil**: Ensure `setup_worktree` was called before `start_metabase`.
  If Metabase was started first, restart it to pick up test paths.
- **Test namespaces unavailable**: Restart Metabase after `setup_worktree`.
- **Dynamic column aliases**: For tests involving `lib/desired-column-alias`, retrieve the alias dynamically from `lib/returned-columns` rather than hardcoding. Aliases differ by metadata provider.
