"""Example PF-Core obligation export from AKTA Record."""

from __future__ import annotations

import json
from pathlib import Path

from akta import AKTAGate, AKTAContext
from adapters.pf_core.export_obligation import build_pf_obligation, export_pf_obligation

ROOT = Path(__file__).resolve().parents[3]


def main() -> None:
    gate = AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")
    decision = gate.evaluate(
        ai_output={"summary": "Prioritize condition B."},
        requested_tool="lab_scheduler.prioritize",
        requested_action="prioritize_next_run",
        context=AKTAContext.from_dict({"evidence_state": "E2_preliminary_signal"}),
        deployment_profile="P2_analysis_assistant",
        domain_overlay="generic_lab_v0",
    )
    record = decision.to_record()
    obligation = build_pf_obligation(record.to_dict())
    print(json.dumps(obligation, indent=2))
    out = export_pf_obligation(record, Path(__file__).parent / "output")
    print(f"Exported to {out}")


if __name__ == "__main__":
    main()
