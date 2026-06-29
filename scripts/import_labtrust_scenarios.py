"""Import AKTA bench scenarios from a live LabTrust-Gym sibling checkout."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "scenarios" / "labtrust_gym_imported.jsonl"

# Map LabTrust injection strategy types to AKTA evaluation slices.
_STRATEGY_TOOL_MAP: dict[str, tuple[str, str, str]] = {
    "prompt_injection": ("literature_search.query", "search_papers", "P1_literature_hypothesis_assistant"),
    "tool_escalation": ("robot_queue.submit", "submit_batch", "P6_authorized_closed_loop_lab_agent"),
    "tool_misuse": ("lab_scheduler.prioritize", "prioritize", "P5_review_gated_experimental_planner"),
    "collusion": ("experiment_planner.create_run_plan", "create_plan", "P5_review_gated_experimental_planner"),
    "slow_roll_poisoning": ("scientific_memory.import", "import_entry", "P2_analysis_assistant"),
    "identity_rotation": ("protocol_editor.update_active_protocol", "update", "P4_protocol_drafting_assistant"),
    "replay_attempts": ("lab_scheduler.prioritize", "prioritize", "P5_review_gated_experimental_planner"),
    "stealthy_poisoning": ("notebook.run_analysis", "analyze", "P2_analysis_assistant"),
    "delayed_trigger": ("protocol_editor.update_active_protocol", "update", "P4_protocol_drafting_assistant"),
    "comms_flood": ("literature_search.query", "search_papers", "P1_literature_hypothesis_assistant"),
}


def _resolve_labtrust_repo(explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit
    env = os.environ.get("LABTRUST_REPO_PATH", "").strip()
    if env and Path(env).is_dir():
        return Path(env)
    from akta.sibling_repos import discover_sibling

    found = discover_sibling("LABTRUST_REPO_PATH")
    if found is not None:
        return found
    raise FileNotFoundError(
        "LabTrust-Gym repo not found; set LABTRUST_REPO_PATH or pass --labtrust-repo"
    )


def _load_injections(labtrust_repo: Path) -> list[dict[str, Any]]:
    path = labtrust_repo / "policy" / "coordination" / "injections.v0.2.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"Missing LabTrust injections spec: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return list(data.get("injections") or [])


def _load_prompt_scenarios(labtrust_repo: Path) -> list[dict[str, Any]]:
    path = labtrust_repo / "policy" / "golden" / "prompt_injection_scenarios.v0.1.yaml"
    if not path.is_file():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return list(data.get("scenarios") or [])


def _injection_to_akta(injection: dict[str, Any]) -> dict[str, Any]:
    iid = injection["injection_id"]
    strategy = injection.get("strategy_type", "tool_misuse")
    tool, action, profile = _STRATEGY_TOOL_MAP.get(
        strategy,
        ("notebook.run_analysis", "execute", "P2_analysis_assistant"),
    )
    return {
        "scenario_id": f"ltg_{iid.lower().replace('-', '_')}",
        "description": injection.get("success_definition", iid)[:240],
        "source": "labtrust_gym",
        "label_source": "labtrust_gym_import",
        "ai_output": {
            "summary": injection.get("adversary_goal") or injection.get("success_definition", iid),
        },
        "requested_tool": tool,
        "requested_action": action,
        "deployment_profile": profile,
        "context": {"evidence_state": "E3_noisy_or_conflicting_evidence"},
        "labtrust_metadata": {
            "original_id": iid,
            "strategy_type": strategy,
            "hazard_tags": [strategy],
            "expected_outcome": injection.get("containment_definition"),
            "source_file": "policy/coordination/injections.v0.2.yaml",
        },
    }


def _prompt_to_akta(scenario: dict[str, Any]) -> dict[str, Any]:
    sid = scenario["scenario_id"]
    return {
        "scenario_id": f"ltg_pi_{sid.lower().replace('-', '_')}",
        "description": scenario.get("title", sid)[:240],
        "source": "labtrust_gym",
        "label_source": "labtrust_gym_import",
        "ai_output": {"summary": scenario.get("adversarial_string", "")[:500]},
        "requested_tool": "literature_search.query",
        "requested_action": "search_papers",
        "deployment_profile": "P1_literature_hypothesis_assistant",
        "context": {"evidence_state": "E2_preliminary_signal"},
        "labtrust_metadata": {
            "original_id": sid,
            "injection_source": scenario.get("injection_source"),
            "hazard_tags": ["prompt_injection"],
            "source_file": "policy/golden/prompt_injection_scenarios.v0.1.yaml",
        },
    }


def _load_pack_result_scenarios(labtrust_repo: Path) -> list[dict[str, Any]]:
    """Import one scenario per coord pack result directory (real LabTrust run metadata)."""
    base = labtrust_repo / "tests" / "fixtures" / "coord_pack_fixture" / "pack_results"
    if not base.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for results_path in sorted(base.glob("*/results.json")):
        data = json.loads(results_path.read_text(encoding="utf-8"))
        cfg = data.get("config") or {}
        pack_meta = data.get("pack_meta") or data.get("meta") or {}
        injection_id = (
            cfg.get("injection_id")
            or pack_meta.get("injection_id")
            or data.get("injection_id")
        )
        if not injection_id:
            continue
        method_id = (
            cfg.get("coord_method")
            or pack_meta.get("method_id")
            or data.get("method_id")
            or data.get("agent_baseline_id")
            or "unknown_method"
        )
        sid = f"{injection_id}_{method_id}".lower().replace("-", "_")
        rows.append({
            "scenario_id": f"ltg_pack_{sid}",
            "description": f"LabTrust pack result {results_path.parent.name}"[:240],
            "source": "labtrust_gym",
            "label_source": "labtrust_gym_import",
            "ai_output": {"summary": injection_id},
            "requested_tool": "robot_queue.submit",
            "requested_action": "submit_batch",
            "deployment_profile": "P6_authorized_closed_loop_lab_agent",
            "context": {"evidence_state": "E4_internally_consistent_evidence"},
            "labtrust_metadata": {
                "original_id": injection_id,
                "method_id": method_id,
                "hazard_tags": ["coordination_pack"],
                "source_file": str(results_path.relative_to(labtrust_repo)).replace("\\", "/"),
            },
        })
    return rows


def build_scenarios(*, labtrust_repo: Path, min_count: int = 50) -> list[dict[str, Any]]:
    scenarios: list[dict[str, Any]] = []
    seen: set[str] = set()

    for injection in _load_injections(labtrust_repo):
        row = _injection_to_akta(injection)
        if row["scenario_id"] not in seen:
            scenarios.append(row)
            seen.add(row["scenario_id"])

    for prompt in _load_prompt_scenarios(labtrust_repo):
        row = _prompt_to_akta(prompt)
        if row["scenario_id"] not in seen:
            scenarios.append(row)
            seen.add(row["scenario_id"])

    for pack_row in _load_pack_result_scenarios(labtrust_repo):
        if pack_row["scenario_id"] not in seen:
            scenarios.append(pack_row)
            seen.add(pack_row["scenario_id"])

    if len(scenarios) < min_count:
        raise ValueError(
            f"LabTrust import produced {len(scenarios)} scenarios; need at least {min_count}"
        )
    return scenarios


def import_labtrust_scenarios(
    *,
    labtrust_repo: Path,
    out_path: Path = DEFAULT_OUT,
    min_count: int = 50,
    dry_run: bool = False,
) -> dict[str, Any]:
    scenarios = build_scenarios(labtrust_repo=labtrust_repo, min_count=min_count)
    report = {
        "labtrust_repo": str(labtrust_repo.resolve()),
        "scenario_count": len(scenarios),
        "out_path": str(out_path),
        "dry_run": dry_run,
    }
    if not dry_run:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        lines = [json.dumps(s, ensure_ascii=False) for s in scenarios]
        out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import LabTrust-Gym scenarios into AKTA bench JSONL")
    parser.add_argument("--labtrust-repo", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--min-count", type=int, default=50)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    try:
        repo = _resolve_labtrust_repo(args.labtrust_repo)
        report = import_labtrust_scenarios(
            labtrust_repo=repo,
            out_path=args.out,
            min_count=args.min_count,
            dry_run=args.dry_run,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, indent=2))
        return 1

    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
