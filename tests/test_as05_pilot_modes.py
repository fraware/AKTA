"""AS-05 pilot mode restriction and shadow isolation tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from akta.gate import AKTAGate
from akta.pilot_workflow import (
    PilotMode,
    evaluate_pilot_gate,
    resolve_pilot_mode,
    shadow_comparison_record,
)
from akta.tool_registry import ToolSpec

ROOT = Path(__file__).resolve().parents[1]


def test_legacy_stage_aliases_map() -> None:
    assert resolve_pilot_mode("stage1_shadow") == PilotMode.PROSPECTIVE_SHADOW
    assert resolve_pilot_mode("stage2_draft_only") == PilotMode.READ_ONLY_SUPPORT
    assert resolve_pilot_mode("stage3_validation") == PilotMode.BOUNDED_EXECUTION


def test_unknown_mode_fail_closed() -> None:
    with pytest.raises(ValueError, match="unknown pilot mode"):
        resolve_pilot_mode("not_a_real_mode")


def test_shadow_isolation_no_operational_influence() -> None:
    gate = AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")
    decision = gate.evaluate(
        ai_output="summarize papers",
        requested_tool="analysis.literature_summary",
        requested_action="summarize",
        context={"evidence_state": "E4_internally_consistent_evidence"},
        pilot_mode="prospective_shadow",
    )
    data = decision.to_dict()
    assert data["pilot_mode"] == "prospective_shadow"
    assert data["shadow"] is True
    assert data["operational_influence"] is False
    # Shadow must not authorize execution side effects.
    assert data.get("operational_influence") is False
    cmp = shadow_comparison_record(akta_decision=data, human_decision="allowed")
    assert cmp["shadow"] is True
    assert cmp["operational_influence"] is False


def test_execution_adjacent_blocks_external_execution() -> None:
    gate = AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")
    decision = gate.evaluate(
        ai_output="run robot",
        requested_tool="lab.robot.execute",
        requested_action="execute",
        context={"evidence_state": "E6_independently_reproduced_evidence"},
        pilot_mode="execution_adjacent",
    )
    data = decision.to_dict()
    assert data["admissibility"] == "blocked"
    assert data["operational_influence"] is False
    assert "pilot_mode" in (data.get("failure") or {}).get("layer", "pilot_mode") or data.get("pilot_mode")


def test_read_only_blocks_mutating() -> None:
    gate = AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")
    decision = gate.evaluate(
        ai_output="update protocol",
        requested_tool="lab.protocol_update",
        requested_action="update",
        context={"evidence_state": "E5_internally_replicated_evidence"},
        pilot_mode="read_only_support",
    )
    assert decision.to_dict()["admissibility"] == "blocked"


def test_bounded_execution_requires_trust() -> None:
    gate = AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")
    decision = gate.evaluate(
        ai_output="execute",
        requested_tool="analysis.literature_summary",
        requested_action="summarize",
        context={"evidence_state": "E4_internally_consistent_evidence"},
        pilot_mode="bounded_execution",
    )
    data = decision.to_dict()
    assert data["admissibility"] == "blocked"
    assert "trust" in (data.get("decision_reason") or "").lower() or "stack_profile" in (
        data.get("decision_reason") or ""
    )


def test_evaluate_pilot_gate_stage_alias_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AKTA_PILOT_STAGE", "stage1_shadow")
    result = evaluate_pilot_gate(requested_tool="analysis.literature_summary")
    assert result.mode == PilotMode.PROSPECTIVE_SHADOW
    assert result.ok


def test_cli_gate_mode_shadow() -> None:
    from akta.cli import main
    import tempfile
    import json

    ctx = ROOT / "tests" / "fixtures" / "as01" / "vsa_report_valid.json"
    # minimal context file
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "decision.json"
        context_path = Path(td) / "context.json"
        context_path.write_text(
            json.dumps({"evidence_state": "E4_internally_consistent_evidence"}),
            encoding="utf-8",
        )
        rc = main(
            [
                "gate",
                "--ai-text",
                "summarize",
                "--tool",
                "analysis.literature_summary",
                "--action",
                "summarize",
                "--context",
                str(context_path),
                "--mode",
                "prospective_shadow",
                "--policy-dir",
                str(ROOT / "policy"),
                "--overlays-dir",
                str(ROOT / "overlays"),
                "--out",
                str(out),
            ]
        )
        assert rc == 0
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["pilot_mode"] == "prospective_shadow"
        assert data["operational_influence"] is False
