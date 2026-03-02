"""Metabase API calls: authenticated HTTP requests using state files."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from .core import read_state_file


def api_call(repro_dir: str, method: str, path: str,
             body: str = "", jq_filter: str = "") -> str:
    """Make an authenticated API call to a running Metabase instance.

    Reads port and session token from state files. Falls back to API key.
    jq_filter is applied in Python (basic key access only — for complex
    filtering, use the raw JSON and process client-side).

    Returns JSON response as formatted string.
    """
    port = read_state_file(repro_dir, "port")
    if not port:
        return f"ERROR: No port file found at {repro_dir}/port. Is Metabase running?"

    # Build auth header
    session_token = read_state_file(repro_dir, "session-token")
    headers: dict[str, str] = {}
    if session_token:
        headers["X-Metabase-Session"] = session_token
    else:
        headers["x-api-key"] = "mb_adminapikey"

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
        return f"HTTP {e.code} {e.reason}\n{error_body}"
    except urllib.error.URLError as e:
        return f"ERROR: Connection failed: {e.reason}"
    except Exception as e:
        return f"ERROR: {e}"

    # Try to format as JSON
    try:
        parsed = json.loads(raw)
        if jq_filter:
            parsed = _apply_filter(parsed, jq_filter)
        return json.dumps(parsed, indent=2)
    except (json.JSONDecodeError, ValueError):
        return raw


def _apply_filter(data, filter_expr: str):
    """Apply a simple jq-like filter. Supports:
    - .key — access object key
    - .key1.key2 — nested access
    - .[N] — array index
    - .[] — iterate array
    - .[].key — map over array extracting key

    For complex filters, returns data unchanged with a note.
    """
    if not filter_expr or filter_expr == ".":
        return data

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
