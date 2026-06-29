"""Cross-repo validation helpers for optional sibling repository CI (v0.6)."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable


def repo_path(env_var: str) -> Path | None:
    raw = os.environ.get(env_var, "").strip()
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_dir() else None


def pf_core_repo() -> Path | None:
    return repo_path("PF_CORE_REPO_PATH")


def pcs_core_repo() -> Path | None:
    return repo_path("PCS_CORE_REPO_PATH")


def scope_repo() -> Path | None:
    return repo_path("SCOPE_REPO_PATH")


def pcs_bench_repo() -> Path | None:
    return repo_path("PCS_BENCH_REPO_PATH")


def vsa_repo() -> Path | None:
    return repo_path("VSA_REPO_PATH")


def memory_repo() -> Path | None:
    return repo_path("MEMORY_REPO_PATH")


def labtrust_repo() -> Path | None:
    return repo_path("LABTRUST_REPO_PATH")


def try_import_validator(
    repo: Path,
    module_candidates: list[str],
    attr: str = "validate",
) -> Callable[[dict[str, Any]], None] | None:
    """Import a validator callable from a sibling repo if present."""
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))
    for mod_name in module_candidates:
        try:
            spec = importlib.util.find_spec(mod_name)
            if spec is None:
                continue
            mod = importlib.import_module(mod_name)
            fn = getattr(mod, attr, None)
            if callable(fn):
                return fn
        except (ImportError, AttributeError, ValueError):
            continue
    return None


def validate_pf_obligation_live(obligation: dict[str, Any]) -> str | None:
    """Validate PF obligation against sibling PF-Core if available. Returns skip reason or None."""
    repo = pf_core_repo()
    if repo is None:
        return "PF_CORE_REPO_PATH not set"

    validator = try_import_validator(
        repo,
        ["pf_core.validate", "pf.validate", "validate_obligation"],
        attr="validate_obligation",
    )
    if validator is None:
        validator = try_import_validator(repo, ["pf_core.schema", "pf.schema"], attr="validate")
    if validator is None:
        cli = repo / "scripts" / "validate_obligation.py"
        if cli.exists():
            import tempfile

            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tmp:
                json.dump(obligation, tmp)
                tmp_path = tmp.name
            try:
                proc = subprocess.run(
                    [sys.executable, str(cli), tmp_path],
                    capture_output=True,
                    text=True,
                    cwd=str(repo),
                    timeout=30,
                    check=False,
                )
                if proc.returncode != 0:
                    raise ValueError(proc.stderr or proc.stdout or "PF-Core CLI validation failed")
            finally:
                Path(tmp_path).unlink(missing_ok=True)
        return "PF-Core validator not found; skipped live validation"
    validator(obligation)
    return None


def validate_vsa_report_live(report: dict[str, Any]) -> str | None:
    """Validate VSA report against sibling VSA if available."""
    repo = vsa_repo()
    if repo is None:
        return "VSA_REPO_PATH not set"

    src = repo / "src"
    if src.is_dir() and str(src) not in sys.path:
        sys.path.insert(0, str(src))
    validator = try_import_validator(
        repo,
        ["vsa.validate.engine", "vsa.engine"],
        attr="validate_report",
    )
    if validator is None:
        return "VSA validate_report not found; skipped live validation"
    validator(report)
    return None


def validate_pcs_bundle_live(bundle_dir: Path) -> str | None:
    """Validate PCS bundle against sibling PCS-Core if available."""
    repo = pcs_core_repo()
    if repo is None:
        return "PCS_CORE_REPO_PATH not set"

    validator = try_import_validator(
        repo,
        ["pcs_core.validate", "pcs.validate", "validate_bundle"],
        attr="validate_akta_bundle",
    )
    if validator is None:
        validator = try_import_validator(repo, ["pcs_core.bundle", "pcs.bundle"], attr="validate")
    if validator is None:
        cli = repo / "scripts" / "validate_akta_bundle.py"
        if cli.exists():
            proc = subprocess.run(
                [sys.executable, str(cli), str(bundle_dir)],
                capture_output=True,
                text=True,
                cwd=str(repo),
                timeout=60,
                check=False,
            )
            if proc.returncode != 0:
                raise ValueError(proc.stderr or proc.stdout or "PCS-Core CLI validation failed")
        return "PCS-Core validator not found; skipped live validation"
    validator(bundle_dir)
    return None
