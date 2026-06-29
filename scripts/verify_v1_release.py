"""Unified v1.0 release verification orchestrator."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


def _run(cmd: list[str], *, env: dict[str, str] | None = None, optional: bool = False) -> dict[str, Any]:
    merged = {**os.environ, **(env or {})}
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=merged,
        check=False,
    )
    result = {
        "command": " ".join(cmd),
        "returncode": proc.returncode,
        "passed": proc.returncode == 0,
        "stdout_tail": (proc.stdout or "")[-2000:],
        "stderr_tail": (proc.stderr or "")[-2000:],
    }
    if not optional and proc.returncode != 0:
        raise RuntimeError(f"Step failed: {' '.join(cmd)}\n{proc.stderr or proc.stdout}")
    return result


def verify_v1_release(*, skip_ci: bool = False) -> dict[str, Any]:
    report: dict[str, Any] = {"steps": [], "passed": False}

    def step(name: str, fn) -> None:
        try:
            outcome = fn()
            report["steps"].append({"name": name, "passed": True, "detail": outcome})
        except Exception as exc:
            report["steps"].append({"name": name, "passed": False, "error": str(exc)})
            raise

    if not skip_ci:
        step("make_ci", lambda: _run(["make", "ci"] if os.name != "nt" else ["python", "-m", "pytest", "tests/", "-q", "--tb=no"]))

    scope_repo = os.environ.get("SCOPE_REPO_PATH", "")
    if scope_repo:
        for mode in ("python-import",):
            step(
                f"scope_live_{mode}",
                lambda m=mode: _run(
                    [sys.executable, "scripts/verify_scope_live_chain.py", "--mode", m, "--scope-repo", scope_repo],
                    optional=False,
                ),
            )
        step("strict_contract", lambda: _run(
            [sys.executable, "-c", "from akta.scope_contract import validate_scope_runtime_contract; validate_scope_runtime_contract(strict=True)"],
            env={"AKTA_STRICT_SCOPE_CONTRACT": "1", "SCOPE_REPO_PATH": scope_repo},
        ))
        step("demo_pilot_bundle", lambda: _run([sys.executable, "scripts/generate_pilot_bundle.py"]))
        step("verify_pilot_bundle", lambda: _run(
            [sys.executable, "scripts/verify_reconstructable_cross_repo.py", "--pilot-mode"],
        ))
    else:
        report["steps"].append({"name": "scope_live", "passed": True, "skipped": "SCOPE_REPO_PATH not set"})

    for script, name in (
        ("scripts/demo_pf_runtime_proof.py", "pf_runtime_proof"),
    ):
        step(name, lambda s=script: _run([sys.executable, s], optional=True))

    step("pcs_core_ingest", lambda: _run(
        [sys.executable, "-m", "pytest", "tests/contracts/test_pcs_core_live_ingest.py", "-v"],
        optional=True,
    ))
    step("memory_roundtrip", lambda: _run(
        [sys.executable, "-m", "pytest", "tests/contracts/test_scientific_memory_roundtrip.py", "-v"],
        optional=True,
    ))
    step("eval_bench_v1", lambda: _run(
        [sys.executable, "-m", "pytest", "tests/test_eval_bench_v1.py", "-v"],
        optional=False,
    ))
    step("behavioral_smoke", lambda: _run(
        [sys.executable, "evals/behavioral_runner.py", "--scenarios", "scenarios/adversarial_transitions.jsonl"],
        optional=True,
    ))

    report["passed"] = all(s.get("passed", False) or s.get("skipped") for s in report["steps"])
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify AKTA v1.0 release readiness")
    parser.add_argument("--skip-ci", action="store_true")
    parser.add_argument("--out", type=Path, default=ROOT / "evals" / "reports" / "verify_v1_release.json")
    args = parser.parse_args(argv)

    try:
        report = verify_v1_release(skip_ci=args.skip_ci)
    except RuntimeError as exc:
        report = {"passed": False, "error": str(exc)}
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "steps": len(report.get("steps", []))}, indent=2))
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
