"""Stack profile load/validate against institutional release pins (AS-02)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from akta import __version__
from akta.errors import AKTAError
from akta.records import validate_against_schema
from akta.release_pins import (
    component_pin_errors,
    institutional_release_gate,
    load_release_pins,
)

_AKTA_ROOT = Path(__file__).resolve().parent.parent
STACK_PROFILE_VERSION = "akta-stack-profile-v1"


class StackProfileError(AKTAError):
    """Unsupported or mismatched stack profile."""


def load_stack_profile(path: str | Path | dict[str, Any]) -> dict[str, Any]:
    if isinstance(path, dict):
        data = dict(path)
    else:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_against_schema(data, "stack_profile.schema.json")
    return data


def _version_compatible(declared: str, expected: str) -> bool:
    d = str(declared or "").strip()
    e = str(expected or "").strip()
    if not d or not e:
        return False
    if d == e:
        return True
    # Allow minor prefix match when pins use short forms (e.g. "2.2" vs "2.2.0").
    return e.startswith(d) or d.startswith(e)


def validate_stack_profile(
    profile: dict[str, Any] | str | Path,
    *,
    pins: dict[str, Any] | None = None,
    require_checkouts: bool = False,
    package_version: str | None = None,
) -> dict[str, Any]:
    """Validate stack profile against release pins / package version.

    Returns a result dict with ``ok`` and ``errors``. Fail-closed: any
    unsupported combination or institutional pin incompleteness (when required)
    yields ``ok=False``.
    """
    data = load_stack_profile(profile)
    pin_data = pins or load_release_pins()
    errors: list[str] = []

    if data.get("stack_profile_version") != STACK_PROFILE_VERSION:
        errors.append(
            f"unsupported_stack_profile_version:{data.get('stack_profile_version')}"
        )

    akta_ver = package_version or __version__
    declared_akta = str(data.get("akta_version") or "")
    if not _version_compatible(declared_akta, akta_ver):
        errors.append(
            f"pin_mismatch:akta_version profile={declared_akta!r} package={akta_ver!r}"
        )

    target = pin_data.get("target_ecosystem") or {}
    components = data.get("components") or {}
    pin_components = pin_data.get("components") or {}

    # AKTA component must be present and match.
    akta_comp = components.get("AKTA") or {}
    if not isinstance(akta_comp, dict) or not akta_comp.get("version"):
        errors.append("missing_component:AKTA")
    elif not _version_compatible(str(akta_comp.get("version")), akta_ver):
        errors.append(
            f"pin_mismatch:AKTA profile={akta_comp.get('version')!r} package={akta_ver!r}"
        )

    shared_declared = data.get("shared_contracts_version")
    shared_pin = (pin_data.get("shared_contracts") or {}).get("package_version")
    if shared_declared and shared_pin and not _version_compatible(
        str(shared_declared), str(shared_pin)
    ):
        errors.append(
            f"pin_mismatch:shared_contracts profile={shared_declared!r} pins={shared_pin!r}"
        )

    required_names = {"VSA", "SCOPE", "PF-Core", "PCS-Core", "Scientific-Memory"}
    if data.get("profile_kind") == "institutional" or data.get("require_institutional_pins"):
        for name in sorted(required_names):
            if name not in components:
                errors.append(f"missing_component:{name}")
                continue
            entry = components[name]
            pin_entry = pin_components.get(name) or {}
            if not isinstance(entry, dict):
                errors.append(f"invalid_component:{name}")
                continue
            # Version / tag / commit must not contradict institutional pins when present.
            pin_tag = pin_entry.get("tag")
            decl_tag = entry.get("tag")
            if pin_tag and decl_tag and str(pin_tag) != str(decl_tag):
                errors.append(
                    f"pin_mismatch:{name}.tag profile={decl_tag!r} pins={pin_tag!r}"
                )
            pin_commit = pin_entry.get("commit")
            decl_commit = entry.get("commit")
            if pin_commit and decl_commit and str(pin_commit) != str(decl_commit):
                errors.append(
                    f"pin_mismatch:{name}.commit profile={decl_commit!r} pins={pin_commit!r}"
                )
            pin_ver = None
            if name == "SCOPE":
                pin_ver = target.get("scope")
            if pin_ver and entry.get("version") and not _version_compatible(
                str(entry.get("version")), str(pin_ver)
            ):
                errors.append(
                    f"pin_mismatch:{name}.version profile={entry.get('version')!r} "
                    f"pins={pin_ver!r}"
                )

        # Reuse institutional verification engine (placeholder signer remains fail-closed).
        gate = institutional_release_gate(
            pins=pin_data,
            require_checkouts=require_checkouts,
        )
        # Always surface pin-file / placeholder errors even without sibling checkouts.
        pin_errs = component_pin_errors(pin_data, require_checkouts=False)
        for err in pin_errs:
            if err not in errors:
                errors.append(err)
        for err in gate.get("errors") or []:
            # Skip missing checkout noise unless explicitly required.
            if not require_checkouts and err.startswith("missing_required_sibling_checkout"):
                continue
            if not require_checkouts and err.startswith("sibling_"):
                continue
            if err not in errors:
                errors.append(err)

    # Reject unknown / empty component versions.
    for name, entry in components.items():
        if not isinstance(entry, dict) or not str(entry.get("version") or "").strip():
            errors.append(f"unsupported_component_pin:{name}")

    ok = not errors
    return {
        "ok": ok,
        "errors": errors,
        "profile_id": data.get("profile_id"),
        "akta_version": declared_akta,
        "package_version": akta_ver,
        "beta": True,
    }


def validate_stack_profile_or_raise(
    profile: dict[str, Any] | str | Path,
    **kwargs: Any,
) -> dict[str, Any]:
    result = validate_stack_profile(profile, **kwargs)
    if not result["ok"]:
        raise StackProfileError("; ".join(result["errors"]))
    return result


__all__ = [
    "STACK_PROFILE_VERSION",
    "StackProfileError",
    "load_stack_profile",
    "validate_stack_profile",
    "validate_stack_profile_or_raise",
]
