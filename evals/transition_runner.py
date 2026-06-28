"""Simulate SCOPE narrow grant -> re-gate -> verify tool allow/block."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from akta import AKTAGate, AKTAContext
from adapters.scope.client import submit_review_trigger


def run_transition(
    scenario: dict[str, Any],
    *,
    policy_dir: str | Path = "policy",
    overlays_dir: str | Path = "overlays",
    grant_scope: str | None = None,
) -> dict[str, Any]:
    """Run review_required scenario through SCOPE grant and re-gate."""
    gate = AKTAGate.from_policy_dir(policy_dir, overlays_dir=overlays_dir)
    ctx = AKTAContext.from_dict(scenario.get("context", {}))
    initial = gate.evaluate(
        ai_output=scenario.get("ai_output", ""),
        requested_tool=scenario["requested_tool"],
        requested_action=scenario.get("requested_action", scenario["requested_tool"]),
        context=ctx,
        deployment_profile=scenario.get("deployment_profile", "P2_analysis_assistant"),
        domain_overlay=scenario.get("domain_overlay"),
    )
    result: dict[str, Any] = {
        "scenario_id": scenario.get("scenario_id"),
        "initial_admissibility": initial.admissibility,
        "passed": False,
    }
    if initial.admissibility != "review_required":
        result["error"] = f"Expected review_required, got {initial.admissibility}"
        return result

    trigger = initial.to_dict().get("review_trigger")
    if not trigger:
        result["error"] = "Missing review_trigger"
        return result

    scope_result = submit_review_trigger(trigger, grant_scope=grant_scope)
    result["adapter_mode"] = scope_result.adapter_mode
    if scope_result.error:
        result["scope_error"] = scope_result.error

    follow_up_tool = scenario.get("follow_up_tool", scenario["requested_tool"])
    follow_up_action = scenario.get("follow_up_action", scenario.get("requested_action", follow_up_tool))
    rectx = dict(scenario.get("context", {}))
    rectx.setdefault("metadata", {})
    if scope_result.grant:
        rectx["metadata"]["prior_review_id"] = scope_result.grant.get("grant_id")
        rectx["metadata"]["prior_review_scope"] = scope_result.grant.get("granted_scope")
        rectx["metadata"]["prior_review_expired"] = False
        rectx["metadata"]["prior_review_decision"] = "approved"

    regate = gate.evaluate(
        ai_output=scenario.get("follow_up_ai_output", scenario.get("ai_output", "")),
        requested_tool=follow_up_tool,
        requested_action=follow_up_action,
        context=AKTAContext.from_dict(rectx),
        deployment_profile=scenario.get("deployment_profile", "P2_analysis_assistant"),
        domain_overlay=scenario.get("domain_overlay"),
    )
    result["regate_admissibility"] = regate.admissibility
    result["regate_allowed_tools"] = regate.to_dict().get("allowed_tools", [])
    result["regate_blocked_tools"] = regate.to_dict().get("blocked_tools", [])

    expected = scenario.get("expected_after_grant", {})
    if expected.get("admissibility"):
        result["passed"] = regate.admissibility == expected["admissibility"]
    elif expected.get("tool_allowed"):
        result["passed"] = regate.admissibility in ("allowed", "allowed_with_logging", "draft_only")
    else:
        result["passed"] = regate.admissibility not in ("blocked", "abstain_insufficient_context")
    return result


def run_suite(path: str | Path, **kwargs: Any) -> list[dict[str, Any]]:
    results = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            results.append(run_transition(json.loads(line), **kwargs))
    return results
