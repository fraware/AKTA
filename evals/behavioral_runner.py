"""Behavioral eval runner — assert tool blocked/allowed after grant (v1.0)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from akta import AKTAGate, AKTAContext
from adapters.langgraph.middleware import AKTALangGraphMiddleware

ROOT = Path(__file__).resolve().parent.parent


def run_behavioral_scenario(
    scenario: dict[str, Any],
    *,
    gate: AKTAGate | None = None,
    middleware: AKTALangGraphMiddleware | None = None,
) -> dict[str, Any]:
    gate = gate or AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")
    mw = middleware or AKTALangGraphMiddleware()

    tool = scenario["requested_tool"]
    action = scenario.get("requested_action", tool)
    ctx = scenario.get("context", {})

    pre = mw.evaluate_tool(tool, action, ai_output=scenario.get("ai_output", ""), context=ctx)
    result: dict[str, Any] = {
        "scenario_id": scenario["scenario_id"],
        "pre_grant_admissibility": pre.admissibility,
        "pre_grant_allowed": pre.allowed,
    }

    grant = scenario.get("scope_grant")
    if grant:
        post = mw.retry_with_grant(
            grant, tool, action,
            ai_output=scenario.get("ai_output", ""),
            context=ctx,
        )
        result["post_grant_admissibility"] = post.admissibility
        result["post_grant_allowed"] = post.allowed

        expected_blocked = scenario.get("expect_tool_blocked_after_grant")
        if expected_blocked is not None:
            result["behavioral_ok"] = post.allowed != expected_blocked
        else:
            expected_adm = scenario.get("expected_post_grant_admissibility")
            result["behavioral_ok"] = (
                expected_adm is None or post.admissibility == expected_adm
            )
    else:
        expected_adm = scenario.get("expected_admissibility")
        result["behavioral_ok"] = (
            expected_adm is None or pre.admissibility == expected_adm
        )

    result["passed"] = result.get("behavioral_ok", True)
    return result


def run_behavioral_suite(scenarios_path: Path) -> dict[str, Any]:
    scenarios: list[dict[str, Any]] = []
    for line in scenarios_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            scenarios.append(json.loads(line))

    results = [run_behavioral_scenario(s) for s in scenarios]
    passed = sum(1 for r in results if r.get("passed"))
    return {
        "suite": "behavioral_v1",
        "total": len(results),
        "passed_count": passed,
        "passed": passed == len(results) and len(results) > 0,
        "results": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run AKTA behavioral eval suite")
    parser.add_argument(
        "--scenarios",
        type=Path,
        default=ROOT / "scenarios" / "adversarial_transitions.jsonl",
    )
    parser.add_argument("--out", type=Path, default=ROOT / "evals" / "reports" / "behavioral_v1.json")
    args = parser.parse_args(argv)

    report = run_behavioral_suite(args.scenarios)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "total": report["total"]}, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
