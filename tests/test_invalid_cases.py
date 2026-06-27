"""Tests for invalid scenario cases."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from akta import AKTAGate, AKTAContext
from akta.errors import SchemaValidationError, UnsupportedProfileError
from akta.records import validate_against_schema
from evals.run_scenarios import load_jsonl

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def gate() -> AKTAGate:
    return AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")


def test_invalid_cases_file_exists() -> None:
    path = ROOT / "scenarios" / "invalid_cases.jsonl"
    assert path.exists()
    cases = load_jsonl(path)
    assert len(cases) >= 3


def test_unsupported_p7_profile_fails(gate: AKTAGate) -> None:
    with pytest.raises(Exception):
        gate.evaluate(
            ai_output="test",
            requested_tool="literature_search.query",
            requested_action="search",
            context=AKTAContext(),
            deployment_profile="P7_fully_autonomous_scientific_operator",
        )


def test_malformed_record_fails_schema() -> None:
    with pytest.raises(SchemaValidationError):
        validate_against_schema({"record_id": "bad"}, "akta_record.schema.json")


def test_unknown_mutating_tool_abstains(gate: AKTAGate) -> None:
    decision = gate.evaluate(
        ai_output="mutate",
        requested_tool="unregistered.custom_mutator",
        requested_action="mutate_state",
        context=AKTAContext.from_dict({"evidence_state": "E4_internally_consistent_evidence"}),
        deployment_profile="P5_review_gated_experimental_planner",
    )
    assert decision.admissibility == "abstain_insufficient_context"


def test_policy_hash_mismatch_detectable(gate: AKTAGate) -> None:
    decision = gate.evaluate(
        ai_output="test",
        requested_tool="literature_search.query",
        requested_action="search",
        context=AKTAContext(),
        deployment_profile="P1_literature_hypothesis_assistant",
    )
    d = decision.to_dict()
    assert d["policy_hash"] != "sha256:deadbeef"
    assert d["policy_hash"].startswith("sha256:")


def test_invalid_jsonl_entries_flagged() -> None:
    cases = load_jsonl(ROOT / "scenarios" / "invalid_cases.jsonl")
    p7_cases = [c for c in cases if c.get("deployment_profile", "").startswith("P7")]
    assert len(p7_cases) >= 1
