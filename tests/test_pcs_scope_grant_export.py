"""PCS export grant validation conformance (v0.7)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from adapters.pcs.export_artifact import export_pcs_bundle
from akta import AKTAGate, AKTAContext
from akta.records import AKTARecord

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "scope_grants"


def _review_required_record() -> tuple[dict, dict]:
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
    return d, record


def test_pcs_export_accepts_real_narrow_scope_grant(tmp_path: Path) -> None:
    d, record = _review_required_record()
    grant = json.loads(
        (FIXTURES / "real_scope_grant_narrow_protocol_draft.json").read_text(encoding="utf-8")
    )
    out = export_pcs_bundle(
        AKTARecord(record),
        tmp_path / "real_narrow",
        decision=d,
        scope_grant=grant,
        validate=True,
    )
    exported = json.loads((out / "scope_grant.json").read_text(encoding="utf-8"))
    assert exported["authorization"]["approved_scope"] == "protocol_draft"


def test_pcs_export_rejects_real_overbroad_scope_grant(tmp_path: Path) -> None:
    d, record = _review_required_record()
    grant = json.loads(
        (FIXTURES / "real_scope_grant_overbroad_robot_submission.json").read_text(encoding="utf-8")
    )
    with pytest.raises(ValueError, match="Invalid SCOPE grant"):
        export_pcs_bundle(
            AKTARecord(record),
            tmp_path / "real_overbroad",
            decision=d,
            scope_grant=grant,
            validate=True,
        )


def test_pcs_export_accepts_simulated_narrow_scope_grant(tmp_path: Path) -> None:
    d, record = _review_required_record()
    grant = json.loads(
        (FIXTURES / "simulated_scope_grant_narrow_protocol_draft.json").read_text(encoding="utf-8")
    )
    out = export_pcs_bundle(
        AKTARecord(record),
        tmp_path / "sim_narrow",
        decision=d,
        scope_grant=grant,
        validate=True,
    )
    assert (out / "scope_grant.json").exists()


def test_pcs_export_rejects_simulated_overbroad_scope_grant(tmp_path: Path) -> None:
    d, record = _review_required_record()
    grant = json.loads(
        (FIXTURES / "simulated_scope_grant_overbroad_robot_submission.json").read_text(encoding="utf-8")
    )
    with pytest.raises(ValueError, match="Invalid SCOPE grant"):
        export_pcs_bundle(
            AKTARecord(record),
            tmp_path / "sim_overbroad",
            decision=d,
            scope_grant=grant,
            validate=True,
        )
