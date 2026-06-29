"""Behavioral eval runner — assert tool blocked/allowed via LangGraph middleware (v1.0)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from adapters.langgraph.middleware import AKTALangGraphMiddleware

ROOT = Path(__file__).resolve().parent.parent


def _run_with_wrap_tool(
    scenario: dict[str, Any],
    *,
    middleware: AKTALangGraphMiddleware,
) -> dict[str, Any]:
    """Execute scenario through middleware.wrap_tool and assert runtime enforcement."""
    executed = {"value": False}

    def _stub_tool(**kwargs: Any) -> dict[str, Any]:
        executed["value"] = True
        return {"ok": True}

    tool = scenario["requested_tool"]
    action = scenario.get("requested_action", tool)
    ctx = scenario.get("context", {})
    profile = scenario.get("deployment_profile", "P2_analysis_assistant")
    middleware.deployment_profile = profile
    middleware.domain_overlay = scenario.get("domain_overlay")
    middleware.reset_state()

    grant = scenario.get("scope_grant")
    ai_output = scenario.get("ai_output", "")
    if grant:
        pre = middleware.evaluate_tool(tool, action, ai_output=ai_output, context=ctx)
        if pre.admissibility == "review_required" and pre.review_trigger:
            middleware.retry_with_grant(grant, tool, action, ai_output=ai_output, context=ctx)
        elif pre.admissibility == "review_required":
            middleware.apply_scope_grant(grant)
        else:
            middleware.apply_scope_grant(grant)

    gated = middleware.wrap_tool(_stub_tool, tool, action)
    runtime_error: str | None = None
    try:
        gated(ai_output=ai_output, context=ctx)
    except (PermissionError, Exception) as exc:
        runtime_error = f"{type(exc).__name__}: {exc}"

    expect_executed = scenario.get("expect_tool_executed")
    if expect_executed is None:
        expected_adm = scenario.get("expected_admissibility")
        pre = middleware.evaluate_tool(tool, action, ai_output=ai_output, context=ctx)
        behavioral_ok = expected_adm is None or pre.admissibility == expected_adm
    else:
        behavioral_ok = executed["value"] == expect_executed

    return {
        "scenario_id": scenario["scenario_id"],
        "tool_executed": executed["value"],
        "expect_tool_executed": expect_executed,
        "runtime_error": runtime_error,
        "behavioral_ok": behavioral_ok,
        "passed": behavioral_ok,
    }


def run_behavioral_scenario(
    scenario: dict[str, Any],
    *,
    middleware: AKTALangGraphMiddleware | None = None,
) -> dict[str, Any]:
    mw = middleware or AKTALangGraphMiddleware(
        policy_dir=str(ROOT / "policy"),
        overlays_dir=str(ROOT / "overlays"),
    )
    return _run_with_wrap_tool(scenario, middleware=mw)


def run_behavioral_suite(scenarios_path: Path) -> dict[str, Any]:
    scenarios: list[dict[str, Any]] = []
    for line in scenarios_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            scenarios.append(json.loads(line))

    results = [run_behavioral_scenario(s) for s in scenarios]
    passed = sum(1 for r in results if r.get("passed"))
    return {
        "suite": "behavioral_v1",
        "scenarios_path": str(scenarios_path),
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
        default=ROOT / "scenarios" / "behavioral_middleware.jsonl",
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
