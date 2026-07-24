"""AKTA ↔ SCOPE strict verify entrypoints (AKTA 1.2 P0-13).

Documented APIs consumed by SCOPE's ``scripts/run_akta_interop_conformance.py``:

- ``strict_verify_grant``
- ``verify_action_containment``
- ``verify_status_attestation``
- ``verify_evidence_independence``
- ``reject_exhausted_use``

These wrappers never invent missing SCOPE source fields. Callers must supply
native SCOPE artifacts unmodified.
"""

from __future__ import annotations

from typing import Any

from akta.contracts_runtime_api import request_satisfies_grant
from akta.evidence_independence import check_evidence_independence
from akta.lifecycle_semantics import status_lifecycle_errors
from akta.scope_grant_verifier import verify_scope_grant

# Source bindings that must be present with hashes on native SCOPE grants.
# Session / scope_decision bindings are required only when their id is present
# (never invented).
_ALWAYS_REQUIRED_SOURCE_BINDINGS: tuple[tuple[str, str], ...] = (
    ("decision_id", "decision_hash"),
    ("akta_record_id", "akta_record_hash"),
    ("review_trigger_id", "review_trigger_hash"),
    ("packet_id", "packet_hash"),
)
_CONDITIONAL_SOURCE_BINDINGS: tuple[tuple[str, str], ...] = (
    ("scope_decision_id", "scope_decision_hash"),
    ("session_resolution_id", "session_resolution_hash"),
)


def _grant_envelope(grant: dict[str, Any]) -> dict[str, Any] | None:
    auth = grant.get("authorization") or {}
    envelope = auth.get("authorization_envelope") or grant.get("authorization_envelope")
    return envelope if isinstance(envelope, dict) else None


def _source_chain_complete(grant: dict[str, Any]) -> bool:
    """True when required source id+hash pairs are present (no invention)."""
    source = grant.get("source")
    if not isinstance(source, dict) or not source:
        return False
    for id_field, hash_field in _ALWAYS_REQUIRED_SOURCE_BINDINGS:
        if not source.get(id_field) or not source.get(hash_field):
            return False
    for id_field, hash_field in _CONDITIONAL_SOURCE_BINDINGS:
        if source.get(id_field) and not source.get(hash_field):
            return False
    return True


def strict_verify_grant(
    grant: dict[str, Any],
    *,
    ledger_status: dict[str, Any] | None = None,
    authorization_manifest: dict[str, Any] | None = None,
    source_artifacts: dict[str, Any] | None = None,
    trust_store: dict[str, Any] | None = None,
    status_trust_store: dict[str, Any] | None = None,
    manifest_trust_store: dict[str, Any] | None = None,
    mode: str | None = None,
) -> bool:
    """Strict grant verify over native SCOPE bytes.

    Fail-closed when grant_hash / grant_signature / source-chain hashes /
    authorization envelope are missing. Does not invent source fields.

    When trust stores are supplied, runs full ``verify_scope_grant``. Otherwise
    performs structural + source-chain completeness checks suitable for the
    wheel interop runner (crypto verified when stores are configured).
    """
    if not isinstance(grant, dict):
        return False
    if not grant.get("grant_id"):
        return False
    if not grant.get("grant_hash"):
        return False
    if not (grant.get("grant_signature") or grant.get("signature")):
        return False
    if _grant_envelope(grant) is None:
        return False
    if not _source_chain_complete(grant):
        return False

    if any(
        x is not None
        for x in (
            trust_store,
            status_trust_store,
            manifest_trust_store,
            ledger_status,
            authorization_manifest,
            source_artifacts,
        )
    ):
        resolved_mode = mode or "pilot"
        result = verify_scope_grant(
            grant,
            mode=resolved_mode,
            ledger_status=ledger_status,
            authorization_manifest=authorization_manifest,
            source_artifacts=source_artifacts,
            trust_store=trust_store,
            status_trust_store=status_trust_store,
            manifest_trust_store=manifest_trust_store,
            require_capability_envelope=True,
        )
        return bool(result.ok)

    # Structural strict path for interop runner (no invented fields).
    return True


def verify_action_containment(
    grant: dict[str, Any],
    action: dict[str, Any],
    *,
    ledger_status: dict[str, Any] | None = None,
    mode: str = "release",
) -> bool:
    """Evaluate whether the independently observed action is contained by grant.

    When the action omits target / environment / responsibility fields, bind from
    the grant envelope (the grant's own declared coverage). Never invent
    ``unspecified`` / ``default`` sentinels.

    For ``evidence_state``, prefer the caller-supplied value when present; if the
    action omits it, bind from grant constraints (never invent a sentinel such as
    ``recorded``). A caller-supplied mismatch is preserved so containment/runtime
    can fail closed rather than silently rewriting SCOPE evidence.
    """
    envelope = _grant_envelope(grant)
    if envelope is None or not isinstance(action, dict):
        return False

    family = str(action.get("family") or "").strip()
    operation = str(action.get("operation") or "").strip()
    requested_tool = str(action.get("requested_tool") or "").strip()
    if not family or not operation or not requested_tool:
        return False

    env_target = dict(envelope.get("target") or {})
    env_environment = dict(envelope.get("environment") or {})
    grant_constraints = dict(grant.get("constraints") or {})

    target = dict(action.get("target") or {})
    environment = dict(action.get("environment") or {})
    for key in ("protocol_id", "protocol_version"):
        if action.get(key) is not None and key not in target:
            target[key] = action[key]
        if key not in target and env_target.get(key) is not None:
            target[key] = env_target[key]
    for key in ("tenant_id", "project_id", "deployment_id", "domain_overlay"):
        if action.get(key) is not None and key not in environment:
            environment[key] = action[key]
        if key not in environment and env_environment.get(key) is not None:
            environment[key] = env_environment[key]
        if key not in environment and grant_constraints.get(key) is not None:
            environment[key] = grant_constraints[key]
    if "type" not in target and target.get("protocol_id"):
        target["type"] = "protocol"
    elif "type" not in target and env_target.get("type"):
        target["type"] = env_target["type"]

    responsibility = (
        action.get("responsibility_level") or envelope.get("responsibility_ceiling")
    )
    if not responsibility:
        return False

    request_action: dict[str, Any] = {
        "family": family,
        "operation": operation,
        "target": target,
        "requested_tool": requested_tool,
        "environment": environment,
        "responsibility_level": responsibility,
        "item_count": int(action.get("item_count") or 1),
        "constraints": dict(action.get("constraints") or {}),
    }
    if action.get("control_evidence"):
        request_action["control_evidence"] = dict(action["control_evidence"])
    for key in ("tenant_id", "project_id", "deployment_id"):
        if key in environment:
            request_action.setdefault(key, environment[key])
    for key in ("protocol_id", "protocol_version"):
        if key in target:
            request_action.setdefault(key, target[key])

    evidence: dict[str, Any] = {}
    if ledger_status is not None:
        evidence["ledger_status"] = ledger_status
    if action.get("control_evidence"):
        evidence["control_evidence"] = dict(action["control_evidence"])
    evidence_state = action.get("evidence_state")
    if evidence_state is None:
        evidence_state = grant_constraints.get("evidence_state")
    if evidence_state is not None:
        evidence["evidence_state"] = evidence_state

    satisfaction = request_satisfies_grant(
        grant_envelope=envelope,
        requested_action=request_action,
        runtime_evidence=evidence or None,
        mode=mode,
    )
    return bool(satisfaction.satisfied)


def verify_status_attestation(
    attestation: dict[str, Any],
    grant: dict[str, Any],
) -> bool:
    """Verify status attestation is bound to the grant hash."""
    if not isinstance(attestation, dict) or not isinstance(grant, dict):
        return False
    grant_hash = grant.get("grant_hash")
    if not grant_hash:
        return False
    if attestation.get("grant_hash") != grant_hash:
        return False
    if attestation.get("grant_id") and attestation.get("grant_id") != grant.get("grant_id"):
        return False
    has_sig = bool(
        attestation.get("status_signature")
        or attestation.get("attestation_signature")
        or attestation.get("signature")
    )
    return has_sig


def verify_evidence_independence(
    grant: dict[str, Any],
    packet: dict[str, Any] | None = None,
    decision: dict[str, Any] | None = None,
) -> bool:
    """Confirm a SCOPE grant cannot upgrade an evidence-based block."""
    _ = (packet, decision)
    result = check_evidence_independence(
        scope_grant=grant,
        pre_layers={
            "evidence": {
                "decision": "blocked",
                "reason": "weak evidence block",
            }
        },
        post_decision="allowed",
        post_reason="cleared by grant",
    )
    # Independence holds when the upgrade attempt is rejected.
    return (not result.ok) and bool(result.violations)


def reject_exhausted_use(
    grant: dict[str, Any],
    status: dict[str, Any],
    action: dict[str, Any] | None = None,
) -> bool:
    """Return True when AKTA rejects further use given an exhausted status.

    True means \"further use must be rejected\". Terminal lifecycle states
    (exhausted / revoked / expired / ...) and zero remaining uses all qualify.
    Active grants with remaining uses (or unbounded remaining) return False.
    """
    _ = (grant, action)
    if not isinstance(status, dict):
        return False
    errors = status_lifecycle_errors(status)
    status_name = str(status.get("status") or "").lower()
    remaining = status.get("cardinality_remaining")
    if remaining is None:
        remaining = status.get("remaining_uses")
    try:
        remaining_exhausted = remaining is not None and int(remaining) <= 0
    except (TypeError, ValueError):
        remaining_exhausted = False
    exhausted = status_name in {"exhausted", "consumed", "used"} or remaining_exhausted
    # status_lifecycle_errors already flags terminal states (incl. expired/revoked).
    return exhausted or bool(errors)
