"""Pinned sibling commits for institutional full-stack release (P1-A / WS12)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import yaml

from akta.sibling_repos import (
    checkout_matches_pin,
    discover_sibling,
    git_rev_parse_head,
    git_submodule_errors,
    git_tag_resolves_to,
    git_working_tree_clean,
)
from akta.shared_contracts import (
    _is_placeholder_pin_value,
    pin_is_complete_for_release,
)

_AKTA_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PINS_PATH = _AKTA_ROOT / "policy" / "release_pins.yaml"
DEFAULT_SHARED_PIN = _AKTA_ROOT / "policy" / "shared_contracts_pin.json"
DEFAULT_COMPAT_MANIFEST = _AKTA_ROOT / "policy" / "scope_compatibility_manifest.json"

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
        "sibling_checkout_sha_mismatch",
        "sibling_working_tree_dirty",
        "sibling_tag_mismatch",
        "sibling_submodule_mismatch",
        "shared_contracts_release_hash_mismatch",
        "shared_contracts_pin_incomplete",
        "compat_manifest_pin_mismatch",
    }
)

_SHARED_PIN_COMPARE_FIELDS = (
    "package_version",
    "wheel_sha256",
    "source_archive_sha256",
    "release_manifest_sha256",
    "release_signer",
    "release_artifact_hash",
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


def _shared_contracts_pin_errors(pins: dict[str, Any]) -> list[str]:
    """Verify release_pins shared_contracts fields match policy pin file."""
    errors: list[str] = []
    declared = pins.get("shared_contracts") or {}
    if not isinstance(declared, dict) or not declared:
        return errors
    pin_file = Path(declared.get("pin_file") or DEFAULT_SHARED_PIN)
    if not pin_file.is_absolute():
        pin_file = _AKTA_ROOT / pin_file
    if not pin_file.is_file():
        errors.append(
            "shared_contracts_release_hash_mismatch: missing pin file "
            f"{pin_file}"
        )
        return errors
    try:
        pin_data = json.loads(pin_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"shared_contracts_release_hash_mismatch: unreadable pin ({exc})")
        return errors

    for field in _SHARED_PIN_COMPARE_FIELDS:
        expected = str(declared.get(field) or "").strip()
        actual = str(pin_data.get(field) or "").strip()
        if expected and actual and expected != actual:
            errors.append(
                "shared_contracts_release_hash_mismatch: "
                f"{field} release_pins={expected!r} shared_contracts_pin={actual!r}"
            )

    # Institutional profile fail-closes on incomplete wheel/manifest/signer pins.
    incomplete = pin_is_complete_for_release(pin_data)
    for item in incomplete:
        if item not in errors:
            errors.append(item)
    # Also treat release_pins-declared placeholders as incomplete.
    for field in (
        "wheel_sha256",
        "source_archive_sha256",
        "release_manifest_sha256",
        "release_signer",
    ):
        if _is_placeholder_pin_value(declared.get(field)):
            marker = f"shared_contracts_pin_incomplete:{field}"
            if marker not in errors:
                errors.append(marker)
    return errors


def _compat_manifest_pin_errors(pins: dict[str, Any]) -> list[str]:
    """Ensure scope compatibility manifest agrees with release pins."""
    errors: list[str] = []
    manifest_path = DEFAULT_COMPAT_MANIFEST
    if not manifest_path.is_file():
        errors.append("compat_manifest_pin_mismatch: missing scope_compatibility_manifest.json")
        return errors
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"compat_manifest_pin_mismatch: unreadable ({exc})")
        return errors

    shared = pins.get("shared_contracts") or {}
    pin_ver = str(shared.get("package_version") or "").strip()
    man_ver = str(manifest.get("shared_contracts_package_version") or "").strip()
    if pin_ver and man_ver and pin_ver != man_ver:
        errors.append(
            "compat_manifest_pin_mismatch: shared_contracts_package_version "
            f"pins={pin_ver!r} manifest={man_ver!r}"
        )

    target = pins.get("target_ecosystem") or {}
    akta_target = str(target.get("akta") or "").strip()
    man_akta = str(manifest.get("akta_package_version") or "").strip()
    if akta_target and man_akta and akta_target != man_akta:
        errors.append(
            "compat_manifest_pin_mismatch: akta_package_version "
            f"pins={akta_target!r} manifest={man_akta!r}"
        )

    # When pins declare a wheel hash, compat manifest must echo it when present.
    wheel = str(shared.get("wheel_sha256") or "").strip()
    man_wheel = str(manifest.get("shared_contracts_wheel_sha256") or "").strip()
    if wheel and man_wheel and wheel != man_wheel:
        errors.append(
            "compat_manifest_pin_mismatch: shared_contracts_wheel_sha256 "
            f"pins={wheel!r} manifest={man_wheel!r}"
        )
    return errors


def component_pin_errors(
    pins: dict[str, Any] | None = None,
    *,
    require_checkouts: bool = False,
    require_sha_match: bool | None = None,
    require_clean_tree: bool | None = None,
    require_tag_match: bool | None = None,
    require_submodules: bool | None = None,
) -> list[str]:
    """Return fail-closed errors for institutional pin integrity.

    When checkouts are required (or ``require_sha_match``), compare
    ``git rev-parse HEAD`` to the pinned commit — directory existence alone
    is insufficient (WS12). Clean tree, tag resolution, and submodule
    consistency are mandatory whenever checkouts are required unless
    explicitly disabled.
    """
    data = pins or load_release_pins()
    errors: list[str] = []
    errors.extend(_shared_contracts_pin_errors(data))
    errors.extend(_compat_manifest_pin_errors(data))
    if require_sha_match is None:
        require_sha_match = require_checkouts
    if require_clean_tree is None:
        require_clean_tree = require_checkouts
    if require_tag_match is None:
        require_tag_match = require_checkouts
    if require_submodules is None:
        require_submodules = require_checkouts

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
        env_var = str(entry.get("env_var") or "")
        found = discover_sibling(env_var) if env_var else None
        if require_checkouts and required:
            if found is None and not os.environ.get(env_var, "").strip():
                errors.append(f"missing_required_sibling_checkout:{name} ({env_var})")
                continue
        if found is None or _is_placeholder_commit(commit):
            continue
        if require_sha_match and required:
            head = git_rev_parse_head(found)
            if head is None:
                errors.append(
                    f"sibling_checkout_sha_mismatch:{name} "
                    f"(unable to read git HEAD at {found})"
                )
            elif not checkout_matches_pin(found, str(commit)):
                errors.append(
                    f"sibling_checkout_sha_mismatch:{name} "
                    f"pinned={commit} head={head}"
                )
        if require_clean_tree and required and not git_working_tree_clean(found):
            errors.append(f"sibling_working_tree_dirty:{name}")
        tag = entry.get("tag")
        if require_tag_match and required and tag not in (None, "", "null"):
            if not git_tag_resolves_to(found, str(tag), str(commit)):
                errors.append(
                    f"sibling_tag_mismatch:{name} tag={tag} pinned={commit}"
                )
        if require_submodules and required:
            for sub_err in git_submodule_errors(found):
                errors.append(f"sibling_submodule_mismatch:{name}:{sub_err}")
    return errors


def institutional_release_gate(
    *,
    pins: dict[str, Any] | None = None,
    flags: dict[str, bool] | None = None,
    require_checkouts: bool = True,
    require_sha_match: bool | None = None,
    require_clean_tree: bool | None = None,
    require_tag_match: bool | None = None,
    require_submodules: bool | None = None,
) -> dict[str, Any]:
    """Evaluate institutional release rejects; fail closed on any violation.

    ``flags`` keys mirror ``rejects`` in release_pins.yaml (true = violation present).
    """
    data = pins or load_release_pins()
    rejects = set(data.get("rejects") or []) | set(INSTITUTIONAL_REJECTS)
    active_flags = dict(flags or {})
    errors: list[str] = []
    errors.extend(
        component_pin_errors(
            data,
            require_checkouts=require_checkouts,
            require_sha_match=require_sha_match,
            require_clean_tree=require_clean_tree,
            require_tag_match=require_tag_match,
            require_submodules=require_submodules,
        )
    )

    for key in sorted(rejects):
        if active_flags.get(key):
            errors.append(f"institutional_release_reject:{key}")

    return {
        "profile": "institutional_release",
        "ok": not errors,
        "errors": errors,
        "pins_source": data.get("_source"),
        "shared_contracts": data.get("shared_contracts"),
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
    report = {
        name: {
            "commit": entry.get("commit"),
            "tag": entry.get("tag"),
            "status": entry.get("status"),
        }
        for name, entry in (data.get("components") or {}).items()
        if isinstance(entry, dict)
    }
    shared = data.get("shared_contracts")
    if isinstance(shared, dict):
        report["shared_contracts"] = {
            "package_version": shared.get("package_version"),
            "wheel_sha256": shared.get("wheel_sha256"),
            "source_archive_sha256": shared.get("source_archive_sha256"),
            "release_manifest_sha256": shared.get("release_manifest_sha256"),
            "release_signer": shared.get("release_signer"),
            "release_artifact_hash": shared.get("release_artifact_hash"),
        }
    return report


__all__ = [
    "INSTITUTIONAL_REJECTS",
    "component_pin_errors",
    "institutional_release_gate",
    "load_release_pins",
    "pins_for_release_report",
]
