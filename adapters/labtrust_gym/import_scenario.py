"""LabTrust-Gym scenario import — external JSONL to AKTA scenario format (v0.6)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator


# Minimal compatible LabTrust-Gym scenario schema (when sibling repo unavailable).
LABTRUST_GYM_REQUIRED = frozenset({"scenario_id", "prompt", "tool_calls"})


def _normalize_tool_call(call: dict[str, Any]) -> dict[str, Any]:
    return {
        "requested_tool": call.get("tool") or call.get("requested_tool") or call.get("name"),
        "requested_action": call.get("action") or call.get("requested_action") or "execute",
        "ai_output": call.get("ai_output") or {"summary": call.get("prompt", "")},
        "context": call.get("context") or {},
        "deployment_profile": call.get("deployment_profile", "P2_analysis_assistant"),
        "domain_overlay": call.get("domain_overlay"),
    }


def convert_labtrust_scenario(ltg: dict[str, Any]) -> dict[str, Any]:
    """Convert one LabTrust-Gym scenario dict to AKTA bench scenario shape."""
    scenario_id = ltg.get("scenario_id") or ltg.get("id")
    tool_calls = ltg.get("tool_calls") or ltg.get("steps") or []
    if not tool_calls and ltg.get("requested_tool"):
        tool_calls = [ltg]

    primary = tool_calls[0] if tool_calls else {}
    normalized = _normalize_tool_call(primary if isinstance(primary, dict) else {})

    return {
        "scenario_id": f"ltg_{scenario_id}" if scenario_id else "ltg_unknown",
        "description": ltg.get("description") or ltg.get("prompt", "")[:200],
        "source": "labtrust_gym",
        "ai_output": normalized.get("ai_output") or {"summary": ltg.get("prompt", "")},
        "requested_tool": normalized.get("requested_tool", "unknown.tool"),
        "requested_action": normalized.get("requested_action", "execute"),
        "deployment_profile": normalized.get("deployment_profile", "P2_analysis_assistant"),
        "domain_overlay": normalized.get("domain_overlay"),
        "context": normalized.get("context") or {},
        "labtrust_metadata": {
            "original_id": scenario_id,
            "expected_outcome": ltg.get("expected_outcome"),
            "hazard_tags": ltg.get("hazard_tags") or [],
            "step_count": len(tool_calls),
        },
    }


def import_labtrust_jsonl(path: str | Path) -> list[dict[str, Any]]:
    """Import LabTrust-Gym JSONL file as AKTA scenarios."""
    scenarios: list[dict[str, Any]] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        scenarios.append(convert_labtrust_scenario(raw))
    return scenarios


def export_akta_jsonl(scenarios: list[dict[str, Any]], out_path: str | Path) -> Path:
    """Write AKTA bench JSONL from converted scenarios."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(s, ensure_ascii=False) for s in scenarios]
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path


def iter_labtrust_scenarios(path: str | Path) -> Iterator[dict[str, Any]]:
    for scenario in import_labtrust_jsonl(path):
        yield scenario
