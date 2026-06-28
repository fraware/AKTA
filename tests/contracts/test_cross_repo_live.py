"""Optional live cross-repo validation (PF-Core, PCS-Core)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from akta import AKTAGate, AKTAContext
from adapters.pcs.export_artifact import export_pcs_bundle, validate_pcs_bundle
from adapters.pf_core.export_obligation import build_pf_obligation
from tests.contracts.cross_repo_helpers import (
    pf_core_repo,
    pcs_core_repo,
    validate_pf_obligation_live,
    validate_pcs_bundle_live,
)

ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture
def gate() -> AKTAGate:
    return AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")


@pytest.mark.integration
def test_pf_core_live_validation(gate: AKTAGate) -> None:
    if pf_core_repo() is None:
        pytest.skip("PF_CORE_REPO_PATH not set")

    decision = gate.evaluate(
        ai_output={"summary": "Update protocol."},
        requested_tool="protocol_editor.update_active_protocol",
        requested_action="update_threshold",
        context=AKTAContext.from_dict({"evidence_state": "E4_internally_consistent_evidence"}),
        deployment_profile="P4_protocol_drafting_assistant",
    )
    obligation = build_pf_obligation(decision.to_record().to_dict(), decision_id=decision.to_dict()["decision_id"])
    skip_reason = validate_pf_obligation_live(obligation)
    if skip_reason and "not found" in skip_reason.lower():
        pytest.skip(skip_reason)


@pytest.mark.integration
def test_pcs_core_live_validation(gate: AKTAGate, tmp_path: Path) -> None:
    if pcs_core_repo() is None:
        pytest.skip("PCS_CORE_REPO_PATH not set")

    decision = gate.evaluate(
        ai_output={"summary": "Analyze."},
        requested_tool="notebook.run_analysis",
        requested_action="analyze",
        context=AKTAContext.from_dict({"evidence_state": "E3_noisy_or_conflicting_evidence"}),
        deployment_profile="P2_analysis_assistant",
    )
    record = decision.to_record().to_dict()
    export_pcs_bundle(record, tmp_path, decision=decision.to_dict(), validate=True)
    validate_pcs_bundle(tmp_path)
    skip_reason = validate_pcs_bundle_live(tmp_path)
    if skip_reason and "not found" in skip_reason.lower():
        pytest.skip(skip_reason)
