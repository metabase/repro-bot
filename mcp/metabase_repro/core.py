"""Core utilities: paths, state files, port picking, process management."""
from __future__ import annotations

import json
import os
import random
import signal
import socket
import subprocess

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# In-memory session cache (also persisted to state files)
_sessions: dict[str, dict] = {}


def project_path(*parts: str) -> str:
    """Join parts relative to the project root."""
    return os.path.join(PROJECT_ROOT, *parts)


def repro_path(repro_dir: str, *parts: str) -> str:
    """Join parts relative to a repro directory."""
    return project_path(repro_dir, *parts)


def ensure_dir(path: str) -> str:
    """Create directory if it doesn't exist, return path."""
    os.makedirs(path, exist_ok=True)
    return path


def read_state_file(repro_dir: str, filename: str) -> str | None:
    """Read a state file from a repro directory, or None if missing."""
    path = repro_path(repro_dir, filename)
    if os.path.exists(path):
        return open(path).read().strip()
    return None


def write_state_file(repro_dir: str, filename: str, value: str) -> None:
    """Write a state file to a repro directory."""
    ensure_dir(repro_path(repro_dir))
    with open(repro_path(repro_dir, filename), "w") as f:
        f.write(value)


def load_state(repro_dir: str) -> dict:
    """Load all state files from a repro directory into memory."""
    state = {}
    for key, filename in [("port", "port"), ("session_token", "session-token"), ("appdb_port", "appdb-port")]:
        val = read_state_file(repro_dir, filename)
        if val:
            state[key] = val
    _sessions[repro_dir] = state
    return state


def get_state(repro_dir: str) -> dict:
    """Get state from cache or load from files."""
    if repro_dir in _sessions:
        return _sessions[repro_dir]
    return load_state(repro_dir)


def clear_state(repro_dir: str) -> None:
    """Remove cached state for a repro directory."""
    _sessions.pop(repro_dir, None)


def pick_port() -> int:
    """Pick a random available port in [10000, 62535]."""
    for _ in range(100):
        port = random.randint(10000, 62535)
        try:
            s = socket.socket()
            s.bind(("", port))
            s.close()
            return port
        except OSError:
            continue
    raise RuntimeError("Could not find an available port after 100 attempts")


def run(cmd: list[str], timeout: int = 300, cwd: str | None = None,
        input_data: str | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """Run a command from the project root (or specified cwd)."""
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=cwd or PROJECT_ROOT,
        timeout=timeout,
        input=input_data,
        env=env,
    )


def kill_tree(pid: int) -> None:
    """Recursively kill a process and all its descendants."""
    try:
        children_out = subprocess.run(
            ["pgrep", "-P", str(pid)],
            capture_output=True, text=True
        ).stdout.strip()
        for child_pid in children_out.split():
            if child_pid:
                kill_tree(int(child_pid))
    except (ValueError, ProcessLookupError):
        pass
    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass


def is_pid_running(pid: int) -> bool:
    """Check if a process is running."""
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError, ValueError):
        return False


def truncate_output(text: str, max_chars: int = 8000) -> str:
    """Truncate output to max_chars, keeping head and tail with a banner.

    When truncated, the full output is saved to a temp file and the banner
    includes the path so the agent can read it if needed.
    """
    if len(text) <= max_chars:
        return text
    import tempfile
    fd, path = tempfile.mkstemp(prefix="repro-output-", suffix=".txt")
    with os.fdopen(fd, "w") as f:
        f.write(text)
    keep = max_chars // 2
    banner = (f"\n\n... ({len(text) - max_chars} chars truncated) ...\n"
              f"Full output saved to: {path}\n"
              f"Use the Read tool to view the full output if needed.\n\n")
    return text[:keep] + banner + text[-keep:]


def format_result(stdout: str = "", stderr: str = "", returncode: int = 0) -> str:
    """Format a command result for MCP tool output."""
    output = stdout
    if stderr:
        output += stderr
    if returncode != 0:
        return f"ERROR (exit {returncode}):\n{output}"
    return output
