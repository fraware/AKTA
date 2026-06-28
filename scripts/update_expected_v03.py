"""One-off helper to enrich expected_decisions.jsonl for v0.3 eval checks."""

from __future__ import annotations

import json
import re
from pathlib import Path

from akta.context import AKTAContext
from akta.gate import AKTAGate
from evals.graders import _FAILURE_CODE_BY_NUMBER
from evals.run_scenarios import load_jsonl

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    gate = AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")
    scenarios = load_jsonl(ROOT / "scenarios" / "public_100.jsonl")
    canonical = load_jsonl(ROOT / "scenarios" / "canonical_5.jsonl")
    all_scenarios = {s["scenario_id"]: s for s in scenarios + canonical}

    expected_path = ROOT / "scenarios" / "expected_decisions.jsonl"
    lines: list[dict] = []
    for line in expected_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        exp = json.loads(line)
        sid = exp["scenario_id"]
        scenario = all_scenarios.get(sid)
        if not scenario:
            lines.append(exp)
            continue

        ctx = AKTAContext.from_dict(scenario.get("context", {}))
        if "vsa_report" in scenario:
            from adapters.vsa.import_report import import_vsa_report

            vsa_ctx = import_vsa_report(scenario["vsa_report"])
            for k, v in vsa_ctx.items():
                if k == "metadata":
                    ctx.metadata.update(v)
                elif hasattr(ctx, k):
                    setattr(ctx, k, v)

        decision = gate.evaluate(
            ai_output=scenario.get("ai_output", ""),
            requested_tool=scenario["requested_tool"],
            requested_action=scenario.get("requested_action", scenario["requested_tool"]),
            context=ctx,
            deployment_profile=scenario["deployment_profile"],
            domain_overlay=scenario.get("domain_overlay"),
        )
        d = decision.to_dict()
        if exp.get("admissibility") in ("review_required", "authorization_required"):
            rt = d.get("review_trigger") or {}
            if rt.get("requested_scope"):
                exp["requested_scope"] = rt["requested_scope"]

        if scenario.get("context", {}).get("handoff_chain") or "_f7_" in sid or "handoff" in sid:
            exp.setdefault("failure_mode", "F7_multi_agent_responsibility_diffusion")
        elif "_f" in sid:
            match = re.search(r"_f(\d+)", sid)
            if match:
                code = _FAILURE_CODE_BY_NUMBER.get(match.group(1))
                if code:
                    exp.setdefault("failure_mode", code)

        if exp.get("admissibility") in ("blocked", "authorization_required"):
            exp.setdefault("severity", "high")
        elif exp.get("admissibility") == "review_required":
            exp.setdefault("severity", "medium")
        else:
            exp.setdefault("severity", "low")

        lines.append(exp)

    expected_path.write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in lines) + "\n",
        encoding="utf-8",
    )
    print(f"Updated {len(lines)} expected entries")

    fix = ROOT / "tests" / "contracts" / "fixtures"
    fix.mkdir(parents=True, exist_ok=True)
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
    trigger = decision.to_dict()["review_trigger"]
    (fix / "scope_review_trigger_v0.3.json").write_text(
        json.dumps(trigger, indent=2), encoding="utf-8"
    )
    record = decision.to_record().to_dict()
    from adapters.pf_core.export_obligation import build_pf_obligation
    from adapters.pcs.export_artifact import build_pcs_manifest

    obligation = build_pf_obligation(record, decision_id=decision.to_dict()["decision_id"])
    pinned_pf = {k: obligation[k] for k in ("obligation_type", "decision", "enforcement_mode", "source")}
    (fix / "pf_obligation_review_required.json").write_text(
        json.dumps(pinned_pf, indent=2), encoding="utf-8"
    )
    record["review_trigger"] = trigger
    manifest = build_pcs_manifest(record, decision.to_dict())
    (fix / "pcs_manifest_v0.3.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("Fixtures written")


if __name__ == "__main__":
    main()
