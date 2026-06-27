"""Tests for JSON schema validation."""

import json
from pathlib import Path

import pytest

from akta.gate import AKTAGate
from akta.context import AKTAContext
from akta.records import validate_against_schema
from akta.errors import SchemaValidationError

ROOT = Path(__file__).resolve().parent.parent
SCHEMAS = ROOT / "schemas"


@pytest.mark.parametrize(
    "schema_file",
    [
        "akta_decision.schema.json",
        "akta_record.schema.json",
        "akta_context.schema.json",
        "akta_card.schema.json",
        "tool_registry.schema.json",
        "domain_overlay.schema.json",
        "review_trigger.schema.json",
        "multi_agent_handoff.schema.json",
    ],
)
def test_schema_files_exist(schema_file: str) -> None:
    assert (SCHEMAS / schema_file).exists()


def test_decision_schema_validates() -> None:
    gate = AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")
    decision = gate.evaluate(
        ai_output="test",
        requested_tool="literature_search.query",
        requested_action="search",
        context=AKTAContext(),
        deployment_profile="P1_literature_hypothesis_assistant",
    )
    validate_against_schema(decision.to_dict(), "akta_decision.schema.json")


def test_invalid_record_fails_schema() -> None:
    with pytest.raises(SchemaValidationError):
        validate_against_schema({"record_id": "bad"}, "akta_record.schema.json")
