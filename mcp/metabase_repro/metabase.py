"""Metabase instance lifecycle: download, start, stop, reset, session management."""
from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
import time
import zipfile
from datetime import datetime, timezone
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


def _current_log_path(repro_dir: str) -> str:
    """Return the path to the current (most recent) Metabase log file."""
    log_file = read_state_file(repro_dir, "log-file")
    if log_file:
        return repro_path(repro_dir, log_file)
    # Fallback: find the most recent metabase.*.log, or legacy metabase.log
    logs = sorted(glob.glob(repro_path(repro_dir, "metabase.*.log")))
    if logs:
        return logs[-1]
    return repro_path(repro_dir, "metabase.log")


def _read_log_tail(repro_dir: str, n: int = 10) -> str:
    """Read the last n lines of the Metabase log file."""
    try:
        with open(_current_log_path(repro_dir)) as f:
            lines = f.readlines()
            return "".join(lines[-n:])
    except Exception:
        return "(could not read log)"


def check_setup_token(port: int) -> str:
    """Check if a Metabase instance needs setup. Returns token or empty string."""
    token = _get_setup_token(port)
    return token or ""


def _read_main_class(jar_path: str) -> str:
    """Read Main-Class from a JAR's META-INF/MANIFEST.MF. Falls back to 'metabase.core'."""
    try:
        with zipfile.ZipFile(jar_path) as zf:
            manifest = zf.read("META-INF/MANIFEST.MF").decode("utf-8")
            for line in manifest.splitlines():
                if line.startswith("Main-Class:"):
                    return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return "metabase.core"


def _parse_env_edn(path: str) -> dict[str, str]:
    """Parse an env.edn file into environment variables.

    Converts keys like :mb-db-type to MB_DB_TYPE.
    """
    env_vars = {}
    try:
        with open(path) as f:
            content = f.read()
        for m in re.finditer(r':(\S+)\s+"([^"]*)"', content):
            key = m.group(1).upper().replace("-", "_")
            env_vars[key] = m.group(2)
    except FileNotFoundError:
        pass
    return env_vars


def _start_nrepl(repro_dir: str, nrepl_port: int) -> str | None:
    """Start an nREPL server inside the running Metabase via socket REPL.

    Returns error message or None on success.
    """
    from .repl import _socket_repl_eval
    code = f"(require 'nrepl.server) (nrepl.server/start-server :port {nrepl_port})"
    result = _socket_repl_eval(repro_dir, code, timeout=30)
    if result.startswith("ERROR"):
        return result
    return None


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

    # Require source worktree for clj-based startup
    source_dir = repro_path(repro_dir, "source")
    if not os.path.isdir(source_dir):
        return "ERROR: Source worktree not found. Run setup_worktree before start_metabase."

    abs_env = repro_path(repro_dir, "env.edn")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    log_filename = f"metabase.{timestamp}.log"
    log_path = repro_path(repro_dir, log_filename)
    write_state_file(repro_dir, "log-file", log_filename)

    jar_path = jars[0]
    repl_port = port + 3000
    nrepl_port = port + 4000

    # Build env vars from env.edn
    env = os.environ.copy()
    env.update(_parse_env_edn(abs_env))
    env["MB_JETTY_PORT"] = str(port)

    # EE config file for auto-setup
    config_file = os.path.join(PROJECT_ROOT, "repro", "master", "mage", "jar_download_config.yml")
    if os.path.exists(config_file):
        env["MB_CONFIG_FILE_PATH"] = config_file

    # Compute classpath from worktree deps, then append the JAR.
    # tools.deps :extra-paths and :local/root don't work for plain JARs,
    # so we resolve the classpath separately and launch with java -cp.
    cp_result = subprocess.run(
        ["clojure", "-Spath", "-A:dev:ee:ee-dev"],
        capture_output=True, text=True, cwd=source_dir, env=env,
    )
    if cp_result.returncode != 0:
        return f"ERROR: Failed to compute classpath:\n{cp_result.stderr}"
    base_cp = cp_result.stdout.strip()
    # Filter out the worktree's resources/ dir to avoid duplicate resource
    # conflicts with the JAR (e.g. liquibase.yaml). The JAR already contains
    # all production resources. Keep test_resources and library resource paths.
    filtered_cp = ":".join(
        p for p in base_cp.split(":")
        if p not in ("resources", "resources/")
    )
    full_cp = f"{jar_path}:{filtered_cp}"

    main_class = _read_main_class(jar_path)

    cmd = [
        "java",
        f"-Dclojure.server.repl={{:port {repl_port} :accept clojure.core.server/repl}}",
        "-cp", full_cp,
        "clojure.main", "-m", main_class,
    ]

    with open(log_path, "w") as log_file:
        proc = subprocess.Popen(
            cmd,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            cwd=source_dir,
            env=env,
        )

    write_state_file(repro_dir, "metabase.pid", str(proc.pid))
    write_state_file(repro_dir, "port", str(port))

    # Wait for health check (up to 5 minutes)
    healthy = False
    for i in range(60):
        if proc.poll() is not None:
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
        write_state_file(repro_dir, "session-token-crowberto@metabase.com", token)
    else:
        setup_error = f"Could not obtain session token: {session_err}"

    # Start nREPL server inside the running Metabase
    nrepl_error = _start_nrepl(repro_dir, nrepl_port)
    if nrepl_error:
        nrepl_status = f"nREPL failed: {nrepl_error}"
    else:
        write_state_file(repro_dir, "nrepl-port", str(nrepl_port))
        nrepl_status = f"nREPL on port {nrepl_port}"

    load_state(repro_dir)

    # Return only the summary block
    lines = [
        f"=== Metabase Ready ===",
        f"Edition:     {edition}",
        f"Port:        {port}",
        f"REPL:        socket={repl_port}, {nrepl_status}",
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
    """Kill the Metabase process. Preserves DB, env, worktree, and appdb."""
    pid_str = read_state_file(repro_dir, "metabase.pid")
    if not pid_str:
        return f"No running Metabase process found for {repro_dir}."
    try:
        pid = int(pid_str)
        if is_pid_running(pid):
            kill_tree(pid)
            try:
                os.remove(repro_path(repro_dir, "metabase.pid"))
            except FileNotFoundError:
                pass
            return f"Stopped Metabase process (PID {pid}) for {repro_dir}. DB, env, and worktree preserved."
        else:
            try:
                os.remove(repro_path(repro_dir, "metabase.pid"))
            except FileNotFoundError:
                pass
            return f"Metabase process (PID {pid}) was not running. Cleaned up PID file."
    except ValueError:
        return f"ERROR: Invalid PID in state file: {pid_str}"


def cleanup(repro_dir: str) -> str:
    """Remove source worktree, stop appdb, and clear state for a repro directory.

    Also stops Metabase if still running.
    """
    actions = []

    # Stop Metabase process if still running
    result = stop_metabase(repro_dir)
    if "Stopped Metabase" in result:
        actions.append(result.split(". ")[0])

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
        return f"Cleaned up {repro_dir}: {', '.join(actions)}."
    return f"Cleaned up {repro_dir}: nothing to clean."


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

    # Remove stale state files
    for f in ["port", "nrepl-port"]:
        try:
            os.remove(repro_path(repro_dir, f))
        except FileNotFoundError:
            pass
    # Remove all per-user session token files
    for f in glob.glob(repro_path(repro_dir, "session-token-*")):
        try:
            os.remove(f)
        except FileNotFoundError:
            pass

    clear_state(repro_dir)
    return f"Reset complete. Removed H2 DB and logs for {repro_dir}. Ready for fresh start."
