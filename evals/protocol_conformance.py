"""Protocol-conformance suite entrypoint (directive §8.1).

Distinct from the empirical-impact benchmark (`evals/empirical_impact.py`).
Uses policy-conformance fixtures / expected decisions — not human ground truth.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evals.run_scenarios import run_scenario_eval

ROOT = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AKTA protocol-conformance suite")
    parser.add_argument(
        "--scenarios",
        default=str(ROOT / "scenarios" / "canonical_5.jsonl"),
    )
    parser.add_argument(
        "--expected",
        default=str(ROOT / "scenarios" / "expected_decisions.jsonl"),
    )
    parser.add_argument(
        "--out",
        default=str(ROOT / "evals" / "reports" / "protocol_conformance.json"),
    )
    args = parser.parse_args(argv)
    report = run_scenario_eval(args.scenarios, args.expected, ROOT / "policy", ROOT / "overlays")
    report["suite"] = "protocol_conformance"
    report["ground_truth_source"] = "policy_expected_decisions"
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"suite": "protocol_conformance", "accuracy": report.get("accuracy"), "out": args.out}))
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
