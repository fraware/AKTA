"""Integrated acceptance: protocol-modification matrix (AKTA 1.1).

SCOPE grants a single draft for protocol-v3. Assert the plan matrix and that
the final Record preserves full authorization provenance + PF/PCS refs.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from adapters.pcs.export_artifact import export_pcs_bundle, validate_pcs_bundle
from adapters.pf_core.export_obligation import build_pf_obligation, export_pf_obligation
from akta import AKTAContext, AKTAGate
from akta.capability_envelope import legacy_scope_to_envelope
from akta.errors import GrantVerificationError
from akta.scope_grant_verifier import verify_scope_grant, verify_scope_grant_or_raise
from akta.trust_store import generate_test_keypair, sign_payload_hash_ed25519
from tests.helpers.institutional_grant import (
    make_institutional_kit,
    make_signed_grant,
    sign_status,
)

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "integrated_protocol_drift"


@pytest.fixture
def gate() -> AKTAGate:
    return AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")


@pytest.fixture
def protocol_v3_kit(tmp_path: Path) -> dict[str, Any]:
    kit = make_institutional_kit(tmp_path)
    envelope = legacy_scope_to_envelope(
        approved_scope="protocol_draft",
        allowed_tools=["protocol_editor.draft_change"],
        blocked_tools=[
            "protocol_editor.update_active_protocol",
            "robot_queue.submit",
        ],
        target={"type": "protocol", "protocol_id": "protocol-v3"},
        environment={"tenant_id": "tenant-a"},
        responsibility_ceiling="R4_methodological_modification",
        cardinality={"mode": "single", "maximum_uses": 1, "maximum_items": 1},
        constraints={"protocol_version": "protocol-v3"},
    )
    grant, status, arts = make_signed_grant(
        kit,
        envelope=envelope,
        overrides={
            "expiration": {
                "absolute_expiration": "2030-01-01T00:00:00Z",
                "expires_after": ["protocol_version_change"],
            },
            "constraints": {
                "single_use": True,
                "tenant_id": "tenant-a",
                "protocol_version": "protocol-v3",
            },
        },
    )
    kit.update(
        {
            "grant": grant,
            "status": status,
            "artifacts": arts,
            "envelope": envelope,
        }
    )
    return kit


def _base_context(**overrides: Any) -> dict[str, Any]:
    ctx = {
        "evidence_state": "E4_internally_consistent_evidence",
        "validation_status": "V3_preliminary_experimental_support",
        "protocol_version": "protocol-v3",
        "tenant_id": "tenant-a",
        "domain": "materials",
        "system_id": "protocol_drift_acceptance",
        "project_id": "demo_protocol_drift",
        "responsibility_level": "R4_methodological_modification",
        "item_count": 1,
    }
    ctx.update(overrides)
    return ctx


def _prior_record(*, admissibility: str = "review_required") -> dict[str, Any]:
    return {
        "decision": {"admissibility": admissibility},
        "classification": {
            "evidence_state": "E4_internally_consistent_evidence",
            "action_type": "A5_protocol_modification",
        },
        "scientific_context": {"protocol_version": "protocol-v3"},
    }


def _verify_kwargs(kit: dict[str, Any]) -> dict[str, Any]:
    return {
        "verification_mode": "pilot",
        "trust_store": kit["issuer_store"],
        "ledger_status": kit["status"],
        "authorization_manifest": kit["manifest"],
        "source_artifacts": kit["artifacts"],
        "action_class": "A5_protocol_modification",
        "validate_output": False,
        "status_trust_store": kit["status_store"],
        "manifest_trust_store": kit["manifest_store"],
    }


def test_initial_active_update_requires_review(gate: AKTAGate) -> None:
    decision = gate.evaluate(
        ai_output={"summary": "Update active protocol-v3 threshold."},
        requested_tool="protocol_editor.update_active_protocol",
        requested_action="update_threshold",
        context=AKTAContext.from_dict(_base_context()),
        deployment_profile="P4_protocol_drafting_assistant",
        domain_overlay="generic_lab_v0",
    )
    assert decision.admissibility == "review_required"


def test_draft_same_protocol_allowed_or_draft_only(
    gate: AKTAGate, protocol_v3_kit: dict[str, Any]
) -> None:
    kit = protocol_v3_kit
    prior = _prior_record()
    decision = gate.evaluate_with_grant(
        ai_output={"summary": "Draft timing tweak for protocol-v3."},
        requested_tool="protocol_editor.draft_change",
        requested_action="draft",
        context=AKTAContext.from_dict(_base_context()),
        deployment_profile="P4_protocol_drafting_assistant",
        domain_overlay="generic_lab_v0",
        scope_grant=kit["grant"],
        record=prior,
        trigger={"review_trigger_id": kit["artifacts"]["review_trigger"]["review_trigger_id"]},
        **_verify_kwargs(kit),
    )
    assert decision.admissibility in ("allowed", "draft_only", "allowed_with_logging")
    data = decision.to_dict()
    assert data.get("authorization_provenance")
    assert data["authorization_provenance"].get("initial_admissibility") == "review_required"


def test_active_protocol_update_blocked_by_envelope(
    gate: AKTAGate, protocol_v3_kit: dict[str, Any]
) -> None:
    kit = protocol_v3_kit
    with pytest.raises(GrantVerificationError):
        gate.evaluate_with_grant(
            ai_output={"summary": "Push active update under draft grant."},
            requested_tool="protocol_editor.update_active_protocol",
            requested_action="update_threshold",
            context=AKTAContext.from_dict(_base_context()),
            deployment_profile="P4_protocol_drafting_assistant",
            domain_overlay="generic_lab_v0",
            scope_grant=kit["grant"],
            record=_prior_record(),
            **_verify_kwargs(kit),
        )
    # Soft path: unit mode still must not unlock active update as draft_only.
    soft = gate.evaluate_with_grant(
        ai_output={"summary": "Push active update under draft grant."},
        requested_tool="protocol_editor.update_active_protocol",
        requested_action="update_threshold",
        context=AKTAContext.from_dict(_base_context()),
        deployment_profile="P4_protocol_drafting_assistant",
        domain_overlay="generic_lab_v0",
        scope_grant=kit["grant"],
        record=_prior_record(),
        verification_mode="unit",
        trust_store=kit["issuer_store"],
        ledger_status=kit["status"],
        authorization_manifest=kit["manifest"],
        source_artifacts=kit["artifacts"],
        action_class="A5_protocol_modification",
        validate_output=False,
        status_trust_store=kit["status_store"],
        manifest_trust_store=kit["manifest_store"],
    )
    assert soft.admissibility in ("blocked", "review_required", "authorization_required")
    assert soft.admissibility != "draft_only"


def test_draft_different_protocol_blocked_by_target(
    gate: AKTAGate, protocol_v3_kit: dict[str, Any]
) -> None:
    kit = protocol_v3_kit
    with pytest.raises(GrantVerificationError):
        gate.evaluate_with_grant(
            ai_output={"summary": "Draft for protocol-v9."},
            requested_tool="protocol_editor.draft_change",
            requested_action="draft",
            context=AKTAContext.from_dict(_base_context(protocol_version="protocol-v9")),
            deployment_profile="P4_protocol_drafting_assistant",
            domain_overlay="generic_lab_v0",
            scope_grant=kit["grant"],
            record=_prior_record(),
            **_verify_kwargs(kit),
        )


def test_draft_different_tenant_blocked_by_environment(
    gate: AKTAGate, protocol_v3_kit: dict[str, Any]
) -> None:
    kit = protocol_v3_kit
    with pytest.raises(GrantVerificationError):
        gate.evaluate_with_grant(
            ai_output={"summary": "Draft for other tenant."},
            requested_tool="protocol_editor.draft_change",
            requested_action="draft",
            context=AKTAContext.from_dict(_base_context(tenant_id="tenant-b")),
            deployment_profile="P4_protocol_drafting_assistant",
            domain_overlay="generic_lab_v0",
            scope_grant=kit["grant"],
            record=_prior_record(),
            **_verify_kwargs(kit),
        )


def test_draft_responsibility_above_r4_blocked(
    gate: AKTAGate, protocol_v3_kit: dict[str, Any]
) -> None:
    kit = protocol_v3_kit
    with pytest.raises(GrantVerificationError):
        gate.evaluate_with_grant(
            ai_output={"summary": "Draft with R6 responsibility."},
            requested_tool="protocol_editor.draft_change",
            requested_action="draft",
            context=AKTAContext.from_dict(
                {
                    **_base_context(),
                    "structured_action": {
                        "action_type": "A5_protocol_modification",
                        "responsibility_level": "R6_physical_execution",
                        "protocol_id": "protocol-v3",
                        "tenant_id": "tenant-a",
                    },
                }
            ),
            deployment_profile="P4_protocol_drafting_assistant",
            domain_overlay="generic_lab_v0",
            scope_grant=kit["grant"],
            record=_prior_record(),
            **_verify_kwargs(kit),
        )


def test_second_use_blocked_by_authoritative_status(
    gate: AKTAGate, protocol_v3_kit: dict[str, Any]
) -> None:
    kit = protocol_v3_kit
    exhausted = deepcopy(kit["status"])
    exhausted["cardinality_remaining"] = 0
    exhausted = sign_status(exhausted, kit["status_keys"])
    with pytest.raises(GrantVerificationError):
        gate.evaluate_with_grant(
            ai_output={"summary": "Second draft use."},
            requested_tool="protocol_editor.draft_change",
            requested_action="draft",
            context=AKTAContext.from_dict(_base_context()),
            deployment_profile="P4_protocol_drafting_assistant",
            domain_overlay="generic_lab_v0",
            scope_grant=kit["grant"],
            record=_prior_record(),
            verification_mode="pilot",
            trust_store=kit["issuer_store"],
            ledger_status=exhausted,
            authorization_manifest=kit["manifest"],
            source_artifacts=kit["artifacts"],
            action_class="A5_protocol_modification",
            validate_output=False,
            status_trust_store=kit["status_store"],
            manifest_trust_store=kit["manifest_store"],
        )


def test_tampered_grant_rejected_before_evaluation(
    protocol_v3_kit: dict[str, Any],
) -> None:
    kit = protocol_v3_kit
    tampered = deepcopy(kit["grant"])
    tampered["grant_signature"] = "sha256:" + ("0" * 64)
    result = verify_scope_grant(
        tampered,
        mode="pilot",
        trust_store=kit["issuer_store"],
        status_trust_store=kit["status_store"],
        authorization_manifest=kit["manifest"],
        manifest_trust_store=kit["manifest_store"],
        ledger_status=kit["status"],
        source_artifacts=kit["artifacts"],
    )
    assert not result.ok


def test_fake_issuer_rejected_before_evaluation(
    tmp_path: Path, protocol_v3_kit: dict[str, Any]
) -> None:
    kit = protocol_v3_kit
    fake = generate_test_keypair(tmp_path / "fake")
    forged = deepcopy(kit["grant"])
    forged["issuer"] = {
        "issuer_identity": "attacker",
        "issuer_key_id": fake["public_key_ref"],
    }
    priv = Path(fake["private_key_path"]).read_bytes()
    forged["grant_signature"] = sign_payload_hash_ed25519(priv, forged["grant_hash"])
    with pytest.raises(GrantVerificationError):
        verify_scope_grant_or_raise(
            forged,
            mode="pilot",
            trust_store=kit["issuer_store"],
            status_trust_store=kit["status_store"],
            authorization_manifest=kit["manifest"],
            manifest_trust_store=kit["manifest_store"],
            ledger_status=kit["status"],
            source_artifacts=kit["artifacts"],
        )


def test_revoked_status_rejected_before_evaluation(
    protocol_v3_kit: dict[str, Any],
) -> None:
    kit = protocol_v3_kit
    revoked = deepcopy(kit["status"])
    revoked["status"] = "revoked"
    revoked = sign_status(revoked, kit["status_keys"])
    with pytest.raises(GrantVerificationError):
        verify_scope_grant_or_raise(
            kit["grant"],
            mode="pilot",
            trust_store=kit["issuer_store"],
            status_trust_store=kit["status_store"],
            authorization_manifest=kit["manifest"],
            manifest_trust_store=kit["manifest_store"],
            ledger_status=revoked,
            source_artifacts=kit["artifacts"],
        )


def test_weak_evidence_remains_evidence_blocked(
    gate: AKTAGate, protocol_v3_kit: dict[str, Any]
) -> None:
    kit = protocol_v3_kit
    decision = gate.evaluate_with_grant(
        ai_output={"summary": "Draft with weak evidence."},
        requested_tool="protocol_editor.draft_change",
        requested_action="draft",
        context=AKTAContext.from_dict(
            _base_context(evidence_state="E1_anecdotal_or_unverified")
        ),
        deployment_profile="P4_protocol_drafting_assistant",
        domain_overlay="generic_lab_v0",
        scope_grant=kit["grant"],
        record=_prior_record(),
        **_verify_kwargs(kit),
    )
    data = decision.to_dict()
    assert data["admissibility"] in ("blocked", "abstain_insufficient_context")
    satisfaction = data.get("grant_layer_satisfaction") or {}
    assert satisfaction.get("evidence_never_satisfied_by_grant") is True


def test_changed_protocol_version_renewed_review(
    gate: AKTAGate, protocol_v3_kit: dict[str, Any]
) -> None:
    kit = protocol_v3_kit
    prior = _prior_record()
    prior["scientific_context"] = {"protocol_version": "protocol-v3"}
    # Containment fails closed when requested protocol_id diverges from grant target.
    with pytest.raises(GrantVerificationError):
        gate.evaluate_with_grant(
            ai_output={"summary": "Draft after protocol changed."},
            requested_tool="protocol_editor.draft_change",
            requested_action="draft",
            context=AKTAContext.from_dict(
                _base_context(protocol_version="protocol-v3-rev2")
            ),
            deployment_profile="P4_protocol_drafting_assistant",
            domain_overlay="generic_lab_v0",
            scope_grant=kit["grant"],
            record=prior,
            **_verify_kwargs(kit),
        )


def test_missing_runtime_target_insufficient_context(
    gate: AKTAGate, protocol_v3_kit: dict[str, Any]
) -> None:
    kit = protocol_v3_kit
    ctx = _base_context()
    ctx.pop("protocol_version", None)
    with pytest.raises(GrantVerificationError):
        gate.evaluate_with_grant(
            ai_output={"summary": "Draft without protocol target."},
            requested_tool="protocol_editor.draft_change",
            requested_action="draft",
            context=AKTAContext.from_dict(ctx),
            deployment_profile="P4_protocol_drafting_assistant",
            domain_overlay="generic_lab_v0",
            scope_grant=kit["grant"],
            record=_prior_record(),
            **_verify_kwargs(kit),
        )


def test_final_record_preserves_full_provenance(
    gate: AKTAGate, protocol_v3_kit: dict[str, Any], tmp_path: Path
) -> None:
    kit = protocol_v3_kit
    prior = _prior_record()
    decision = gate.evaluate_with_grant(
        ai_output={"summary": "Draft timing tweak for protocol-v3."},
        requested_tool="protocol_editor.draft_change",
        requested_action="draft",
        context=AKTAContext.from_dict(_base_context()),
        deployment_profile="P4_protocol_drafting_assistant",
        domain_overlay="generic_lab_v0",
        scope_grant=kit["grant"],
        record=prior,
        trigger={"review_trigger_id": kit["artifacts"]["review_trigger"]["review_trigger_id"]},
        **_verify_kwargs(kit),
    )
    assert decision.admissibility in ("allowed", "draft_only", "allowed_with_logging")

    record = decision.to_record(
        ai_output={"summary": "Draft timing tweak for protocol-v3."},
        context={
            "pf_core_obligation_ref": "PF-OBL-ACCEPTANCE",
            "pcs_artifact_ref": "PCS-ACCEPTANCE",
            "project_id": "demo_protocol_drift",
        },
    )
    body = record.to_dict()
    auth = body.get("authorization_provenance") or {}
    assert auth.get("initial_admissibility") == "review_required"
    assert auth.get("grant_verification")
    assert auth.get("status_attestation") or auth.get("grant_verification", {}).get(
        "ledger_status"
    )
    assert auth.get("requested_envelope") or auth.get("requested_authorization")
    assert auth.get("granted_envelope") or body.get("capability_envelope")
    assert auth.get("containment") is not None or auth.get(
        "envelope_covers_requested_scope"
    ) is True
    assert body.get("evidence_independence") or body.get("grant_layer_satisfaction")
    assert body["decision"]["admissibility"] == decision.admissibility
    assert body["provenance"].get("policy_hash", "").startswith("sha256:")
    assert body["integrations"].get("pf_core_obligation_ref") == "PF-OBL-ACCEPTANCE"
    assert body["integrations"].get("pcs_artifact_ref") == "PCS-ACCEPTANCE"

    obligation = build_pf_obligation(
        body, decision_id=decision.to_dict().get("decision_id")
    )
    pf_path = export_pf_obligation(
        record, tmp_path / "pf", decision_id=decision.to_dict().get("decision_id")
    )
    assert Path(pf_path).is_file()
    assert obligation.get("obligation_id")

    pcs_dir = tmp_path / "pcs"
    export_pcs_bundle(
        record,
        pcs_dir,
        decision=decision.to_dict(),
        scope_grant=kit["grant"],
        pf_obligation=obligation,
        validate=True,
    )
    validate_pcs_bundle(pcs_dir)
    assert (pcs_dir / "scope_grant.json").is_file()
    assert (pcs_dir / "pf_obligation.json").is_file()


def test_example_fixtures_present() -> None:
    assert EXAMPLE.is_dir()
    assert (EXAMPLE / "context.json").is_file()
    assert (EXAMPLE / "scope_narrow_grant.json").is_file()
    assert (EXAMPLE / "pcs_bundle" / "manifest.json").is_file()
