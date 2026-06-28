"""PCS export validation for simulated and real SCOPE v0.5 grant shapes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from adapters.pcs.export_artifact import export_pcs_bundle
from akta import AKTAGate, AKTAContext
from akta.records import AKTARecord
from akta.scope_contract import (
    _scope_grant_approved_scope,
    _scope_grant_requested_scope,
)

ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"


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


def test_scope_grant_helpers_simulated_shape() -> None:
    grant = {
        "grant_id": "SCOPE-GRANT-SIM",
        "granted_scope": "protocol_draft",
        "requested_scope": "active_protocol_update",
    }
    assert _scope_grant_approved_scope(grant) == "protocol_draft"
    assert _scope_grant_requested_scope(grant, None, None) == "active_protocol_update"


def test_scope_grant_helpers_real_v05_shape() -> None:
    grant = json.loads((FIXTURES / "scope_grant_v0.5_narrow.json").read_text(encoding="utf-8"))
    assert _scope_grant_approved_scope(grant) == "protocol_draft"
    assert _scope_grant_requested_scope(grant, None, None) == "active_protocol_update"


def test_pcs_export_accepts_simulated_grant_shape(tmp_path: Path) -> None:
    d, record = _review_required_record()
    grant = {
        "grant_id": "SCOPE-GRANT-SIM",
        "granted_scope": "protocol_draft",
        "requested_scope": "active_protocol_update",
        "adapter_mode": "simulated",
    }
    out = export_pcs_bundle(
        AKTARecord(record),
        tmp_path / "simulated",
        decision=d,
        scope_grant=grant,
        validate=True,
    )
    exported = json.loads((out / "scope_grant.json").read_text(encoding="utf-8"))
    assert exported == grant


def test_pcs_export_accepts_real_v05_grant_shape(tmp_path: Path) -> None:
    d, record = _review_required_record()
    grant = json.loads((FIXTURES / "scope_grant_v0.5_narrow.json").read_text(encoding="utf-8"))
    out = export_pcs_bundle(
        AKTARecord(record),
        tmp_path / "real_v05",
        decision=d,
        scope_grant=grant,
        validate=True,
    )
    exported = json.loads((out / "scope_grant.json").read_text(encoding="utf-8"))
    assert exported["authorization"]["approved_scope"] == "protocol_draft"
    assert exported["source"]["requested_scope"] == "active_protocol_update"


def test_pcs_export_rejects_overbroad_real_v05_grant(tmp_path: Path) -> None:
    d, record = _review_required_record()
    grant = {
        "authorization": {"approved_scope": "robot_queue_submission"},
        "source": {"requested_scope": "active_protocol_update"},
    }
    with pytest.raises(ValueError, match="Invalid SCOPE grant"):
        export_pcs_bundle(
            AKTARecord(record),
            tmp_path / "bad",
            decision=d,
            scope_grant=grant,
            validate=True,
        )


def test_pcs_export_narrow_active_to_draft_from_trigger_fallback(tmp_path: Path) -> None:
    """Real grant without source.requested_scope falls back to record review_trigger."""
    d, record = _review_required_record()
    grant = {"authorization": {"approved_scope": "protocol_draft"}}
    export_pcs_bundle(
        AKTARecord(record),
        tmp_path / "fallback",
        decision=d,
        scope_grant=grant,
        validate=True,
    )
