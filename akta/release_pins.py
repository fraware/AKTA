"""Pinned sibling commits for institutional full-stack release (P1-A)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from akta.sibling_repos import discover_sibling

_AKTA_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PINS_PATH = _AKTA_ROOT / "policy" / "release_pins.yaml"

INSTITUTIONAL_REJECTS = frozenset(
    {
        "simulated_scope",
        "legacy_scalar_scope_grant",
        "mock_pf_validator",
        "mock_pcs_validator",
        "missing_pcs_bench",
        "synthetic_vsa_only_validation",
        "missing_scientific_memory_integration",
        "empty_issuer_trust_registry",
        "unpinned_or_placeholder_required_sibling",
    }
)


def load_release_pins(path: str | Path | None = None) -> dict[str, Any]:
    pins_path = Path(path) if path else DEFAULT_PINS_PATH
    data = yaml.safe_load(pins_path.read_text(encoding="utf-8")) or {}
    data["_source"] = str(pins_path.resolve())
    return data


def _is_placeholder_commit(commit: Any) -> bool:
    text = str(commit or "").strip()
    if not text:
        return True
    upper = text.upper()
    return "PLACEHOLDER" in upper or "UNAVAILABLE" in upper or text == "0" * 40


def component_pin_errors(
    pins: dict[str, Any] | None = None,
    *,
    require_checkouts: bool = False,
) -> list[str]:
    """Return fail-closed errors for institutional pin integrity."""
    data = pins or load_release_pins()
    errors: list[str] = []
    components = data.get("components") or {}
    for name, entry in components.items():
        if not isinstance(entry, dict):
            errors.append(f"release pin {name}: invalid entry")
            continue
        required = bool(entry.get("required", True))
        commit = entry.get("commit")
        status = str(entry.get("status") or "")
        if required and (_is_placeholder_commit(commit) or status == "missing_placeholder"):
            errors.append(
                f"unpinned_or_placeholder_required_sibling:{name} "
                "(institutional_release fail-closed)"
            )
            continue
        if require_checkouts and required:
            env_var = str(entry.get("env_var") or "")
            found = discover_sibling(env_var) if env_var else None
            if found is None and not os.environ.get(env_var, "").strip():
                errors.append(f"missing_required_sibling_checkout:{name} ({env_var})")
    return errors


def institutional_release_gate(
    *,
    pins: dict[str, Any] | None = None,
    flags: dict[str, bool] | None = None,
    require_checkouts: bool = True,
) -> dict[str, Any]:
    """Evaluate institutional release rejects; fail closed on any violation.

    ``flags`` keys mirror ``rejects`` in release_pins.yaml (true = violation present).
    """
    data = pins or load_release_pins()
    rejects = set(data.get("rejects") or []) | set(INSTITUTIONAL_REJECTS)
    active_flags = dict(flags or {})
    errors: list[str] = []
    errors.extend(component_pin_errors(data, require_checkouts=require_checkouts))

    for key in sorted(rejects):
        if active_flags.get(key):
            errors.append(f"institutional_release_reject:{key}")

    return {
        "profile": "institutional_release",
        "ok": not errors,
        "errors": errors,
        "pins_source": data.get("_source"),
        "components": {
            name: {
                "commit": (entry or {}).get("commit"),
                "tag": (entry or {}).get("tag"),
                "status": (entry or {}).get("status"),
                "env_var": (entry or {}).get("env_var"),
            }
            for name, entry in (data.get("components") or {}).items()
            if isinstance(entry, dict)
        },
        "beta": True,
        "disclaimer": (
            "Pinned full-stack validation is beta reference engineering; "
            "not a production certification for SCOPE-authorized action."
        ),
    }


def pins_for_release_report(pins: dict[str, Any] | None = None) -> dict[str, Any]:
    """Compact SHA table for release reports."""
    data = pins or load_release_pins()
    return {
        name: {
            "commit": entry.get("commit"),
            "tag": entry.get("tag"),
            "status": entry.get("status"),
        }
        for name, entry in (data.get("components") or {}).items()
        if isinstance(entry, dict)
    }


__all__ = [
    "INSTITUTIONAL_REJECTS",
    "component_pin_errors",
    "institutional_release_gate",
    "load_release_pins",
    "pins_for_release_report",
]
