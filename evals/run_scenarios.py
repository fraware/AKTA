"""AKTA scenario evaluation runner."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from akta.context import AKTAContext
from akta.gate import AKTAGate


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def run_scenario_eval(
    scenarios_path: str | Path,
    expected_path: str | Path,
    policy_dir: str | Path = "policy",
    overlays_dir: str | Path = "overlays",
) -> dict[str, Any]:
    scenarios = load_jsonl(scenarios_path)
    expected = load_jsonl(expected_path)
    expected_by_id = {e["scenario_id"]: e for e in expected}

    gate = AKTAGate.from_policy_dir(policy_dir, overlays_dir=overlays_dir)
    results: list[dict[str, Any]] = []
    passed_count = 0

    for scenario in scenarios:
        sid = scenario["scenario_id"]
        exp = expected_by_id.get(sid)
        if not exp:
            results.append({"scenario_id": sid, "passed": False, "error": "no expected entry"})
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

        checks = {
            "admissibility": d["admissibility"] == exp["admissibility"],
            "scientific_action_type": d["scientific_action_type"] == exp["scientific_action_type"],
            "responsibility_level": d["responsibility_level"] == exp["responsibility_level"],
            "evidence_state": d["evidence_state"] == exp["evidence_state"],
        }
        if exp.get("validation_status"):
            checks["validation_status"] = d["validation_status"] == exp["validation_status"]
        if exp.get("next_admissible_steps_min"):
            checks["next_admissible_steps"] = (
                len(d.get("next_admissible_steps", [])) >= exp["next_admissible_steps_min"]
            )
        if exp.get("expected_next_admissible_steps"):
            actual_steps = set(d.get("next_admissible_steps", []))
            checks["expected_next_admissible_steps"] = all(
                step in actual_steps for step in exp["expected_next_admissible_steps"]
            )
        if exp.get("requested_scope"):
            trigger = d.get("review_trigger") or {}
            checks["requested_scope"] = trigger.get("requested_scope") == exp["requested_scope"]

        passed = all(checks.values())
        if passed:
            passed_count += 1

        failure_mode = scenario.get("failure_mode") or exp.get("failure_mode")
        severity = scenario.get("severity") or exp.get("severity")

        results.append({
            "scenario_id": sid,
            "passed": passed,
            "checks": checks,
            "failure_mode": failure_mode,
            "severity": severity,
            "expected": exp,
            "actual": {
                "admissibility": d["admissibility"],
                "scientific_action_type": d["scientific_action_type"],
                "responsibility_level": d["responsibility_level"],
                "evidence_state": d["evidence_state"],
                "validation_status": d["validation_status"],
                "requested_scope": (d.get("review_trigger") or {}).get("requested_scope"),
                "review_trigger_id": (d.get("review_trigger") or {}).get("review_trigger_id"),
                "policy_hash": d.get("policy_hash"),
                "tool_registry_hash": d.get("tool_registry_hash"),
                "next_admissible_steps": d.get("next_admissible_steps", []),
            },
        })

    total = len(scenarios)
    report = {
        "passed": passed_count == total,
        "total": total,
        "passed_count": passed_count,
        "accuracy": passed_count / total if total else 0.0,
        "results": results,
    }
    from evals.graders import grade_report
    from evals.metrics import compute_metrics

    graded = grade_report(report, scenarios)
    graded["metrics"] = compute_metrics(graded)
    return graded
