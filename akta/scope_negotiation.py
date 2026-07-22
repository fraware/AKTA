"""SCOPE × AKTA contract negotiation (directive §6).

Handshake resolves package/policy/review/grant/capability-envelope/summary
versions via the JSON compatibility manifest or installed package metadata.
Does NOT execute arbitrary sibling Python source.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from importlib.metadata import PackageNotFoundError, metadata, version
from pathlib import Path
from typing import Any

_AKTA_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_MANIFEST = _AKTA_ROOT / "policy" / "scope_compatibility_manifest.json"

STATUS_COMPLETED = "completed"
STATUS_SESSION_REQUIRED = "session_required"
VALID_SUMMARY_STATUSES = frozenset({STATUS_COMPLETED, STATUS_SESSION_REQUIRED})


@dataclass
class ScopeNegotiationResult:
    """Outcome of a SCOPE contract handshake."""

    ok: bool
    status: str
    strict: bool
    versions: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # Populated when status == session_required
    review_pending: bool = False
    session_id: str | None = None
    required_roles: list[str] = field(default_factory=list)
    next_integration_action: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ok": self.ok,
            "status": self.status,
            "strict": self.strict,
            "versions": dict(self.versions),
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }
        if self.status == STATUS_SESSION_REQUIRED:
            payload.update({
                "review_pending": True,
                "session_id": self.session_id,
                "required_roles": list(self.required_roles),
                "next_integration_action": self.next_integration_action,
            })
        return payload


def load_compatibility_manifest(path: str | Path | None = None) -> dict[str, Any]:
    manifest_path = Path(path) if path else _DEFAULT_MANIFEST
    if not manifest_path.is_file():
        raise FileNotFoundError(f"SCOPE compatibility manifest not found: {manifest_path}")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("compatibility manifest must be a JSON object")
    return data


def _package_version(dist_name: str) -> str | None:
    try:
        return version(dist_name)
    except PackageNotFoundError:
        return None


def _package_metadata_field(dist_name: str, key: str) -> str | None:
    try:
        meta = metadata(dist_name)
    except PackageNotFoundError:
        return None
    value = meta.get(key)  # type: ignore[attr-defined]
    if value:
        return str(value)
    # setuptools / custom keys often live in JSON under Provides-Extra style fields
    for field_name in meta:
        if field_name.lower() == key.lower():
            return str(meta[field_name])
    return None


def resolve_scope_versions_from_environment(
    *,
    manifest: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Resolve SCOPE/AKTA contract versions without executing sibling source.

    Resolution order for SCOPE package:
    1. Installed ``scope-protocol`` / ``scope`` distribution metadata
    2. Environment overrides (SCOPE_PACKAGE_VERSION, SCOPE_POLICY_VERSION, ...)
    3. Compatibility manifest defaults (AKTA side pins)
    """
    manifest = manifest or load_compatibility_manifest()
    resolved: dict[str, str] = {
        "akta_package_version": str(manifest.get("akta_package_version", "1.0.0")),
        "akta_review_contract_version": str(manifest["akta_review_contract_version"]),
        "grant_schema_version": str(manifest["grant_schema_version"]),
        "capability_envelope_version": str(manifest["capability_envelope_version"]),
        "summary_contract_version": str(manifest["summary_contract_version"]),
        "fixture_contract_version": str(manifest["fixture_contract_version"]),
    }

    scope_pkg = (
        os.environ.get("SCOPE_PACKAGE_VERSION")
        or _package_version("scope-protocol")
        or _package_version("scope")
    )
    if scope_pkg:
        resolved["scope_package_version"] = scope_pkg

    scope_policy = (
        os.environ.get("SCOPE_POLICY_VERSION")
        or _package_metadata_field("scope-protocol", "Scope-Policy-Version")
        or _package_metadata_field("scope", "Scope-Policy-Version")
    )
    if scope_policy:
        resolved["scope_policy_version"] = scope_policy

    scope_core = os.environ.get("SCOPE_CORE_VERSION")
    if scope_core:
        resolved["scope_core_version"] = scope_core

    return resolved


def is_strict_scope_contract() -> bool:
    return os.environ.get("AKTA_STRICT_SCOPE_CONTRACT", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def negotiate_scope_contract(
    *,
    peer_versions: dict[str, str] | None = None,
    summary: dict[str, Any] | None = None,
    strict: bool | None = None,
    manifest_path: str | Path | None = None,
    required_roles: list[str] | None = None,
) -> ScopeNegotiationResult:
    """Perform SCOPE contract handshake.

    ``summary.status`` may be ``completed`` or ``session_required``.
    On ``session_required``, returns review_pending payload and does not require
    decision/grant artifact paths.
    """
    if strict is None:
        strict = is_strict_scope_contract()
    manifest = load_compatibility_manifest(manifest_path)
    local = resolve_scope_versions_from_environment(manifest=manifest)
    peer = dict(peer_versions or {})
    errors: list[str] = []
    warnings: list[str] = []

    exact = manifest.get("strict_exact_versions") or {}
    for key, expected in exact.items():
        actual = peer.get(key) or local.get(key)
        if actual is None:
            msg = f"missing contract version for {key}"
            (errors if strict else warnings).append(msg)
            continue
        if strict and str(actual) != str(expected):
            errors.append(f"strict mismatch {key}: got {actual!r}, expected {expected!r}")
        local[key] = str(actual)

    # Package compatibility (non-strict: warn; strict: error if peer declares incompatible)
    peer_pkg = peer.get("scope_package_version") or local.get("scope_package_version")
    allowed_pkgs = (manifest.get("compatible_scope_packages") or {}).get("scope-protocol") or []
    if peer_pkg and allowed_pkgs and peer_pkg not in allowed_pkgs:
        msg = f"scope package {peer_pkg!r} not in compatible set {allowed_pkgs}"
        (errors if strict else warnings).append(msg)

    peer_policy = peer.get("scope_policy_version") or local.get("scope_policy_version")
    allowed_policies = manifest.get("compatible_scope_policy_versions") or []
    if peer_policy and allowed_policies and peer_policy not in allowed_policies:
        msg = f"scope policy {peer_policy!r} not in compatible set {allowed_policies}"
        (errors if strict else warnings).append(msg)

    status = STATUS_COMPLETED
    if summary is not None:
        raw_status = summary.get("status", STATUS_COMPLETED)
        if raw_status not in VALID_SUMMARY_STATUSES:
            errors.append(
                f"summary.status must be one of {sorted(VALID_SUMMARY_STATUSES)}, "
                f"got {raw_status!r}"
            )
        else:
            status = str(raw_status)
        # Strict: reject free-form identity/signing levels outside enums (schema);
        # also reject arbitrary adapter_contract_version strings.
        if strict:
            expected_summary = exact.get("summary_contract_version") or manifest.get(
                "summary_contract_version"
            )
            adapter_ver = summary.get("adapter_contract_version") or summary.get(
                "summary_contract_version"
            )
            if expected_summary and adapter_ver and str(adapter_ver) != str(expected_summary):
                # Allow legacy alias mapping for review contract pin
                review_pin = exact.get("akta_review_contract_version")
                if str(adapter_ver) not in {str(expected_summary), str(review_pin)}:
                    errors.append(
                        f"strict summary contract version mismatch: {adapter_ver!r}"
                    )

    if status == STATUS_SESSION_REQUIRED:
        session_id = (
            (summary or {}).get("session_id")
            or (summary or {}).get("queue_id")
            or f"SCOPE-SESSION-{uuid.uuid4().hex[:12].upper()}"
        )
        roles = list(
            required_roles
            or (summary or {}).get("required_roles")
            or [(summary or {}).get("required_review_role") or "domain_scientist"]
        )
        return ScopeNegotiationResult(
            ok=not errors,
            status=STATUS_SESSION_REQUIRED,
            strict=bool(strict),
            versions={**local, **peer},
            errors=errors,
            warnings=warnings,
            review_pending=True,
            session_id=str(session_id),
            required_roles=[str(r) for r in roles if r],
            next_integration_action=(
                (summary or {}).get("next_integration_action")
                or "await_human_review_session"
            ),
        )

    return ScopeNegotiationResult(
        ok=not errors,
        status=STATUS_COMPLETED,
        strict=bool(strict),
        versions={**local, **peer},
        errors=errors,
        warnings=warnings,
    )


def consume_scope_summary(
    summary: dict[str, Any],
    *,
    strict: bool | None = None,
    peer_versions: dict[str, str] | None = None,
) -> ScopeNegotiationResult:
    """Consume a SCOPE review summary after handshake.

    For ``session_required``, does NOT attempt to load decision/grant paths.
    For ``completed``, validates that artifact references are present (paths or ids).
    """
    result = negotiate_scope_contract(
        summary=summary,
        peer_versions=peer_versions,
        strict=strict,
    )
    if not result.ok:
        return result

    if result.status == STATUS_SESSION_REQUIRED:
        # Explicitly do not touch decision_path / grant_path.
        return result

    # completed: require either paths or ids for decision and grant
    has_decision = bool(summary.get("decision_id") or summary.get("decision_path"))
    has_grant = bool(summary.get("grant_id") or summary.get("grant_path"))
    if not has_decision:
        result.errors.append("completed summary missing decision_id/decision_path")
    if not has_grant:
        result.errors.append("completed summary missing grant_id/grant_path")
    if not summary.get("approved_scope"):
        result.errors.append("completed summary missing approved_scope")
    result.ok = not result.errors
    return result
