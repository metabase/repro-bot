"""Browser snapshot tool — saves full YAML to file, returns compact summary."""
from __future__ import annotations

import os
import re
import subprocess
import time

from .core import PROJECT_ROOT

INTERACTIVE_RE = re.compile(
    r'(button|textbox|link|checkbox|tab|combobox|select|radio|switch|slider|menuitem)'
    r'\s+"([^"]*)"'
    r'.*\[ref=(e\d+)\]'
)

MAX_ELEMENTS = 20


def browser_snapshot(repro_dir: str, name: str = "") -> str:
    """Take a page snapshot, save YAML to file, return compact summary."""
    abs_repro = os.path.join(PROJECT_ROOT, repro_dir)
    pw_dir = os.path.join(abs_repro, "playwright")
    os.makedirs(pw_dir, exist_ok=True)

    if not name:
        name = str(int(time.time()))
    filename = os.path.join(pw_dir, f"{name}.yaml")

    result = subprocess.run(
        ["playwright-cli", "snapshot", f"--filename={filename}"],
        capture_output=True,
        text=True,
        timeout=30,
    )

    if result.returncode != 0:
        err = result.stderr.strip() or result.stdout.strip()
        return f"ERROR: playwright-cli snapshot failed (exit {result.returncode}): {err}"

    if not os.path.exists(filename):
        return f"ERROR: Snapshot file not created at {filename}"

    with open(filename) as f:
        lines = f.readlines()

    total_lines = len(lines)

    # Extract interactive elements
    elements: list[tuple[str, str, str]] = []
    for line in lines:
        m = INTERACTIVE_RE.search(line)
        if m and len(elements) < MAX_ELEMENTS:
            elements.append((m.group(3), m.group(1), m.group(2)))

    # Build compact summary
    rel_path = os.path.relpath(filename, PROJECT_ROOT)
    parts = [f"Snapshot saved: ./{rel_path} ({total_lines} lines)"]

    if elements:
        parts.append("\nInteractive elements:")
        for ref, etype, label in elements:
            parts.append(f"  {ref}: {etype} \"{label}\"")
        if len(elements) == MAX_ELEMENTS:
            parts.append(f"  ... (capped at {MAX_ELEMENTS}, see full YAML for more)")
    else:
        parts.append("\nNo interactive elements found.")

    parts.append(f"\nUse Read tool on ./{rel_path} to inspect full page structure.")

    return "\n".join(parts)
