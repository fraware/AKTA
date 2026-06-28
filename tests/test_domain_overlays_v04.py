"""Gate tests for operational domain overlays (v0.4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from akta import AKTAGate, AKTAContext

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def gate() -> AKTAGate:
    return AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")


@pytest.mark.parametrize(
    "overlay,tool,action,hazard,expected",
    [
        (
            "biology_v0",
            "cell_culture.schedule",
            "schedule_passage",
            "bsl3_pathogen_present",
            "authorization_required",
        ),
        (
            "biology_v0",
            "robot_queue.submit",
            "submit_batch",
            None,
            "blocked",
        ),
        (
            "chemistry_v0",
            "synthesis_planner.schedule",
            "schedule_reaction",
            "pyrophoric_reagent_present",
            "authorization_required",
        ),
        (
            "chemistry_v0",
            "reagent_inventory.allocate",
            "allocate_precursor",
            "explosive_precursor",
            "blocked",
        ),
        (
            "clinical_v0",
            "ehr.draft_note",
            "draft_note",
            None,
            "blocked",
        ),
        (
            "clinical_v0",
            "trial_scheduler.enroll",
            "enroll_patient",
            "phi_exposure_risk",
            "blocked",
        ),
    ],
)
def test_domain_overlay_gate(
    gate: AKTAGate,
    overlay: str,
    tool: str,
    action: str,
    hazard: str | None,
    expected: str,
) -> None:
    metadata = {"hazard_flags": [hazard]} if hazard else {}
    decision = gate.evaluate(
        ai_output={"summary": f"Request {action}"},
        requested_tool=tool,
        requested_action=action,
        context=AKTAContext.from_dict({
            "domain": overlay.split("_")[0],
            "evidence_state": "E4_internally_consistent_evidence",
            "metadata": metadata,
        }),
        deployment_profile="P5_review_gated_experimental_planner",
        domain_overlay=overlay,
    )
    assert decision.admissibility == expected


def test_biology_overlay_blocks_recombinant_dna(gate: AKTAGate) -> None:
    decision = gate.evaluate(
        ai_output={"summary": "Modify vector"},
        requested_tool="gene_editor.draft_change",
        requested_action="edit_cassette",
        context=AKTAContext.from_dict({
            "evidence_state": "E4_internally_consistent_evidence",
            "metadata": {"hazard_flags": ["recombinant_dna_unregistered"]},
        }),
        deployment_profile="P4_protocol_drafting_assistant",
        domain_overlay="biology_v0",
    )
    assert decision.admissibility == "blocked"


def test_clinical_overlay_requires_high_evidence_for_planning(gate: AKTAGate) -> None:
    decision = gate.evaluate(
        ai_output={"summary": "Plan trial arm"},
        requested_tool="experiment_planner.create_run_plan",
        requested_action="create_plan",
        context=AKTAContext.from_dict({"evidence_state": "E4_internally_consistent_evidence"}),
        deployment_profile="P5_review_gated_experimental_planner",
        domain_overlay="clinical_v0",
    )
    assert decision.admissibility in ("blocked", "review_required")
