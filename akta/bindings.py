"""AKTA binding-set construction and verification (AS-01)."""

from __future__ import annotations

from typing import Any

from akta.hash import hash_object
from akta.records import validate_against_schema

BINDING_SET_VERSION = "akta-binding-set-v1"


def digest_or_none(payload: Any) -> str | None:
    """Return sha256 digest for a JSON-serializable payload, or None if empty."""
    if payload is None:
        return None
    if payload == "" or payload == {} or payload == []:
        return None
    return hash_object(payload)


def extract_claim_set(vsa_bundle: dict[str, Any] | None) -> list[dict[str, Any]] | None:
    if not isinstance(vsa_bundle, dict):
        return None
    claims = vsa_bundle.get("claims")
    if isinstance(claims, list):
        return [c for c in claims if isinstance(c, dict)]
    return None


def extract_evidence_report(vsa_bundle: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(vsa_bundle, dict):
        return None
    # Prefer explicit evidence_report; else freeze the report body without mutable wrappers.
    if isinstance(vsa_bundle.get("evidence_report"), dict):
        return vsa_bundle["evidence_report"]
    body = {
        k: v
        for k, v in vsa_bundle.items()
        if k
        not in (
            "bundle_digest",
            "declared_digest",
            "schema",
            "schema_version",
            "bundle_version",
        )
    }
    return body or None


def build_binding_set(
    *,
    decision_id: str,
    record_id: str,
    policy_hash: str,
    tool_registry_hash: str,
    requested_tool: str,
    action_class: str,
    domain_overlay_hash: str | None = None,
    scientific_question: Any = None,
    evidence_report: Any = None,
    claim_set: Any = None,
    proposed_action: Any = None,
    vsa_bundle: dict[str, Any] | None = None,
    vsa_bundle_digest: str | None = None,
    decision_basis_digest: str | None = None,
    scope_review_ref: str | None = None,
    pf_obligation_ref: str | None = None,
    pcs_manifest_ref: str | None = None,
    execution_ref: str | None = None,
    outcome_ref: str | None = None,
    validate: bool = True,
) -> dict[str, Any]:
    """Build a schema-valid binding set for a decision/record."""
    bundle = vsa_bundle if isinstance(vsa_bundle, dict) else None
    evidence = evidence_report if evidence_report is not None else extract_evidence_report(bundle)
    claims = claim_set if claim_set is not None else extract_claim_set(bundle)
    computed_vsa = vsa_bundle_digest
    if computed_vsa is None and bundle is not None:
        frozen = {k: v for k, v in bundle.items() if k not in ("bundle_digest", "declared_digest")}
        computed_vsa = hash_object(frozen)

    bindings: dict[str, Any] = {
        "binding_set_version": BINDING_SET_VERSION,
        "decision_id": decision_id,
        "record_id": record_id,
        "scientific_question_digest": digest_or_none(scientific_question),
        "evidence_report_digest": digest_or_none(evidence),
        "claim_set_digest": digest_or_none(claims),
        "proposed_action_digest": digest_or_none(proposed_action),
        "vsa_decision_time_bundle_digest": computed_vsa,
        "vsa_bundle_schema": (bundle or {}).get("schema") or (bundle or {}).get("schema_version"),
        "vsa_bundle_version": (bundle or {}).get("bundle_version") or (bundle or {}).get("version"),
        "policy_hash": policy_hash,
        "domain_overlay_hash": domain_overlay_hash,
        "tool_registry_hash": tool_registry_hash,
        "requested_tool": requested_tool,
        "action_class": action_class,
        "decision_basis_digest": decision_basis_digest,
        "scope_review_ref": scope_review_ref,
        "pf_obligation_ref": pf_obligation_ref,
        "pcs_manifest_ref": pcs_manifest_ref,
        "execution_ref": execution_ref,
        "outcome_ref": outcome_ref,
    }
    if validate:
        validate_against_schema(bindings, "akta_binding_set.schema.json")
    return bindings


def verify_policy_hashes(
    *,
    bindings: dict[str, Any],
    loaded_policy_hash: str,
    loaded_overlay_hash: str | None,
    loaded_tool_registry_hash: str,
) -> list[str]:
    """Return errors when binding hashes are stale vs currently loaded files."""
    errors: list[str] = []
    if bindings.get("policy_hash") != loaded_policy_hash:
        errors.append(
            "stale_policy_hash: binding "
            f"{bindings.get('policy_hash')} != loaded {loaded_policy_hash}"
        )
    if bindings.get("tool_registry_hash") != loaded_tool_registry_hash:
        errors.append(
            "stale_tool_registry_hash: binding "
            f"{bindings.get('tool_registry_hash')} != loaded {loaded_tool_registry_hash}"
        )
    bound_overlay = bindings.get("domain_overlay_hash")
    if bound_overlay and loaded_overlay_hash and bound_overlay != loaded_overlay_hash:
        errors.append(
            f"stale_domain_overlay_hash: binding {bound_overlay} != loaded {loaded_overlay_hash}"
        )
    return errors


def sync_binding_ids(
    payload: dict[str, Any],
    *,
    decision_id: str | None = None,
    record_id: str | None = None,
) -> dict[str, Any]:
    """Return a shallow copy of ``payload`` with binding IDs aligned.

    Demo stabilizers and PCS/PF exporters must keep ``bindings.decision_id`` /
    ``bindings.record_id`` synchronized with top-level IDs after ID rewriting.
    """
    out = dict(payload)
    bindings = out.get("bindings")
    if not isinstance(bindings, dict):
        return out
    synced = dict(bindings)
    if decision_id is not None:
        synced["decision_id"] = decision_id
    if record_id is not None:
        synced["record_id"] = record_id
    out["bindings"] = synced
    return out


__all__ = [
    "BINDING_SET_VERSION",
    "build_binding_set",
    "digest_or_none",
    "extract_claim_set",
    "extract_evidence_report",
    "sync_binding_ids",
    "verify_policy_hashes",
]
