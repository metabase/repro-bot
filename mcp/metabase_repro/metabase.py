"""Metabase instance lifecycle: download, start, stop, reset, session management."""
from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request

from .core import (
    PROJECT_ROOT, pick_port, repro_path, ensure_dir,
    write_state_file, read_state_file, load_state, clear_state,
    run, kill_tree, is_pid_running,
)
from .appdb import stop_appdb, create_env


def jar_download(version: str) -> str:
    """Download Metabase JAR to ./downloads/ using mage from the master worktree."""
    master_dir = os.path.join(PROJECT_ROOT, "repro", "master")
    if not os.path.isdir(master_dir):
        return "ERROR: Master worktree not found at repro/master. Run setup_master_worktree first."

    downloads_dir = os.path.join(PROJECT_ROOT, "downloads")
    os.makedirs(downloads_dir, exist_ok=True)

    result = run(
        [os.path.join(master_dir, "bin", "mage"), "jar-download", version, downloads_dir],
        cwd=master_dir,
        timeout=600,
    )
    if result.returncode != 0:
        return f"ERROR downloading JAR:\n{result.stdout}\n{result.stderr}"

    # Verify a JAR exists
    jars = sorted(glob.glob(os.path.join(downloads_dir, "metabase_*.jar")), key=os.path.getmtime, reverse=True)
    if not jars:
        return "ERROR: No JAR file found in downloads/ after download."

    return f"Download complete: {os.path.basename(jars[0])}"


def _get_setup_token(port: int) -> str | None:
    """Check if a Metabase instance needs initial setup. Returns token or None."""
    try:
        req = urllib.request.Request(f"http://localhost:{port}/api/session/properties")
        resp = urllib.request.urlopen(req, timeout=10)
        props = json.loads(resp.read().decode())
        token = props.get("setup-token") or None
        return token
    except Exception:
        return None


def _do_setup(port: int, setup_token: str, password: str) -> tuple[bool, str]:
    """Run /api/setup for OSS jars. Returns (success, message)."""
    data = json.dumps({
        "token": setup_token,
        "user": {
            "email": "crowberto@metabase.com",
            "password": password,
            "first_name": "Crowberto",
            "last_name": "Corv",
            "site_name": "Metabase Repro",
        },
        "prefs": {
            "site_name": "Metabase Repro",
            "site_locale": "en",
            "allow_tracking": False,
        },
    }).encode()

    last_error = ""
    for attempt in range(3):
        if attempt > 0:
            time.sleep(2)
        try:
            req = urllib.request.Request(
                f"http://localhost:{port}/api/setup",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=30)
            return True, "OK"
        except urllib.error.HTTPError as e:
            error_body = ""
            try:
                error_body = e.read().decode("utf-8")
            except Exception:
                pass
            last_error = f"HTTP {e.code}: {error_body}"
        except Exception as e:
            last_error = str(e)
    return False, last_error


def get_session_token(port: int, email: str = "crowberto@metabase.com",
                      password: str | None = None) -> tuple[str | None, str]:
    """Authenticate and return (session_token, error_message).

    If password is None, tries EE (blackjet) then OSS (1Blackjet!).
    """
    passwords = [password] if password else ["blackjet", "1Blackjet!"]
    last_error = ""
    for pw in passwords:
        try:
            data = json.dumps({"username": email, "password": pw}).encode()
            req = urllib.request.Request(
                f"http://localhost:{port}/api/session",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            resp = urllib.request.urlopen(req, timeout=10)
            return json.loads(resp.read().decode())["id"], ""
        except urllib.error.HTTPError as e:
            error_body = ""
            try:
                error_body = e.read().decode("utf-8")
            except Exception:
                pass
            last_error = f"HTTP {e.code} (pw={pw}): {error_body}"
        except Exception as e:
            last_error = f"{e} (pw={pw})"
    return None, last_error


def _read_log_tail(repro_dir: str, n: int = 10) -> str:
    """Read the last n lines of the Metabase log file."""
    try:
        with open(repro_path(repro_dir, "metabase.log")) as f:
            lines = f.readlines()
            return "".join(lines[-n:])
    except Exception:
        return "(could not read log)"


def check_setup_token(port: int) -> str:
    """Check if a Metabase instance needs setup. Returns token or empty string."""
    token = _get_setup_token(port)
    return token or ""


def start_metabase(repro_dir: str, version: str, port: int | None = None) -> str:
    """Start a Metabase instance. Handles JAR download, env creation, startup, and setup.

    Returns a summary of the running instance.
    """
    ensure_dir(repro_path(repro_dir))

    if port is None:
        port = pick_port()

    master_dir = os.path.join(PROJECT_ROOT, "repro", "master")
    if not os.path.isdir(master_dir):
        return "ERROR: Master worktree not found at repro/master. Run setup_master_worktree first."

    downloads_dir = os.path.join(PROJECT_ROOT, "downloads")

    # Check if env.edn exists, create default H2 if not
    env_path = repro_path(repro_dir, "env.edn")
    if not os.path.exists(env_path):
        # Check if appdb was set up
        appdb_port = read_state_file(repro_dir, "appdb-port")
        if appdb_port:
            # Detect db type from container name
            container_name = read_state_file(repro_dir, "appdb-container.txt") or ""
            db_type = "h2"
            for dt in ["postgres", "mysql", "mariadb"]:
                if dt in container_name:
                    db_type = dt
                    break
            create_env(repro_dir, db_type, appdb_port)
        else:
            create_env(repro_dir, "h2")

    # Download JAR (idempotent — mage skips if already present)
    dl_result = jar_download(version)
    if dl_result.startswith("ERROR"):
        return dl_result

    # Find the JAR
    jars = sorted(glob.glob(os.path.join(downloads_dir, "metabase_*.jar")), key=os.path.getmtime, reverse=True)
    if not jars:
        return "ERROR: No JAR found in downloads/."

    abs_repro = repro_path(repro_dir)
    abs_env = repro_path(repro_dir, "env.edn")
    log_path = repro_path(repro_dir, "metabase.log")

    # Start via mage jar-download --run
    with open(log_path, "w") as log_file:
        proc = subprocess.Popen(
            [os.path.join(master_dir, "bin", "mage"), "jar-download", version, downloads_dir,
             "--run", "--port", str(port), "-e", abs_env],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            cwd=master_dir,
        )

    write_state_file(repro_dir, "metabase.pid", str(proc.pid))
    write_state_file(repro_dir, "port", str(port))

    # Wait for health check (up to 5 minutes)
    healthy = False
    for i in range(60):
        if not is_pid_running(proc.pid):
            tail = _read_log_tail(repro_dir)
            return f"ERROR: Metabase process died.\nLast log lines:\n{tail}"

        try:
            resp = urllib.request.urlopen(f"http://localhost:{port}/api/health", timeout=5)
            body = json.loads(resp.read().decode())
            if body.get("status") == "ok":
                healthy = True
                break
        except Exception:
            pass
        time.sleep(5)

    if not healthy:
        tail = _read_log_tail(repro_dir)
        return f"ERROR: Timeout waiting for Metabase after 5 minutes.\nLast log lines:\n{tail}"

    # Determine edition and run setup
    # Strategy: try to authenticate first (EE config-file setup may have already
    # created the user), then fall back to OSS auto-setup if login fails.
    token = None
    edition = "unknown"
    password = ""
    setup_error = ""

    # Try to authenticate — EE config-file setup may have already created the user
    token, _ = get_session_token(port)  # tries both passwords (EE then OSS)
    if token:
        edition = "EE"
        password = "blackjet"
    else:
        # Not set up yet — check for setup token and run OSS setup
        setup_token = _get_setup_token(port)
        if setup_token:
            edition = "OSS"
            password = "1Blackjet!"
            ok, setup_msg = _do_setup(port, setup_token, password)
            if not ok:
                setup_error = f"OSS auto-setup failed: {setup_msg}"
        else:
            # No setup token and no login worked — wait for config-file setup
            for _ in range(6):  # up to 30 seconds
                time.sleep(5)
                token, _ = get_session_token(port)
                if token:
                    break
            edition = "EE"
            password = "blackjet"

    # Get session token (if not already obtained)
    if not token:
        token, session_err = get_session_token(port)
    if token:
        write_state_file(repro_dir, "session-token", token)
    else:
        setup_error = f"Could not obtain session token: {session_err}"

    load_state(repro_dir)

    # Return only the summary block
    lines = [
        f"=== Metabase Ready ===",
        f"Edition:     {edition}",
        f"Port:        {port}",
        f"Credentials: crowberto@metabase.com / {password}",
        f"URL:         http://localhost:{port}",
    ]
    if token:
        lines.append(f"Session:     {token}")
    if setup_error:
        lines.append(f"WARNING:     {setup_error}")
    lines.append("=====================")

    return "\n".join(lines)


def stop_metabase(repro_dir: str) -> str:
    """Kill Metabase process tree, remove source worktree, stop appdb."""
    actions = []

    # Kill Metabase process
    pid_str = read_state_file(repro_dir, "metabase.pid")
    if pid_str:
        try:
            pid = int(pid_str)
            if is_pid_running(pid):
                kill_tree(pid)
                actions.append(f"stopped Metabase (PID {pid})")
        except ValueError:
            pass
        try:
            os.remove(repro_path(repro_dir, "metabase.pid"))
        except FileNotFoundError:
            pass

    # Stop appdb
    container_name = read_state_file(repro_dir, "appdb-container.txt")
    stop_appdb(repro_dir)
    if container_name:
        actions.append(f"stopped appdb container '{container_name}'")

    # Remove source worktree
    bare_repo = os.path.join(PROJECT_ROOT, "git", "metabase")
    worktree_path = repro_path(repro_dir, "source")
    if os.path.isdir(worktree_path):
        result = run(["git", "-C", bare_repo, "worktree", "remove", "--force", worktree_path])
        if result.returncode != 0:
            shutil.rmtree(worktree_path, ignore_errors=True)
        actions.append("removed source worktree")

    clear_state(repro_dir)

    if actions:
        return f"Stopped {repro_dir}: {', '.join(actions)}."
    return f"Stopped {repro_dir}: nothing was running."


def reset_metabase(repro_dir: str) -> str:
    """Kill Metabase process and remove DB/log files. Keep env and worktree."""
    # Kill process
    pid_str = read_state_file(repro_dir, "metabase.pid")
    if pid_str:
        try:
            pid = int(pid_str)
            if is_pid_running(pid):
                kill_tree(pid)
        except ValueError:
            pass
        try:
            os.remove(repro_path(repro_dir, "metabase.pid"))
        except FileNotFoundError:
            pass

    # Remove H2 DB files
    for f in ["metabase.mv.db", "metabase.trace.db"]:
        try:
            os.remove(repro_path(repro_dir, f))
        except FileNotFoundError:
            pass

    # Remove log
    try:
        os.remove(repro_path(repro_dir, "metabase.log"))
    except FileNotFoundError:
        pass

    # Remove stale state files
    for f in ["port", "session-token"]:
        try:
            os.remove(repro_path(repro_dir, f))
        except FileNotFoundError:
            pass

    clear_state(repro_dir)
    return f"Reset complete. Removed H2 DB and logs for {repro_dir}. Ready for fresh start."
