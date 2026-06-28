"""PCS-Bench harness integration — AKTA scenario runner (v0.6)."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from akta import AKTAGate, AKTAContext

from adapters.pcs_bench.export_suite import export_from_jsonl, export_scenario_suite


def pcs_bench_repo() -> Path | None:
    """Return sibling PCS-Bench repo path when PCS_BENCH_REPO_PATH is set."""
    raw = os.environ.get("PCS_BENCH_REPO_PATH", "").strip()
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_dir() else None


def _try_import_external_runner(repo: Path) -> Any | None:
    """Import an external PCS-Bench runner callable if present."""
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))
    for mod_name, attr in (
        ("pcs_bench.runners.akta", "run_akta_suite"),
        ("pcs_bench.akta_runner", "run_akta_suite"),
        ("runners.akta_gate", "run_suite"),
    ):
        try:
            spec = importlib.util.find_spec(mod_name)
            if spec is None:
                continue
            mod = importlib.import_module(mod_name)
            fn = getattr(mod, attr, None)
            if callable(fn):
                return fn
        except (ImportError, AttributeError, ValueError):
            continue
    return None


def _run_external_cli(
    repo: Path,
    scenarios_path: Path,
    expected_path: Path | None,
    gate: AKTAGate,
) -> dict[str, Any] | None:
    """Invoke external PCS-Bench CLI script when available."""
    for script_rel in (
        "scripts/run_akta_suite.py",
        "scripts/run_pcs_bench.py",
        "bin/run_akta_suite.py",
    ):
        script = repo / script_rel
        if not script.is_file():
            continue
        cmd = [sys.executable, str(script), str(scenarios_path), "--runner", "akta_gate_v0.6"]
        if expected_path:
            cmd.extend(["--expected", str(expected_path)])
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(repo),
            timeout=120,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr or proc.stdout or "PCS-Bench CLI failed")
        stdout = proc.stdout.strip()
        if not stdout:
            raise RuntimeError("PCS-Bench CLI produced no output")
        return json.loads(stdout.splitlines()[-1])
    return None


def run_pcs_bench_suite(
    scenarios_path: str | Path,
    expected_path: str | Path | None = None,
    *,
    gate: AKTAGate | None = None,
    policy_dir: str | Path = "policy",
    overlays_dir: str | Path = "overlays",
) -> dict[str, Any]:
    """Run PCS-Bench suite via external checkout or in-repo AKTABenchScenario runner."""
    scenarios_path = Path(scenarios_path)
    expected_path = Path(expected_path) if expected_path else None
    gate = gate or AKTAGate.from_policy_dir(policy_dir, overlays_dir=overlays_dir)

    repo = pcs_bench_repo()
    if repo is not None:
        external = _try_import_external_runner(repo)
        if external is not None:
            result = external(
                str(scenarios_path),
                expected=str(expected_path) if expected_path else None,
                gate=gate,
            )
            if isinstance(result, dict):
                result.setdefault("runner_mode", "external_import")
                return result

        cli_result = _run_external_cli(repo, scenarios_path, expected_path, gate)
        if cli_result is not None:
            cli_result.setdefault("runner_mode", "external_cli")
            return cli_result

    scenarios = load_scenarios(scenarios_path, expected_path)
    result = run_suite(scenarios, gate)
    result["runner_mode"] = "in_repo"
    return result


@dataclass
class AKTABenchScenario:
    """AKTA scenario class consumable by PCS-Bench runners."""

    scenario_id: str
    inputs: dict[str, Any]
    expected: dict[str, Any] | None = None
    suite_id: str = "akta-pcs-bench-v0.6"
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_jsonl_row(cls, row: dict[str, Any], expected: dict[str, Any] | None = None) -> AKTABenchScenario:
        return cls(
            scenario_id=row["scenario_id"],
            inputs={
                "ai_output": row.get("ai_output"),
                "requested_tool": row["requested_tool"],
                "requested_action": row.get("requested_action", row["requested_tool"]),
                "deployment_profile": row["deployment_profile"],
                "domain_overlay": row.get("domain_overlay"),
                "context": row.get("context", {}),
            },
            expected=expected,
            metadata={"description": row.get("description", "")},
        )

    def run(self, gate: AKTAGate) -> dict[str, Any]:
        """Execute scenario through AKTA gate."""
        decision = gate.evaluate(
            ai_output=self.inputs.get("ai_output", ""),
            requested_tool=self.inputs["requested_tool"],
            requested_action=self.inputs["requested_action"],
            context=AKTAContext.from_dict(self.inputs.get("context", {})),
            deployment_profile=self.inputs["deployment_profile"],
            domain_overlay=self.inputs.get("domain_overlay"),
        )
        d = decision.to_dict()
        result: dict[str, Any] = {
            "scenario_id": self.scenario_id,
            "admissibility": d["admissibility"],
            "scientific_action_type": d["scientific_action_type"],
            "blocked_tools": d.get("blocked_tools", []),
            "allowed_tools": d.get("allowed_tools", []),
            "policy_hash": d.get("policy_hash"),
        }
        if self.expected:
            exp_adm = self.expected.get("admissibility")
            result["passed"] = exp_adm is None or d["admissibility"] == exp_adm
            if self.expected.get("tool_blocked"):
                result["tool_blocked_ok"] = self.expected["tool_blocked"] in d.get("blocked_tools", [])
            if self.expected.get("tool_allowed"):
                result["tool_allowed_ok"] = self.expected["tool_allowed"] in d.get("allowed_tools", [])
        return result

    def to_pcs_bench_entry(self) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "suite_id": self.suite_id,
            "scenario_id": self.scenario_id,
            "description": self.metadata.get("description", ""),
            "inputs": self.inputs,
            "runner": "akta_gate_v0.6",
        }
        if self.expected:
            entry["expected"] = self.expected
        return entry


def load_scenarios(
    scenarios_path: str | Path,
    expected_path: str | Path | None = None,
) -> list[AKTABenchScenario]:
    """Load AKTA bench scenarios as AKTABenchScenario instances."""
    expected_map: dict[str, dict[str, Any]] = {}
    if expected_path:
        for line in Path(expected_path).read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                expected_map[row["scenario_id"]] = row

    scenarios: list[AKTABenchScenario] = []
    for line in Path(scenarios_path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            scenarios.append(
                AKTABenchScenario.from_jsonl_row(row, expected_map.get(row["scenario_id"]))
            )
    return scenarios


def run_suite(
    scenarios: list[AKTABenchScenario],
    gate: AKTAGate,
) -> dict[str, Any]:
    """Run PCS-Bench compatible suite through AKTA gate."""
    results = [s.run(gate) for s in scenarios]
    passed = sum(1 for r in results if r.get("passed", True))
    return {
        "suite_id": scenarios[0].suite_id if scenarios else "akta-pcs-bench-v0.6",
        "total": len(results),
        "passed_count": passed,
        "passed": passed == len(results) and len(results) > 0,
        "results": results,
    }


def export_runner_hook(out_path: str | Path, scenarios_path: str | Path) -> Path:
    """Export suite + runner metadata for PCS-Bench."""
    scenarios = load_scenarios(scenarios_path)
    suite_entries = [s.to_pcs_bench_entry() for s in scenarios]
    export_scenario_suite(
        [{"scenario_id": s.scenario_id, **s.inputs, "description": s.metadata.get("description", "")} for s in scenarios],
        out_path,
    )
    hook_path = Path(out_path).with_suffix(".runner.json")
    hook_path.write_text(
        json.dumps(
            {
                "runner": "akta_gate_v0.6",
                "entrypoint": "adapters.pcs_bench.runner.run_suite",
                "scenario_count": len(scenarios),
                "suite_path": str(out_path),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return hook_path
