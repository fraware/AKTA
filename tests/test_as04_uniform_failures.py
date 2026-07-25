"""AS-04 uniform failure mapping tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from akta.errors import GrantVerificationError, SchemaValidationError, UnsupportedProfileError
from akta.failure_mapping import (
    UNIFORM_CLASSES,
    failures_for_decision,
    map_exception,
    map_local_reason,
    map_rest_error,
    normalize_failure_class_code,
)
from akta.records import validate_against_schema

FIX = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "as04"


@pytest.mark.parametrize("uniform_class", UNIFORM_CLASSES)
def test_each_uniform_class_fixture(uniform_class: str) -> None:
    path = FIX / f"{uniform_class}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    validate_against_schema(data, "uniform_failure.schema.json")
    assert data["uniform_class"] == uniform_class
    assert data["local_reason_code"]


def test_local_codes_preserved() -> None:
    f = map_local_reason("F01_weak_evidence_escalation", detail="weak")
    assert f["local_reason_code"] == "F01_weak_evidence_escalation"
    assert f["uniform_class"] == "insufficient_evidence"


def test_f1_normalized_to_f01() -> None:
    assert normalize_failure_class_code("F1_weak_evidence_escalation") == "F01_weak_evidence_escalation"
    f = map_local_reason("F1_weak_evidence_escalation", detail="x")
    assert f["local_reason_code"] == "F01_weak_evidence_escalation"


def test_rest_preserves_error_code() -> None:
    f = map_rest_error("grant_invalid", detail="bad grant")
    assert f["error_code"] == "grant_invalid"
    assert f["local_reason_code"] == "grant_invalid"


def test_map_exception_types() -> None:
    assert map_exception(SchemaValidationError("bad"))["uniform_class"] == "invalid_input"
    assert map_exception(UnsupportedProfileError("P7"))["uniform_class"] == "policy_block"
    assert map_exception(GrantVerificationError("nope"))["uniform_class"] == "verification_failed"


def test_failures_for_decision() -> None:
    fails = failures_for_decision(
        {
            "admissibility": "blocked",
            "decision_reason": "insufficient evidence for action",
            "next_admissible_steps": ["gather_evidence"],
            "evaluation_layers": [
                {"source": "evidence_rules", "decision": "blocked", "reason": "evidence too weak"}
            ],
        }
    )
    assert fails and fails[0]["uniform_class"] == "insufficient_evidence"
    assert fails[0]["next_admissible_steps"] == ["gather_evidence"]
