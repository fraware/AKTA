"""Fixture-driven SCOPE narrowing contract tests (AKTA-3)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from akta.scope_contract import (
    is_valid_narrowing_grant,
    load_valid_narrowing_pairs,
    scope_rank,
    validate_approval_grant,
)
from adapters.pcs.export_artifact import export_pcs_bundle
from akta import AKTAGate, AKTAContext
from akta.records import AKTARecord

ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def test_fixture_narrowing_pairs_all_validate() -> None:
    raw = json.loads((FIXTURES / "scope_valid_narrowing.json").read_text(encoding="utf-8"))
    for entry in raw["valid_narrowing_pairs"]:
        requested = entry["requested_scope"]
        granted = entry["granted_scope"]
        result = validate_approval_grant(
            granted_scope=granted,
            requested_scope=requested,
        )
        assert result["narrow_grant"] is True
        assert is_valid_narrowing_grant(granted_scope=granted, requested_scope=requested)


def test_same_rank_unlisted_pair_blocked() -> None:
    with pytest.raises(ValueError, match="does not cover"):
        validate_approval_grant(
            granted_scope="single_validation_run_draft",
            requested_scope="single_validation_plan",
        )


def test_overbroad_grant_fails_pcs_export(tmp_path: Path) -> None:
    gate = AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")
    decision = gate.evaluate(
        ai_output={"summary": "Update active protocol threshold."},
        requested_tool="protocol_editor.update_active_protocol",
        requested_action="update_threshold",
        context=AKTAContext.from_dict({
            "evidence_state": "E4_internally_consistent_evidence",
            "validation_status": "V3_preliminary_experimental_support",
        }),
        deployment_profile="P4_protocol_drafting_assistant",
        domain_overlay="generic_lab_v0",
    )
    d = decision.to_dict()
    record = decision.to_record().to_dict()
    record["review_trigger"] = d["review_trigger"]
    overbroad_grant = {
        "grant_id": "SCOPE-GRANT-OVERBROAD",
        "authorization": {"approved_scope": "robot_queue_submission"},
        "source": {"requested_scope": "protocol_draft"},
    }
    with pytest.raises(ValueError, match="Invalid SCOPE grant"):
        export_pcs_bundle(
            AKTARecord(record),
            tmp_path,
            decision=d,
            scope_grant=overbroad_grant,
            validate=True,
        )


def test_scope_order_fixture_is_monotonic() -> None:
    order = json.loads((FIXTURES / "scope_scope_order.json").read_text(encoding="utf-8"))["scope_order"]
    ranks = [scope_rank(s) for s in order]
    assert ranks == sorted(ranks)
    assert len(set(ranks)) == len(ranks)


def test_narrowing_pairs_subset_of_loaded_fixture() -> None:
    pairs = load_valid_narrowing_pairs()
    assert ("active_protocol_update", "protocol_draft") in pairs
    assert len(pairs) >= 1
