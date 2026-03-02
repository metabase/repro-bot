#!/usr/bin/env python3
"""MCP server exposing all Metabase repro tools.

Run with: uv run --with fastmcp python -m metabase_repro
"""
from __future__ import annotations

import json
import os
from typing import Optional

from fastmcp import FastMCP

from .core import PROJECT_ROOT, load_state, is_pid_running, read_state_file, write_state_file
from . import appdb
from . import metabase
from . import api
from . import git
from . import preflight
from . import testing

mcp = FastMCP("metabase-repro")


@mcp.tool()
def check_setup() -> str:
    """Verify all required environment variables, tools, and MCP servers are available.

    Run this before starting any reproduction workflow."""
    return preflight.check_setup()


@mcp.tool()
def start_appdb(repro_dir: str, db_type: str = "mysql") -> str:
    """Start a Docker container for the Metabase application database."""
    return appdb.start_appdb(repro_dir, db_type)


@mcp.tool()
def stop_appdb_tool(repro_dir: str) -> str:
    """Stop and remove the appdb Docker container for a repro directory."""
    return appdb.stop_appdb(repro_dir)


@mcp.tool()
def create_env(repro_dir: str, db_type: str = "h2", appdb_port: str = "") -> str:
    """Create the env.edn configuration file for a Metabase repro instance."""
    if not appdb_port and db_type != "h2":
        appdb_port = read_state_file(repro_dir, "appdb-port") or ""
    return appdb.create_env(repro_dir, db_type, appdb_port)


@mcp.tool()
def jar_download(version: str) -> str:
    """Download a Metabase JAR to the shared downloads/ directory."""
    return metabase.jar_download(version)


@mcp.tool()
def start_metabase(repro_dir: str, version: str, port: Optional[int] = None) -> str:
    """Download JAR, create env, and start Metabase. Returns port and credentials.

    Orchestrates: jar-download -> create-env -> start -> setup -> session token.
    If port is not provided, picks a random one."""
    return metabase.start_metabase(repro_dir, version, port)


@mcp.tool()
def stop_metabase(repro_dir: str) -> str:
    """Stop a running Metabase instance, remove source worktree, and stop appdb."""
    return metabase.stop_metabase(repro_dir)


@mcp.tool()
def reset_metabase(repro_dir: str) -> str:
    """Reset a Metabase instance (kill process, remove DB/logs, keep env and worktree)."""
    return metabase.reset_metabase(repro_dir)


@mcp.tool()
def get_session_token(repro_dir: str, email: str = "crowberto@metabase.com", password: str = "") -> str:
    """Obtain a fresh session token for a running Metabase instance.

    Tries EE password (blackjet) then OSS (1Blackjet!) if no password given.
    Saves the token to the session-token state file."""
    port_str = read_state_file(repro_dir, "port")
    if not port_str:
        return "ERROR: No port file found. Is Metabase running?"
    port = int(port_str)
    token, err = metabase.get_session_token(port, email, password if password else None)
    if token:
        write_state_file(repro_dir, "session-token", token)
        return f"Session token: {token}"
    return f"ERROR: Could not authenticate: {err}"


@mcp.tool()
def check_setup_token(repro_dir: str) -> str:
    """Check if a Metabase instance needs initial setup.

    Returns the setup token if setup is needed, empty string if already set up."""
    port_str = read_state_file(repro_dir, "port")
    if not port_str:
        return "ERROR: No port file found. Is Metabase running?"
    return metabase.check_setup_token(int(port_str))


@mcp.tool()
def api_call(repro_dir: str, method: str, path: str, body: str = "", jq_filter: str = "") -> str:
    """Make an authenticated API call to a running Metabase instance.

    Reads port and session token from state files automatically."""
    return api.api_call(repro_dir, method, path, body, jq_filter)


@mcp.tool()
def setup_master_worktree() -> str:
    """Create or update the repro/master worktree from the bare clone.

    This provides the bin/mage script used for JAR downloads."""
    return git.setup_master_worktree()


@mcp.tool()
def setup_worktree(repro_dir: str, version_ref: str) -> str:
    """Create a source worktree for an issue at a specific version."""
    return git.setup_worktree(repro_dir, version_ref)


@mcp.tool()
def save_test_patch(repro_dir: str) -> str:
    """Generate a git diff of changes in the source worktree and save as a patch file.

    Output: <repro_dir>/test-diff.patch"""
    return git.save_test_patch(repro_dir)


@mcp.tool()
def run_test(repro_dir: str, test_file: str, port: Optional[int] = None) -> str:
    """Run a single test file against the source worktree.

    Auto-detects test type from extension:
    - .clj -> Clojure test via REPL
    - .unit.spec.ts(x) -> Jest
    - .cy.spec.ts(x) -> Cypress"""
    return testing.run_test(repro_dir, test_file, port)


@mcp.tool()
def get_status() -> str:
    """Show all known Metabase repro instances and their state.

    Scans the repro/ directory for repro directories with state files."""
    repo_dir = os.path.join(PROJECT_ROOT, "repro")
    if not os.path.isdir(repo_dir):
        return json.dumps({"instances": []})

    instances = []
    for entry in sorted(os.listdir(repo_dir)):
        repro_path = os.path.join(repo_dir, entry)
        port_file = os.path.join(repro_path, "port")
        if os.path.isdir(repro_path) and os.path.exists(port_file):
            state = load_state(f"repro/{entry}")
            pid_file = os.path.join(repro_path, "metabase.pid")
            running = False
            if os.path.exists(pid_file):
                try:
                    pid = int(open(pid_file).read().strip())
                    running = is_pid_running(pid)
                except (ValueError, FileNotFoundError):
                    pass
            state["name"] = entry
            state["running"] = running
            instances.append(state)

    return json.dumps({"instances": instances}, indent=2)
