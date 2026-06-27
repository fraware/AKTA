"""Example PCS artifact bundle export."""

from __future__ import annotations

import json
from pathlib import Path

from akta import AKTAGate, AKTAContext
from adapters.pcs.export_artifact import export_pcs_bundle

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
    out_dir = export_pcs_bundle(record, Path(__file__).parent / "output")
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
