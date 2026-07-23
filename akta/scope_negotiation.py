"""SCOPE × AKTA contract negotiation (P0-H).

Strict mode requires the peer to declare actual versions — AKTA must NOT
substitute local expected versions for missing peer declarations.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from importlib.metadata import PackageNotFoundError, metadata, version
from pathlib import Path
from typing import Any

from akta.shared_contracts import (
    ENVELOPE_VERSION,
    authorization_envelope_schema_hash,
    grant_schema_version,
)

_AKTA_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_MANIFEST = _AKTA_ROOT / "policy" / "scope_compatibility_manifest.json"

STATUS_COMPLETED = "completed"
STATUS_SESSION_REQUIRED = "session_required"
VALID_SUMMARY_STATUSES = frozenset({STATUS_COMPLETED, STATUS_SESSION_REQUIRED})

REQUIRED_PEER_KEYS = (
    "scope_package_version",
    "scope_core_version",
    "akta_review_contract_version",
    "grant_schema_version",
    "envelope_schema_version",
    "summary_schema_version",
    "policy_manifest_version",
)


@dataclass
class ScopeNegotiationResult:
    """Outcome of a SCOPE contract handshake."""

    ok: bool
    status: str
    strict: bool
    versions: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    review_pending: bool = False
    session_id: str | None = None
    required_roles: list[str] = field(default_factory=list)
    next_integration_action: str | None = None
    packet_id: str | None = None
    summary_schema_version: str | None = None
    scope_contract_version: str | None = None

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
                "packet_id": self.packet_id,
                "summary_schema_version": self.summary_schema_version,
                "scope_contract_version": self.scope_contract_version,
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
    for field_name in meta:
        if field_name.lower() == key.lower():
            return str(meta[field_name])
    return None


def resolve_scope_versions_from_environment(
    *,
    manifest: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Resolve local AKTA-side pins. Never used as a substitute for missing peer info."""
    manifest = manifest or load_compatibility_manifest()
    resolved: dict[str, str] = {
        "akta_package_version": str(manifest.get("akta_package_version", "1.0.0")),
        "akta_review_contract_version": str(manifest["akta_review_contract_version"]),
        "grant_schema_version": str(manifest.get("grant_schema_version") or grant_schema_version()),
        "capability_envelope_version": str(
            manifest.get("capability_envelope_version") or ENVELOPE_VERSION
        ),
        "envelope_schema_version": str(
            manifest.get("authorization_schema_version")
            or manifest.get("capability_envelope_version")
            or ENVELOPE_VERSION
        ),
        "envelope_schema_hash": authorization_envelope_schema_hash(),
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
        resolved["policy_manifest_version"] = scope_policy

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
    """Perform SCOPE contract handshake with peer-authenticated versions (P0-H)."""
    if strict is None:
        strict = is_strict_scope_contract()
    manifest = load_compatibility_manifest(manifest_path)
    local = resolve_scope_versions_from_environment(manifest=manifest)
    peer = dict(peer_versions or {})
    errors: list[str] = []
    warnings: list[str] = []

    required_keys = tuple(
        manifest.get("required_peer_version_keys") or REQUIRED_PEER_KEYS
    )
    if strict:
        for key in required_keys:
            # Alias: summary_schema_version ↔ summary_contract_version
            actual = peer.get(key)
            if actual is None and key == "summary_schema_version":
                actual = peer.get("summary_contract_version")
            if actual is None and key == "envelope_schema_version":
                actual = peer.get("capability_envelope_version") or peer.get(
                    "authorization_schema_version"
                )
            if actual is None:
                errors.append(
                    f"peer missing required version declaration for {key} "
                    "(strict negotiation forbids substituting AKTA local pins)"
                )

    exact = manifest.get("strict_exact_versions") or {}
    legacy_ids = {
        str(x)
        for x in (
            manifest.get("legacy_ids_rejected_in_strict")
            or [
                "akta-capability-envelope-v1.0",
                "akta-scope-grant-v1.0",
                "akta-scope-contract-v1.0",
            ]
        )
    }
    for key, expected in exact.items():
        # Strict: compare only peer-declared values, never local fallback.
        actual = peer.get(key)
        if actual is None and key == "summary_schema_version":
            actual = peer.get("summary_contract_version")
        if actual is None and key == "envelope_schema_version":
            actual = peer.get("capability_envelope_version") or peer.get(
                "authorization_schema_version"
            )
        if actual is None and key == "grant_status_schema_version":
            actual = peer.get("grant_status_schema_version")
        if actual is None:
            if not strict:
                # Non-strict may consult local for warnings only.
                actual = local.get(key)
                if actual is None:
                    warnings.append(f"missing contract version for {key}")
                continue
            continue  # already recorded as missing peer key
        if strict and str(actual) in legacy_ids:
            errors.append(
                f"strict rejects legacy contract id for {key}: {actual!r} "
                "(delete former envelope/grant IDs from peer negotiation)"
            )
            continue
        if strict and str(actual) != str(expected):
            errors.append(f"strict mismatch {key}: got {actual!r}, expected {expected!r}")

    # Reject legacy IDs anywhere in peer declarations under strict mode.
    if strict:
        for key, value in peer.items():
            if str(value) in legacy_ids:
                errors.append(
                    f"strict rejects legacy peer value {key}={value!r}"
                )

    peer_pkg = peer.get("scope_package_version")
    allowed_pkgs = (manifest.get("compatible_scope_packages") or {}).get("scope-protocol") or []
    if peer_pkg and allowed_pkgs and peer_pkg not in allowed_pkgs:
        msg = f"scope package {peer_pkg!r} not in compatible set {allowed_pkgs}"
        (errors if strict else warnings).append(msg)

    peer_core = peer.get("scope_core_version")
    allowed_cores = (manifest.get("compatible_scope_packages") or {}).get("scope-core") or []
    if peer_core and allowed_cores and peer_core not in allowed_cores:
        msg = f"scope core {peer_core!r} not in compatible set {allowed_cores}"
        (errors if strict else warnings).append(msg)

    peer_policy = peer.get("scope_policy_version") or peer.get("policy_manifest_version")
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
        if strict:
            expected_summary = exact.get("summary_contract_version") or manifest.get(
                "summary_contract_version"
            )
            adapter_ver = (
                summary.get("adapter_contract_version")
                or summary.get("summary_contract_version")
                or summary.get("summary_schema_version")
            )
            if expected_summary and adapter_ver and str(adapter_ver) != str(expected_summary):
                review_pin = exact.get("akta_review_contract_version")
                if str(adapter_ver) not in {str(expected_summary), str(review_pin)}:
                    errors.append(
                        f"strict summary contract version mismatch: {adapter_ver!r}"
                    )

    merged_versions = {**local, **{k: str(v) for k, v in peer.items()}}

    if status == STATUS_SESSION_REQUIRED:
        summary = summary or {}
        session_id = summary.get("session_id") or summary.get("queue_id")
        if not session_id:
            errors.append(
                "session_required summary missing session_id "
                "(do not invent session identity)"
            )
        packet_id = summary.get("packet_id")
        if not packet_id:
            (errors if strict else warnings).append(
                "session_required summary missing packet_id"
            )
        summary_schema = (
            summary.get("summary_schema_version")
            or summary.get("summary_contract_version")
            or summary.get("adapter_contract_version")
        )
        if not summary_schema:
            (errors if strict else warnings).append(
                "session_required summary missing summary_schema_version"
            )
        scope_contract = (
            summary.get("scope_contract_version")
            or peer.get("akta_review_contract_version")
            or peer.get("scope_core_version")
            or summary.get("adapter_contract_version")
        )
        if not scope_contract:
            (errors if strict else warnings).append(
                "session_required summary missing SCOPE contract version"
            )
        roles = list(
            required_roles
            or summary.get("required_roles")
            or ([summary.get("required_review_role")] if summary.get("required_review_role") else [])
        )
        if not roles:
            (errors if strict else warnings).append(
                "session_required summary missing required_roles"
            )
        return ScopeNegotiationResult(
            ok=not errors,
            status=STATUS_SESSION_REQUIRED,
            strict=bool(strict),
            versions=merged_versions,
            errors=errors,
            warnings=warnings,
            review_pending=True,
            session_id=str(session_id) if session_id else None,
            required_roles=[str(r) for r in roles if r],
            next_integration_action=(
                summary.get("next_integration_action") or "await_human_review_session"
            ),
            packet_id=str(packet_id) if packet_id else None,
            summary_schema_version=str(summary_schema) if summary_schema else None,
            scope_contract_version=str(scope_contract) if scope_contract else None,
        )

    return ScopeNegotiationResult(
        ok=not errors,
        status=STATUS_COMPLETED,
        strict=bool(strict),
        versions=merged_versions,
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

    Completed summaries must reference authenticated artifact IDs and hashes,
    not merely filesystem paths (P0-H).
    """
    result = negotiate_scope_contract(
        summary=summary,
        peer_versions=peer_versions,
        strict=strict,
    )
    if not result.ok:
        return result

    if result.status == STATUS_SESSION_REQUIRED:
        return result

    has_decision_id = bool(summary.get("decision_id"))
    has_grant_id = bool(summary.get("grant_id"))
    has_decision_hash = bool(summary.get("decision_hash"))
    has_grant_hash = bool(summary.get("grant_hash"))

    if not has_decision_id:
        result.errors.append("completed summary missing authenticated decision_id")
    if not has_grant_id:
        result.errors.append("completed summary missing authenticated grant_id")
    if strict:
        if not has_decision_hash:
            result.errors.append("completed summary missing decision_hash")
        if not has_grant_hash:
            result.errors.append("completed summary missing grant_hash")
        # Paths alone are insufficient in strict mode.
        if summary.get("decision_path") and not has_decision_id:
            result.errors.append("decision_path without decision_id is not authenticated")
        if summary.get("grant_path") and not has_grant_id:
            result.errors.append("grant_path without grant_id is not authenticated")
    else:
        if not (has_decision_id or summary.get("decision_path")):
            result.errors.append("completed summary missing decision_id/decision_path")
        if not (has_grant_id or summary.get("grant_path")):
            result.errors.append("completed summary missing grant_id/grant_path")

    # approved_scope may remain as display/migration field; envelope preferred.
    if not summary.get("approved_scope") and not summary.get("authorization_envelope"):
        result.errors.append(
            "completed summary missing approved_scope or authorization_envelope"
        )
    result.ok = not result.errors
    return result
