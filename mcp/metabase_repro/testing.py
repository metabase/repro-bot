"""Test running: execute Clojure, Jest, or Cypress tests against a source worktree."""
from __future__ import annotations

import logging
import os
import re

from .core import repro_path, run, read_state_file
from .repl import repl_eval as _repl_eval_fn

logger = logging.getLogger(__name__)


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


def _resolve_dev_classpath(source_dir: str) -> list[str]:
    """Resolve :dev alias Maven dependency JARs from the source worktree.

    Checks for a cached .dev-classpath file first (written by setup_worktree),
    then falls back to running `clj -A:dev -Spath`.
    Returns an empty list on failure (clj not found, resolution error, etc.).
    """
    # Check for cached classpath from setup_worktree
    cache_file = os.path.join(source_dir, ".dev-classpath")
    if os.path.exists(cache_file):
        with open(cache_file) as f:
            jars = [line.strip() for line in f if line.strip()]
        if jars:
            logger.info("Using cached dev classpath (%d JARs)", len(jars))
            return jars

    # Fall back to resolving (longer timeout for fresh downloads)
    try:
        result = run(["clj", "-A:dev", "-Spath"], cwd=source_dir, timeout=300)
        if result.returncode != 0:
            logger.warning("clj -A:dev -Spath failed: %s", result.stderr)
            return []
        classpath = result.stdout.strip()
        jars = [p for p in classpath.split(":") if p.endswith(".jar")]
        # Cache for next time
        with open(cache_file, "w") as f:
            f.write("\n".join(jars))
        return jars
    except FileNotFoundError:
        logger.warning("clj not found — dev dependency JARs will not be added to classpath")
        return []
    except Exception as e:
        logger.warning("Failed to resolve dev classpath: %s", e)
        return []


def _run_clojure_test(source_dir: str, test_file: str, port: int | None, repro_dir: str) -> str:
    """Run a Clojure test via the socket REPL."""
    if not port:
        return "ERROR: Clojure tests require a running Metabase instance (need port for socket REPL)"

    # Detect enterprise test path
    is_enterprise = test_file.startswith("enterprise/")

    # Derive namespace from test file path
    ns = test_file
    if is_enterprise:
        ns = re.sub(r"^enterprise/backend/test/", "", ns)
    else:
        ns = re.sub(r"^test/", "", ns)
    ns = re.sub(r"\.cljc?$", "", ns)
    ns = ns.replace("/", ".")
    ns = ns.replace("_", "-")

    # Build list of classpath directories to add
    cp_dirs = [f"{source_dir}/test", f"{source_dir}/dev"]
    if is_enterprise:
        cp_dirs.extend([
            f"{source_dir}/enterprise/backend/test",
            f"{source_dir}/enterprise/backend/src",
        ])

    # Resolve dev dependency JARs from deps.edn :dev alias
    dev_jars = _resolve_dev_classpath(source_dir)
    if dev_jars:
        jar_vector = " ".join(f'"{jar}"' for jar in dev_jars)
        add_jars_code = f"""
    (doseq [jar [{jar_vector}]]
      (.addURL cl (io/as-url (io/file jar))))"""
    else:
        add_jars_code = ""

    # Build addURL calls for all classpath dirs
    cp_urls = "\n".join(
        f'      (let [u (io/as-url (io/file "{d}"))] (.addURL cl u))'
        for d in cp_dirs
    )

    clj_code = f"""
(require '[clojure.java.io :as io])
(let [cl (.getContextClassLoader (Thread/currentThread))
      test-url (io/as-url (io/file "{source_dir}/test"))]
  (when-not (some #{{test-url}} (seq (.getURLs cl)))
{cp_urls} {add_jars_code}
    (println "Added classpath entries:" (mapv str (.getURLs cl)))))
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
    result = run(
        ["yarn", "test-unit", f"--testPathPattern={test_file}"],
        cwd=source_dir,
        timeout=120,
    )
    return result.stdout + result.stderr


def _run_cypress_test(source_dir: str, test_file: str, port: int | None) -> str:
    """Run a Cypress acceptance test."""
    if not port:
        return "ERROR: Cypress tests require a port for the running Metabase instance"

    import subprocess
    env = os.environ.copy()
    env["CYPRESS_BASE_URL"] = f"http://localhost:{port}"

    result = subprocess.run(
        ["yarn", "test-cypress-run", "--spec", test_file],
        capture_output=True, text=True,
        cwd=source_dir, env=env, timeout=300,
    )
    return result.stdout + result.stderr
