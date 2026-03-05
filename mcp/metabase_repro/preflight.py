"""Pre-flight checks: verify environment, tools, and MCP servers are available."""
from __future__ import annotations

import os
import shutil
import subprocess


def check_setup() -> str:
    """Verify all required environment variables, tools, and MCP servers.

    Returns a report of what's OK and what's missing. Exits with error
    summary if anything critical is missing.
    """
    messages = []
    ok = True

    # --- Environment variables ---
    if not os.environ.get("MB_PREMIUM_EMBEDDING_TOKEN"):
        messages.append("MISSING: MB_PREMIUM_EMBEDDING_TOKEN is not set")
        ok = False
    else:
        messages.append("OK: MB_PREMIUM_EMBEDDING_TOKEN is set")

    # --- CLI tools ---
    if not shutil.which("gh"):
        messages.append("MISSING: gh CLI is not installed")
        ok = False
    else:
        result = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
        if result.returncode != 0:
            messages.append("MISSING: gh CLI is not authenticated (run 'gh auth login')")
            ok = False
        else:
            messages.append("OK: gh CLI is authenticated")

    if not shutil.which("jq"):
        messages.append("MISSING: jq is not installed")
        ok = False
    else:
        messages.append("OK: jq is installed")

    if not shutil.which("docker"):
        messages.append("WARN: docker not installed (needed for Postgres/MySQL appdb issues)")
    else:
        result = subprocess.run(["docker", "info"], capture_output=True, text=True)
        if result.returncode != 0:
            messages.append("WARN: docker daemon not running (needed for Postgres/MySQL appdb issues)")
        else:
            messages.append("OK: docker is available")

    # --- Playwright CLI ---
    if shutil.which("playwright-cli"):
        messages.append("OK: playwright-cli is installed")
    else:
        # Check if available via npx
        npx_result = subprocess.run(
            ["npx", "playwright-cli", "--version"],
            capture_output=True, text=True, timeout=15,
        )
        if npx_result.returncode == 0:
            messages.append("OK: playwright-cli is available via npx")
        else:
            messages.append(
                "MISSING: playwright-cli is not installed "
                "(run 'npm install -g @playwright/cli@latest && playwright-cli install --skills')"
            )
            ok = False

    # --- Result ---
    if not ok:
        messages.append("")
        messages.append("Pre-flight check FAILED. Fix the issues above before proceeding.")
    else:
        messages.append("")
        messages.append("All checks passed.")

    return "\n".join(messages)
