"""Eval runner for gate-derived public scenarios (reported separately from oracle-independent)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evals.run_scenarios import run_scenario_eval

ROOT = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run public gate-derived scenario eval")
    parser.add_argument(
        "--scenarios",
        type=Path,
        default=ROOT / "scenarios" / "public_100.jsonl",
    )
    parser.add_argument(
        "--expected",
        type=Path,
        default=ROOT / "scenarios" / "public_gate_derived.jsonl",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "evals" / "reports" / "public_gate_derived_eval.json",
    )
    args = parser.parse_args(argv)

    expected_ids = {
        json.loads(line)["scenario_id"]
        for line in args.expected.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    filtered = ROOT / "dist" / "_public_gate_derived_scenarios.jsonl"
    filtered.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for line in args.scenarios.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row["scenario_id"] in expected_ids:
            rows.append(line)
    filtered.write_text("\n".join(rows) + ("\n" if rows else ""), encoding="utf-8")

    report = run_scenario_eval(filtered, args.expected)
    report["suite"] = "public_gate_derived"
    report["label_source_filter"] = "gate_derived"
    stats = report.get("inter_rater_stats") or {}
    report["gate_derived_metrics"] = {
        "total": report.get("total", 0),
        "passed_count": report.get("passed_count", 0),
        "accuracy": report.get("accuracy", 0.0),
        "gate_derived_count": stats.get("gate_derived_count", report.get("total", 0)),
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "suite": "public_gate_derived"}, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
