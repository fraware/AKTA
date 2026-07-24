"""Discover sibling repository paths for live trust-stack validation (v1.0 / WS12)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

_AKTA_ROOT = Path(__file__).resolve().parent.parent
_HOME = Path.home()

# Env var -> candidate directory names under the user's home (or AKTA parent).
_SIBLING_CANDIDATES: dict[str, list[str]] = {
    "SCOPE_REPO_PATH": ["SCOPE"],
    "PF_CORE_REPO_PATH": ["provability-fabric-core", "PF-Core", "pf-core", "provability-fabric"],
    "PCS_CORE_REPO_PATH": ["pcs-core", "PCS-Core"],
    "PCS_BENCH_REPO_PATH": ["pcs-bench", "PCS-Bench"],
    "VSA_REPO_PATH": ["verified-science-agent", "VSA", "vsa"],
    "MEMORY_REPO_PATH": ["scientific-memory", "Scientific-Memory", "scientific_memory"],
    "LABTRUST_REPO_PATH": ["LabTrust-Gym", "labtrust-gym", "LabTrust"],
}


def _is_repo(path: Path) -> bool:
    return path.is_dir() and ((path / ".git").is_dir() or (path / ".git").is_file())


def discover_sibling(env_var: str) -> Path | None:
    """Return sibling repo path from env or well-known locations."""
    raw = os.environ.get(env_var, "").strip()
    if raw:
        path = Path(raw)
        if path.is_dir():
            return path.resolve()
        return None

    parent = _AKTA_ROOT.parent
    for name in _SIBLING_CANDIDATES.get(env_var, []):
        for base in (parent, _HOME):
            candidate = base / name
            if _is_repo(candidate):
                return candidate.resolve()
    return None


def _git(repo_path: Path, *args: str, timeout: int = 30) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["git", "-C", str(repo_path), *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def git_rev_parse_head(repo_path: str | Path) -> str | None:
    """Return ``git rev-parse HEAD`` for a checkout, or None on failure.

    Existence of a directory / ``.git`` alone is insufficient for pin checks —
    callers must compare this SHA to ``policy/release_pins.yaml``.
    """
    path = Path(repo_path)
    if not path.is_dir():
        return None
    completed = _git(path, "rev-parse", "HEAD")
    if completed is None or completed.returncode != 0:
        return None
    sha = (completed.stdout or "").strip()
    return sha or None


def checkout_matches_pin(repo_path: str | Path, pinned_commit: str) -> bool:
    """True when checkout HEAD equals (or uniquely prefixes) the pinned commit."""
    pinned = str(pinned_commit or "").strip().lower()
    if not pinned or "placeholder" in pinned or "unavailable" in pinned:
        return False
    head = git_rev_parse_head(repo_path)
    if not head:
        return False
    head = head.lower()
    return head == pinned or head.startswith(pinned) or pinned.startswith(head)


def git_working_tree_clean(repo_path: str | Path) -> bool:
    """True when ``git status --porcelain`` is empty (clean working tree)."""
    path = Path(repo_path)
    if not path.is_dir():
        return False
    completed = _git(path, "status", "--porcelain")
    if completed is None or completed.returncode != 0:
        return False
    return not (completed.stdout or "").strip()


def git_tag_resolves_to(repo_path: str | Path, tag: str, pinned_commit: str) -> bool:
    """True when ``tag`` resolves to an object that matches ``pinned_commit``."""
    path = Path(repo_path)
    tag_name = str(tag or "").strip()
    pinned = str(pinned_commit or "").strip().lower()
    if not tag_name or not pinned or "placeholder" in pinned:
        return False
    completed = _git(path, "rev-parse", f"{tag_name}^{{}}")
    if completed is None or completed.returncode != 0:
        # Lightweight tag or missing peel — try bare rev-parse.
        completed = _git(path, "rev-parse", tag_name)
    if completed is None or completed.returncode != 0:
        return False
    resolved = (completed.stdout or "").strip().lower()
    if not resolved:
        return False
    return resolved == pinned or resolved.startswith(pinned) or pinned.startswith(resolved)


def git_submodule_errors(repo_path: str | Path) -> list[str]:
    """Return errors when recorded submodules are missing or SHA-mismatched.

    Repositories without submodules yield an empty list. Uninitialized or
    divergent submodule HEADs produce descriptive errors.
    """
    path = Path(repo_path)
    errors: list[str] = []
    gitmodules = path / ".gitmodules"
    if not gitmodules.is_file():
        return errors

    # Ensure submodule metadata is readable.
    completed = _git(path, "submodule", "status", "--recursive")
    if completed is None or completed.returncode != 0:
        stderr = (completed.stderr if completed else "") or "git submodule status failed"
        errors.append(f"submodule_status_unavailable:{stderr.strip()}")
        return errors

    for line in (completed.stdout or "").splitlines():
        raw = line.rstrip()
        if not raw:
            continue
        # git submodule status prefixes: ' ' ok, '-' not initialized, '+' SHA mismatch, 'U' conflicts
        prefix = raw[0]
        rest = raw[1:].strip()
        parts = rest.split()
        if not parts:
            continue
        sha = parts[0]
        name = parts[1] if len(parts) > 1 else sha
        if prefix == "-":
            errors.append(f"submodule_not_initialized:{name}")
        elif prefix == "+":
            errors.append(f"submodule_sha_mismatch:{name}:{sha}")
        elif prefix == "U":
            errors.append(f"submodule_merge_conflict:{name}")
    return errors


def apply_sibling_env_defaults() -> dict[str, str]:
    """Set unset sibling env vars from discovery; return applied mapping."""
    applied: dict[str, str] = {}
    for env_var in _SIBLING_CANDIDATES:
        if os.environ.get(env_var, "").strip():
            continue
        found = discover_sibling(env_var)
        if found is not None:
            os.environ[env_var] = str(found)
            applied[env_var] = str(found)
    return applied


__all__ = [
    "apply_sibling_env_defaults",
    "checkout_matches_pin",
    "discover_sibling",
    "git_rev_parse_head",
    "git_submodule_errors",
    "git_tag_resolves_to",
    "git_working_tree_clean",
]
