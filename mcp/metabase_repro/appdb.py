"""Application database management: Docker containers + env file creation."""
from __future__ import annotations

import os
import subprocess
import time

from .core import (
    pick_port, repro_path, ensure_dir, write_state_file,
    read_state_file, run, PROJECT_ROOT,
)


def start_appdb(repro_dir: str, db_type: str = "mysql") -> str:
    """Start a Docker container for Postgres, MySQL 8.0, or MariaDB.

    Writes state files: appdb-port, appdb-container.txt.
    Returns status message with port info.
    """
    ensure_dir(repro_path(repro_dir))
    port = pick_port()
    container_name = f"mb-repro-appdb-{repro_dir.rstrip('/').split('/')[-1]}"

    docker_args = {
        "postgres": {
            "image": "postgres:latest",
            "internal_port": 5432,
            "env": {
                "POSTGRES_USER": "metabase",
                "POSTGRES_PASSWORD": "password",
                "POSTGRES_DB": "metabase",
            },
            "ready_cmd": ["pg_isready", "-U", "metabase", "-d", "metabase"],
        },
        "mysql": {
            "image": "mysql:8.0",
            "internal_port": 3306,
            "env": {
                "MYSQL_ROOT_PASSWORD": "metabase",
                "MYSQL_DATABASE": "metabase",
                "MYSQL_USER": "metabase",
                "MYSQL_PASSWORD": "metabase",
            },
            "ready_cmd": ["mysqladmin", "ping", "-h", "localhost", "-u", "metabase", "-pmetabase"],
        },
        "mariadb": {
            "image": "mariadb:latest",
            "internal_port": 3306,
            "env": {
                "MARIADB_ROOT_PASSWORD": "metabase",
                "MARIADB_DATABASE": "metabase",
                "MARIADB_USER": "metabase",
                "MARIADB_PASSWORD": "metabase",
            },
            "ready_cmd": ["mysqladmin", "ping", "-h", "localhost", "-u", "metabase", "-pmetabase"],
        },
    }

    if db_type not in docker_args:
        return f"ERROR: Unknown db_type '{db_type}'. Must be postgres, mysql, or mariadb."

    cfg = docker_args[db_type]

    # Build docker run command
    cmd = ["docker", "run", "-d", "--name", container_name, "-p", f"{port}:{cfg['internal_port']}"]
    for k, v in cfg["env"].items():
        cmd.extend(["-e", f"{k}={v}"])
    cmd.append(cfg["image"])

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return f"ERROR starting {db_type} container:\n{result.stderr}"

    # Wait for readiness
    messages = [f"Started {db_type} container '{container_name}' on port {port}"]
    ready = False
    for i in range(30):
        check = subprocess.run(
            ["docker", "exec", container_name] + cfg["ready_cmd"],
            capture_output=True, text=True,
        )
        if check.returncode == 0:
            ready = True
            break
        time.sleep(1)

    if not ready:
        return f"ERROR: {db_type} not ready after 30s"

    # Write state files
    write_state_file(repro_dir, "appdb-container.txt", container_name)
    write_state_file(repro_dir, "appdb-port", str(port))

    messages.append(f"{db_type} is ready. APPDB_PORT={port}")
    return "\n".join(messages)


def stop_appdb(repro_dir: str) -> str:
    """Stop and remove the appdb Docker container if one exists."""
    container_name = read_state_file(repro_dir, "appdb-container.txt")
    if not container_name:
        return "No appdb container found."

    subprocess.run(["docker", "kill", container_name], capture_output=True)
    subprocess.run(["docker", "rm", container_name], capture_output=True)

    marker = repro_path(repro_dir, "appdb-container.txt")
    if os.path.exists(marker):
        os.remove(marker)

    return f"Stopped and removed appdb container '{container_name}'."


def create_env(repro_dir: str, db_type: str = "h2", appdb_port: str = "") -> str:
    """Create the env.edn configuration file for a Metabase repro instance.

    Args:
        repro_dir: Path to repro directory
        db_type: h2, postgres, mysql, or mariadb
        appdb_port: Port for non-H2 databases
    """
    abs_repro = repro_path(repro_dir)
    ensure_dir(abs_repro)
    env_path = repro_path(repro_dir, "env.edn")

    configs = {
        "h2": f'''{{:mb-run-mode "dev"
 :mb-db-type "h2"
 :mb-db-file "{abs_repro}/metabase"}}''',
        "postgres": f'''{{:mb-run-mode "dev"
 :mb-db-type "postgres"
 :mb-db-host "localhost"
 :mb-db-port "{appdb_port}"
 :mb-db-dbname "metabase"
 :mb-db-user "metabase"
 :mb-db-pass "password"}}''',
        "mysql": f'''{{:mb-run-mode "dev"
 :mb-db-type "mysql"
 :mb-db-host "localhost"
 :mb-db-port "{appdb_port}"
 :mb-db-dbname "metabase"
 :mb-db-user "metabase"
 :mb-db-pass "metabase"}}''',
        "mariadb": f'''{{:mb-run-mode "dev"
 :mb-db-type "mysql"
 :mb-db-host "localhost"
 :mb-db-port "{appdb_port}"
 :mb-db-dbname "metabase"
 :mb-db-user "metabase"
 :mb-db-pass "metabase"}}''',
    }

    if db_type not in configs:
        return f"ERROR: Unknown db_type '{db_type}'. Must be h2, postgres, mysql, or mariadb."

    with open(env_path, "w") as f:
        f.write(configs[db_type] + "\n")

    return f"Created {env_path}"
