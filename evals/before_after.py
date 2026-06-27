"""Before/after comparison utility for AKTA policy or overlay changes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evals.graders import grade_report
from evals.metrics import compute_metrics
from evals.run_scenarios import load_jsonl, run_scenario_eval


def compare_evaluations(
    before_report: dict[str, Any],
    after_report: dict[str, Any],
) -> dict[str, Any]:
    """Compare two scenario evaluation reports."""
    before_by_id = {r["scenario_id"]: r for r in before_report.get("results", [])}
    after_by_id = {r["scenario_id"]: r for r in after_report.get("results", [])}

    improved: list[str] = []
    regressed: list[str] = []
    unchanged: list[str] = []
    deltas: list[dict[str, Any]] = []

    for sid in sorted(set(before_by_id) | set(after_by_id)):
        b = before_by_id.get(sid)
        a = after_by_id.get(sid)
        if not b or not a:
            deltas.append({"scenario_id": sid, "status": "missing", "before": b, "after": a})
            continue

        b_pass = b.get("passed", False)
        a_pass = a.get("passed", False)
        if not b_pass and a_pass:
            improved.append(sid)
            status = "improved"
        elif b_pass and not a_pass:
            regressed.append(sid)
            status = "regressed"
        else:
            unchanged.append(sid)
            status = "unchanged"

        adm_before = b.get("actual", {}).get("admissibility")
        adm_after = a.get("actual", {}).get("admissibility")
        if adm_before != adm_after:
            deltas.append({
                "scenario_id": sid,
                "status": status,
                "admissibility_before": adm_before,
                "admissibility_after": adm_after,
            })

    before_metrics = compute_metrics(before_report)
    after_metrics = compute_metrics(after_report)
    metric_delta = {
        k: after_metrics.get(k, 0) - before_metrics.get(k, 0)
        for k in set(before_metrics) | set(after_metrics)
    }

    return {
        "improved": improved,
        "regressed": regressed,
        "unchanged": unchanged,
        "admissibility_deltas": deltas,
        "before_metrics": before_metrics,
        "after_metrics": after_metrics,
        "metric_delta": metric_delta,
        "net_improvement": len(improved) - len(regressed),
    }


def run_before_after(
    scenarios_path: str | Path,
    expected_path: str | Path,
    policy_dir_before: str | Path,
    policy_dir_after: str | Path,
    overlays_dir: str | Path = "overlays",
) -> dict[str, Any]:
    """Run evaluation before and after a policy change."""
    before = run_scenario_eval(scenarios_path, expected_path, policy_dir_before, overlays_dir)
    after = run_scenario_eval(scenarios_path, expected_path, policy_dir_after, overlays_dir)
    scenarios = load_jsonl(scenarios_path)
    return {
        "comparison": compare_evaluations(before, after),
        "before": grade_report(before, scenarios),
        "after": grade_report(after, scenarios),
    }


def save_comparison_report(report: dict[str, Any], out_path: str | Path) -> Path:
    """Write before/after report to disk."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return out_path
