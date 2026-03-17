"""Test running: execute Clojure, Jest, or Cypress tests against a source worktree."""
from __future__ import annotations

import json
import os
import re

from .core import repro_path, run, read_state_file, truncate_output
from .repl import repl_eval as _repl_eval_fn


def _ensure_node_modules(source_dir: str) -> str | None:
    """Ensure node_modules exists in source_dir, symlinking from CI if needed.

    Returns None on success, or an error message string on failure.
    """
    target = os.path.join(source_dir, "node_modules")
    if os.path.isdir(target):
        return None
    ci_modules = os.environ.get("REPRO_NODE_MODULES_DIR")
    if ci_modules and os.path.isdir(ci_modules):
        os.symlink(ci_modules, target)
        return None
    return "ERROR: node_modules not found. Run 'yarn install' or 'bun install' in the source worktree first, or skip test execution and save the patch."


def _detect_pkg_manager(source_dir: str) -> str:
    """Detect package manager from package.json. Returns 'bun' or 'yarn'."""
    pkg_json = os.path.join(source_dir, "package.json")
    try:
        with open(pkg_json) as f:
            data = json.load(f)
        pm = data.get("packageManager", "")
        if pm.startswith("bun"):
            return "bun"
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return "yarn"


def _node_env() -> dict[str, str] | None:
    """Return env dict with NODE_BIN_DIR prepended to PATH, or None if not set."""
    node_bin = os.environ.get("NODE_BIN_DIR")
    if not node_bin:
        return None
    env = os.environ.copy()
    env["PATH"] = f"{node_bin}:{env.get('PATH', '')}"
    return env


def run_test(repro_dir: str, test_file: str, port: int | None = None,
             source_dir: str | None = None) -> str:
    """Run a single test file against the source worktree.

    Detects test type from the file extension:
    - .clj → Clojure test via clj-nrepl-eval (REPL port = 3000 + port)
    - .unit.spec.ts(x) → Jest unit test
    - .cy.spec.ts(x) → Cypress acceptance test

    Args:
        repro_dir: Path to repro directory (used for port/REPL state)
        test_file: Path relative to source root (e.g. test/metabase/foo_test.clj)
        port: Metabase HTTP port (required for Clojure and Cypress tests)
        source_dir: Override source directory (default: <repro_dir>/source)
    """
    if source_dir is None:
        source_dir = repro_path(repro_dir, "source")

    if not os.path.isdir(source_dir):
        return f"ERROR: Source worktree not found at {source_dir}"

    full_test_path = os.path.join(source_dir, test_file)
    if not os.path.exists(full_test_path):
        return f"ERROR: Test file not found: {full_test_path}"

    # Auto-detect port from state file if not provided
    if port is None:
        port_str = read_state_file(repro_dir, "port")
        if port_str:
            port = int(port_str)

    if test_file.endswith(".clj") or test_file.endswith(".cljc"):
        return _run_clojure_test(source_dir, test_file, port, repro_dir)
    elif re.search(r"\.unit\.spec\.(ts|tsx|js|jsx)$", test_file):
        return _run_jest_test(source_dir, test_file)
    elif re.search(r"\.cy\.spec\.(ts|tsx|js)$", test_file):
        return _run_cypress_test(source_dir, test_file, port)
    else:
        return f"ERROR: Unknown test file type: {test_file}\nExpected: *.clj, *.cljc, *.unit.spec.{{ts,tsx}}, or *.cy.spec.{{ts,tsx}}"


def _run_clojure_test(source_dir: str, test_file: str, port: int | None, repro_dir: str) -> str:
    """Run a Clojure test via the REPL.

    Test/dev namespaces are already on the classpath when Metabase is started
    via clj with :dev:ee:ee-dev aliases — no .addURL manipulation needed.
    """
    if not port:
        return "ERROR: Clojure tests require a running Metabase instance"

    # Derive namespace from test file path
    ns = test_file
    if test_file.startswith("enterprise/"):
        ns = re.sub(r"^enterprise/backend/test/", "", ns)
    else:
        ns = re.sub(r"^test/", "", ns)
    ns = re.sub(r"\.cljc?$", "", ns)
    ns = ns.replace("/", ".")
    ns = ns.replace("_", "-")

    clj_code = f"""
(require '{ns} :reload)
(let [result (clojure.test/run-tests '{ns})]
  (when (pos? (+ (:fail result) (:error result)))
    (println "\\nTest FAILED as expected (test demonstrates the bug)"))
  (when (zero? (+ (:fail result) (:error result)))
    (println "\\nWARNING: Test PASSED — it may not be testing the bug correctly")))
"""

    return _repl_eval_fn(repro_dir, clj_code.strip(), timeout=120)


def _run_jest_test(source_dir: str, test_file: str) -> str:
    """Run a Jest unit test."""
    err = _ensure_node_modules(source_dir)
    if err:
        return err

    pkg_mgr = _detect_pkg_manager(source_dir)
    if pkg_mgr == "bun":
        cmd = ["bun", "run", "test-unit", f"--testPathPattern={test_file}"]
    else:
        cmd = ["yarn", "--ignore-engines", "test-unit", f"--testPathPattern={test_file}"]

    result = run(cmd, cwd=source_dir, timeout=120, env=_node_env())
    return truncate_output(result.stdout + result.stderr)


def _run_cypress_test(source_dir: str, test_file: str, port: int | None) -> str:
    """Run a Cypress acceptance test."""
    if not port:
        return "ERROR: Cypress tests require a port for the running Metabase instance"

    err = _ensure_node_modules(source_dir)
    if err:
        return err

    import subprocess
    env = _node_env() or os.environ.copy()
    env["CYPRESS_BASE_URL"] = f"http://localhost:{port}"

    pkg_mgr = _detect_pkg_manager(source_dir)
    if pkg_mgr == "bun":
        cmd = ["bun", "run", "test-cypress-run", "--spec", test_file]
    else:
        cmd = ["yarn", "test-cypress-run", "--spec", test_file]

    result = subprocess.run(
        cmd,
        capture_output=True, text=True,
        cwd=source_dir, env=env, timeout=300,
    )
    return truncate_output(result.stdout + result.stderr)
