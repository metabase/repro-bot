"""Metabase API calls: authenticated HTTP requests using state files."""
from __future__ import annotations

import json
import shutil
import subprocess
import urllib.error
import urllib.request

from .core import read_state_file


def api_call(repro_dir: str, method: str, path: str,
             email: str = "crowberto@metabase.com",
             body: str = "", jq_filter: str = "",
             max_response_chars: int = 10000) -> str:
    """Make an authenticated API call to a running Metabase instance.

    Reads port and per-user session token from state files.
    Every call must include email (defaults to crowberto@metabase.com).
    Call get_session_token for each user before making API calls as them.

    Returns JSON response as formatted string.
    """
    port = read_state_file(repro_dir, "port")
    if not port:
        return f"ERROR: No port file found at {repro_dir}/port. Is Metabase running?"

    # Build auth header from per-user session token
    session_token = read_state_file(repro_dir, f"session-token-{email}")
    headers: dict[str, str] = {}
    if session_token:
        headers["X-Metabase-Session"] = session_token
    else:
        return f"ERROR: No session token for {email}. Call get_session_token first."

    # Defensive: strip /api/ prefix if caller included it (common mistake)
    if path.startswith("/api/"):
        path = path[4:]
    url = f"http://localhost:{port}/api{path}"

    # Build request
    data = None
    if body:
        data = body.encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    try:
        resp = urllib.request.urlopen(req, timeout=30)
        raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        error_body = ""
        try:
            error_body = e.read().decode("utf-8")
        except Exception:
            pass
        truncated = error_body[:500] + ("..." if len(error_body) > 500 else "")
        return f"HTTP {e.code} {e.reason}\n{truncated}"
    except urllib.error.URLError as e:
        return f"ERROR: Connection failed: {e.reason}"
    except Exception as e:
        return f"ERROR: {e}"

    # Try to format as JSON
    try:
        parsed = json.loads(raw)
        if jq_filter:
            parsed = _apply_filter(parsed, jq_filter)
        formatted = json.dumps(parsed, indent=2)
        if len(formatted) > max_response_chars:
            formatted = formatted[:max_response_chars] + f"\n... (truncated, {len(formatted)} total chars. Use jq_filter to narrow results)"
        return formatted
    except (json.JSONDecodeError, ValueError):
        return raw


def _is_simple_filter(expr: str) -> bool:
    """Check if a jq filter uses only simple syntax we handle in Python."""
    # Simple: .key, .key1.key2, .[N], .[], .[].key
    # Complex: anything with |, map, select, @, if, etc.
    for token in ["|", "map", "select", "@", "if ", "as ", "def ", "reduce"]:
        if token in expr:
            return False
    return True


def _apply_filter(data, filter_expr: str):
    """Apply a jq-like filter. Simple patterns handled in Python; complex
    patterns delegate to the real jq binary if available."""
    if not filter_expr or filter_expr == ".":
        return data

    if not _is_simple_filter(filter_expr) and shutil.which("jq"):
        return _apply_jq_binary(data, filter_expr)

    return _apply_simple_filter(data, filter_expr)


def _apply_jq_binary(data, filter_expr: str):
    """Delegate filtering to the real jq binary."""
    try:
        result = subprocess.run(
            ["jq", filter_expr],
            input=json.dumps(data),
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return {"_jq_error": result.stderr.strip(), "_raw_data": "use jq_filter='' to see full response"}
        return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception) as e:
        return {"_jq_error": str(e), "_raw_data": "use jq_filter='' to see full response"}


def _apply_simple_filter(data, filter_expr: str):
    """Apply simple jq-like filters in Python. Supports:
    - .key — access object key
    - .key1.key2 — nested access
    - .[N] — array index
    - .[] — iterate array
    - .[].key — map over array extracting key
    """
    # Strip leading dot
    expr = filter_expr.lstrip(".")
    if not expr:
        return data

    parts = []
    current = ""
    i = 0
    while i < len(expr):
        if expr[i] == ".":
            if current:
                parts.append(current)
            current = ""
        elif expr[i] == "[":
            if current:
                parts.append(current)
                current = ""
            end = expr.index("]", i)
            parts.append(expr[i:end + 1])
            i = end
        else:
            current += expr[i]
        i += 1
    if current:
        parts.append(current)

    result = data
    for part in parts:
        try:
            if part == "[]":
                if isinstance(result, list):
                    continue  # Will be handled by next part
                return data
            elif part.startswith("[") and part.endswith("]"):
                idx = int(part[1:-1])
                result = result[idx]
            else:
                if isinstance(result, list):
                    result = [item.get(part) if isinstance(item, dict) else item for item in result]
                elif isinstance(result, dict):
                    result = result[part]
                else:
                    return data
        except (KeyError, IndexError, TypeError):
            return data

    return result
