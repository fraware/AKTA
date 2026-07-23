"""P1-E pilot workflow stage gate tests."""

from __future__ import annotations

from akta.pilot_workflow import PilotStage, evaluate_pilot_gate, resolve_pilot_stage


def test_resolve_stage_aliases() -> None:
    assert resolve_pilot_stage("shadow") == PilotStage.SHADOW
    assert resolve_pilot_stage("draft_only") == PilotStage.DRAFT_ONLY
    assert resolve_pilot_stage("3") == PilotStage.VALIDATION


def test_exclusions_block_robot_and_clinical() -> None:
    r = evaluate_pilot_gate(
        stage="stage1_shadow",
        requested_tool="robot_queue.submit",
        metadata={"physical_robot": True},
    )
    assert not r.ok
    assert "physical_robot" in r.exclusions_hit


def test_stage2_rejects_mutating() -> None:
    r = evaluate_pilot_gate(
        stage="stage2_draft_only",
        requested_tool="protocol_editor.draft_change",
        metadata={"mutates_state": True},
    )
    assert not r.ok


def test_stage3_fail_closed_without_evidence() -> None:
    r = evaluate_pilot_gate(
        stage="stage3_validation",
        requested_tool="protocol_editor.draft_change",
        evidence={},
    )
    assert not r.ok
    assert any("scope_identity" in e for e in r.errors)
    assert any("signed_grant" in e for e in r.errors)
    assert any("pf_runtime_proof" in e for e in r.errors)
    assert any("pcs_package" in e for e in r.errors)
    assert any("transactional_ledger" in e for e in r.errors)


def test_stage3_accepts_full_evidence() -> None:
    r = evaluate_pilot_gate(
        stage="stage3_validation",
        requested_tool="protocol_editor.draft_change",
        evidence={
            "scope_identity": True,
            "signed_grant": True,
            "full_grant_verification": True,
            "pf_runtime_proof": True,
            "pcs_package": True,
            "transactional_ledger": True,
        },
    )
    assert r.ok
    assert r.policy_switches["require_signed_grant"] is True
    assert r.beta is True
