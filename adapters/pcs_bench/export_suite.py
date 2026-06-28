"""Export PCS-Bench scenario suite JSONL."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def export_scenario_suite(
    scenarios: list[dict[str, Any]],
    out_path: str | Path,
    *,
    suite_id: str = "akta-pcs-bench-v0.5",
    include_expected: dict[str, dict[str, Any]] | None = None,
) -> Path:
    """Write PCS-Bench consumable JSONL scenario suite."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for scenario in scenarios:
        entry = {
            "suite_id": suite_id,
            "scenario_id": scenario.get("scenario_id"),
            "description": scenario.get("description", ""),
            "inputs": {
                "ai_output": scenario.get("ai_output"),
                "requested_tool": scenario.get("requested_tool"),
                "requested_action": scenario.get("requested_action"),
                "deployment_profile": scenario.get("deployment_profile"),
                "domain_overlay": scenario.get("domain_overlay"),
                "context": scenario.get("context", {}),
            },
        }
        if include_expected and scenario.get("scenario_id") in include_expected:
            entry["expected"] = include_expected[scenario["scenario_id"]]
        lines.append(json.dumps(entry, ensure_ascii=False))
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path


def export_from_jsonl(
    scenarios_path: str | Path,
    out_path: str | Path,
    expected_path: str | Path | None = None,
) -> Path:
    """Convert AKTA bench JSONL to PCS-Bench suite format."""
    scenarios_path = Path(scenarios_path)
    scenarios = [json.loads(line) for line in scenarios_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    expected_map: dict[str, dict[str, Any]] = {}
    if expected_path:
        for line in Path(expected_path).read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                expected_map[row["scenario_id"]] = row
    return export_scenario_suite(scenarios, out_path, include_expected=expected_map or None)
