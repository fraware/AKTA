"""Skill validation tests for akta-scientific-action-admissibility."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from akta import AKTAGate, AKTAContext

SKILL_DIR = Path(__file__).resolve().parent.parent
ROOT = SKILL_DIR.parents[1]


@pytest.fixture
def skill_md() -> str:
    return (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")


def test_skill_frontmatter(skill_md: str) -> None:
    assert skill_md.startswith("---")
    assert "name: akta-scientific-action-admissibility" in skill_md
    assert "description:" in skill_md


def test_skill_description_length(skill_md: str) -> None:
    match = re.search(r"description:\s*>-\s*\n((?:\s+.+\n?)+)", skill_md)
    assert match, "description block required"
    desc = match.group(1).replace("\n", " ").strip()
    assert len(desc) <= 1024


def test_skill_has_examples_dir() -> None:
    examples = list((SKILL_DIR / "examples").glob("*.md"))
    assert len(examples) >= 2


def test_weak_evidence_example_matches_gate() -> None:
    gate = AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")
    decision = gate.evaluate(
        ai_output={"summary": "Prioritize condition B based on preliminary signal."},
        requested_tool="lab_scheduler.prioritize",
        requested_action="prioritize_next_run",
        context=AKTAContext.from_dict({"evidence_state": "E2_preliminary_signal", "validation_status": "V0_unvalidated"}),
        deployment_profile="P2_analysis_assistant",
        domain_overlay="generic_lab_v0",
    )
    assert decision.admissibility == "blocked"
    assert decision.to_dict()["scientific_action_type"] == "A7_resource_or_queue_prioritization"


def test_multi_agent_handoff_example_blocked() -> None:
    gate = AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")
    ctx = {
        "evidence_state": "E3_noisy_or_conflicting_evidence",
        "validation_status": "V2_simulation_supported",
        "handoff_chain": [
            {"agent_id": "a", "action_type": "A2_hypothesis_generation", "responsibility_level": "R1_epistemic_assistance"},
            {"agent_id": "b", "action_type": "A6_experimental_planning", "responsibility_level": "R5_experimental_planning"},
            {"agent_id": "c", "action_type": "A7_resource_or_queue_prioritization", "responsibility_level": "R6_resource_allocation"},
        ],
    }
    decision = gate.evaluate(
        ai_output={"summary": "Place condition D at top of queue."},
        requested_tool="lab_scheduler.prioritize",
        requested_action="prioritize_condition_d",
        context=AKTAContext.from_dict(ctx),
        deployment_profile="P5_review_gated_experimental_planner",
        domain_overlay="generic_lab_v0",
    )
    assert decision.admissibility == "blocked"
