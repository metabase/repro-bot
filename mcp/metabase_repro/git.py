"""Git worktree management: master worktree, per-issue worktrees, patch generation."""
from __future__ import annotations

import os

from .core import PROJECT_ROOT, repro_path, ensure_dir, run


def setup_master_worktree() -> str:
    """Create or update the repro/master worktree from the bare clone."""
    bare_repo = os.path.join(PROJECT_ROOT, "git", "metabase")
    master_dir = os.path.join(PROJECT_ROOT, "repro", "master")

    messages = []

    if not os.path.isdir(bare_repo):
        messages.append(f"Bare repo not found at {bare_repo}, cloning from GitHub...")
        messages.append("WARNING: This will download ~1.6GB and may take several minutes.")
        os.makedirs(os.path.dirname(bare_repo), exist_ok=True)
        result = run(["git", "clone", "--bare", "https://github.com/metabase/metabase.git", bare_repo])
        if result.returncode != 0:
            return f"ERROR: Failed to clone bare repo:\n{result.stderr}"
        messages.append("Bare repo cloned successfully.")

    messages.append("Fetching latest from bare clone...")
    result = run(["git", "-C", bare_repo, "fetch", "origin"])
    if result.returncode != 0:
        return f"ERROR fetching:\n{result.stderr}"

    if os.path.isdir(master_dir):
        messages.append("Updating existing master worktree...")
        # Try checkout master, create if needed
        result = run(["git", "-C", master_dir, "checkout", "master"])
        if result.returncode != 0:
            result = run(["git", "-C", master_dir, "checkout", "-b", "master", "origin/master"])
        if result.returncode != 0:
            return f"ERROR checking out master:\n{result.stderr}"

        result = run(["git", "-C", master_dir, "pull", "origin", "master"])
        if result.returncode != 0:
            return f"ERROR pulling master:\n{result.stderr}"
    else:
        messages.append(f"Creating master worktree at {master_dir}...")
        result = run(["git", "-C", bare_repo, "worktree", "add", master_dir, "master"])
        if result.returncode != 0:
            return f"ERROR creating worktree:\n{result.stderr}"

    messages.append(f"Master worktree ready at {master_dir}")
    return "\n".join(messages)


def _resolve_ref(bare_repo: str, version_ref: str, messages: list[str]) -> tuple[str | None, str | None]:
    """Try version_ref, then OSS fallback, then fetch+retry. Returns (resolved_ref, error)."""
    refs_to_try = [version_ref]
    if version_ref.startswith("v1."):
        refs_to_try.append("v0." + version_ref[3:])

    for ref in refs_to_try:
        result = run(["git", "-C", bare_repo, "rev-parse", "--verify", ref])
        if result.returncode == 0:
            if ref != version_ref:
                messages.append(f"Tag {version_ref} not found, using OSS tag {ref}")
            return ref, None

    # Fetch all tags and retry
    messages.append("Tags not found locally, fetching all tags...")
    run(["git", "-C", bare_repo, "fetch", "origin", "--tags"])

    for ref in refs_to_try:
        result = run(["git", "-C", bare_repo, "rev-parse", "--verify", ref])
        if result.returncode == 0:
            if ref != version_ref:
                messages.append(f"Using OSS tag {ref}")
            return ref, None

    return None, f"ERROR: Could not resolve ref {version_ref} (also tried {refs_to_try})"


def setup_worktree(repro_dir: str, version_ref: str) -> str:
    """Create a repro directory and source worktree pinned to a specific version.

    Reuses existing worktree at the correct version, or switches in-place.
    Auto-normalizes EE tags (v1.x.y) to OSS tags (v0.x.y) and fetches missing tags.
    """
    bare_repo = os.path.join(PROJECT_ROOT, "git", "metabase")

    ensure_dir(repro_path(repro_dir))
    ensure_dir(repro_path(repro_dir, "playwright"))
    worktree_path = repro_path(repro_dir, "source")

    messages = []

    # Resolve the ref (with EE→OSS fallback and auto-fetch)
    resolved_ref, error = _resolve_ref(bare_repo, version_ref, messages)
    if error:
        return error

    if os.path.isdir(worktree_path):
        # Check current version
        result = run(["git", "-C", worktree_path, "describe", "--tags", "--exact-match"])
        current_ref = result.stdout.strip() if result.returncode == 0 else ""
        if not current_ref:
            result = run(["git", "-C", worktree_path, "rev-parse", "--short", "HEAD"])
            current_ref = result.stdout.strip()

        if current_ref == resolved_ref:
            messages.append(f"Worktree already at {resolved_ref}, reusing.")
            _pre_resolve_dev_classpath(worktree_path, messages)
            return "\n".join(messages)
        else:
            messages.append(f"Worktree exists at {current_ref}, switching to {resolved_ref}...")
            result = run(["git", "-C", worktree_path, "checkout", resolved_ref])
            if result.returncode != 0:
                return f"ERROR switching worktree:\n{result.stderr}"
            messages.append(f"Worktree switched to {resolved_ref}")
            _pre_resolve_dev_classpath(worktree_path, messages)
            return "\n".join(messages)

    messages.append(f"Creating worktree at {worktree_path} from {resolved_ref}...")
    result = run(["git", "-C", bare_repo, "worktree", "add", "--detach", worktree_path, resolved_ref])
    if result.returncode != 0:
        return f"ERROR creating worktree:\n{result.stderr}"

    messages.append(f"Worktree ready at {worktree_path}")

    # After worktree is ready, pre-resolve dev classpath (non-fatal)
    _pre_resolve_dev_classpath(worktree_path, messages)

    return "\n".join(messages)


def _pre_resolve_dev_classpath(source_dir: str, messages: list[str]):
    """Pre-resolve :dev alias Maven deps and cache the JAR list."""
    cache_file = os.path.join(source_dir, ".dev-classpath")
    if os.path.exists(cache_file):
        messages.append("Dev classpath already cached.")
        return
    try:
        result = run(["clj", "-A:dev", "-Spath"], cwd=source_dir, timeout=500)
        if result.returncode != 0:
            messages.append(f"WARNING: Dev classpath resolution failed: {result.stderr[:200]}")
            return
        jars = [p for p in result.stdout.strip().split(":") if p.endswith(".jar")]
        with open(cache_file, "w") as f:
            f.write("\n".join(jars))
        messages.append(f"Dev classpath cached ({len(jars)} JARs).")
    except FileNotFoundError:
        messages.append("WARNING: clj not found — dev classpath not cached.")
    except Exception as e:
        messages.append(f"WARNING: Dev classpath resolution failed: {e}")


def save_test_patch(repro_dir: str) -> str:
    """Generate a git diff of all changes in the source worktree and save as a patch."""
    source_dir = repro_path(repro_dir, "source")
    patch_file = repro_path(repro_dir, "test-diff.patch")

    if not os.path.isdir(source_dir):
        return f"ERROR: Source worktree not found at {source_dir}"

    # Collect tracked changes
    result = run(["git", "diff"], cwd=source_dir)
    diff = result.stdout

    result = run(["git", "diff", "--cached"], cwd=source_dir)
    diff += result.stdout

    # Collect untracked files
    result = run(["git", "ls-files", "--others", "--exclude-standard"], cwd=source_dir)
    for f in result.stdout.strip().split("\n"):
        if f:
            result2 = run(["git", "diff", "--no-index", "/dev/null", f], cwd=source_dir)
            diff += result2.stdout

    if not diff.strip():
        return "No changes found — nothing to save."

    with open(patch_file, "w") as pf:
        pf.write(diff)

    line_count = diff.count("\n")
    return f"Patch saved: {patch_file} ({line_count} lines)"
