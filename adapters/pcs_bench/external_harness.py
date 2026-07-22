"""Shell PCS-Bench sibling repo runner for AKTA release-gate live matrix (v1.0)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from adapters.pcs_bench.runner import pcs_bench_repo, run_pcs_bench_suite


def _pcs_bench_cli(repo: Path) -> list[str] | None:
    """Resolve PCS-Bench CLI entrypoint (installed package or repo module)."""
    for cmd in (
        ["pcs-bench", "run-suite"],
        [sys.executable, "-m", "pcs_bench.cli", "run-suite"],
    ):
        try:
            proc = subprocess.run(
                cmd + ["--help"],
                capture_output=True,
                text=True,
                cwd=str(repo),
                timeout=30,
                check=False,
            )
            if proc.returncode == 0:
                return cmd
        except (OSError, subprocess.TimeoutExpired):
            continue
    script = repo / "scripts" / "run_akta_suite.py"
    if script.is_file():
        return [sys.executable, str(script)]
    return None


def run_external_harness(
    scenarios_path: str | Path,
    expected_path: str | Path | None = None,
    *,
    out_path: str | Path | None = None,
) -> dict[str, Any]:
    """Run PCS-Bench via sibling checkout; fail closed when path set but harness missing."""
    repo = pcs_bench_repo()
    if repo is None:
        report = run_pcs_bench_suite(scenarios_path, expected_path)
        report["harness"] = "in_repo_fallback"
        if out_path:
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            Path(out_path).write_text(json.dumps(report, indent=2), encoding="utf-8")
        return report

    scenarios_path = Path(scenarios_path)
    expected_path = Path(expected_path) if expected_path else None
    cli = _pcs_bench_cli(repo)
    if cli is None:
        report = run_pcs_bench_suite(scenarios_path, expected_path)
        report["harness"] = "import_fallback"
        report["pcs_bench_repo"] = str(repo)
        if out_path:
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            Path(out_path).write_text(json.dumps(report, indent=2), encoding="utf-8")
        return report

    cmd = list(cli) + [str(scenarios_path), "--runner", "akta_gate_v0.6"]
    if expected_path:
        cmd.extend(["--expected", str(expected_path)])
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(repo),
        timeout=300,
        check=False,
        env={**os.environ, "PCS_BENCH_REPO_PATH": str(repo)},
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout or "PCS-Bench external harness failed")

    stdout = (proc.stdout or "").strip()
    if not stdout:
        raise RuntimeError("PCS-Bench external harness produced no output")
    report = json.loads(stdout.splitlines()[-1])
    report.setdefault("harness", "external_cli")
    report["pcs_bench_repo"] = str(repo)
    report.setdefault("passed", report.get("passed_count", 0) == report.get("total", 0))

    if out_path:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    import argparse

    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Run PCS-Bench external harness")
    parser.add_argument(
        "--scenarios",
        type=Path,
        default=root / "scenarios" / "canonical_5.jsonl",
    )
    parser.add_argument(
        "--expected",
        type=Path,
        default=root / "scenarios" / "expected_decisions.jsonl",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=root / "evals" / "reports" / "pcs_bench_live.json",
    )
    args = parser.parse_args(argv)

    report = run_external_harness(args.scenarios, args.expected, out_path=args.out)
    print(json.dumps({"passed": report.get("passed"), "harness": report.get("harness")}, indent=2))
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
