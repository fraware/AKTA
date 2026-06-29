"""Discover sibling repository paths for live trust-stack validation (v1.0)."""

from __future__ import annotations

import os
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
    return path.is_dir() and (path / ".git").is_dir()


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
