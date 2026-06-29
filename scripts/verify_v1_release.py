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


def _run(
    cmd: list[str],
    *,
    env: dict[str, str] | None = None,
    optional: bool = False,
    require_repo: str | None = None,
) -> dict[str, Any]:
    merged = {**os.environ, **(env or {})}
    if require_repo and not merged.get(require_repo, "").strip():
        return {
            "command": " ".join(cmd),
            "returncode": 0,
            "passed": True,
            "skipped": f"{require_repo} not set",
        }

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
    from akta.sibling_repos import apply_sibling_env_defaults

    discovered = apply_sibling_env_defaults()
    report: dict[str, Any] = {"steps": [], "passed": False, "sibling_discovery": discovered}

    def step(name: str, fn) -> None:
        try:
            outcome = fn()
            report["steps"].append({"name": name, "passed": True, "detail": outcome})
        except Exception as exc:
            report["steps"].append({"name": name, "passed": False, "error": str(exc)})
            raise

    if not skip_ci:
        if os.name == "nt":
            step("make_ci", lambda: _run([sys.executable, "-m", "pytest", "tests/", "-q", "--tb=no"]))
        else:
            step("make_ci", lambda: _run(["make", "ci"]))

    scope_repo = os.environ.get("SCOPE_REPO_PATH", "")
    if scope_repo:
        for mode in ("python-import", "cli", "akta-review"):
            env = {"SCOPE_REPO_PATH": scope_repo}
            if mode == "cli":
                env["SCOPE_CLI"] = "scope"
            elif mode == "akta-review":
                env["SCOPE_CLI"] = "scope"
                env["SCOPE_CLI_MODE"] = "akta-review"
            step(
                f"scope_live_{mode}",
                lambda m=mode, e=env: _run(
                    [sys.executable, "scripts/verify_scope_live_chain.py", "--mode", m]
                    + (["--scope-repo", scope_repo] if m == "python-import" else []),
                    env=e,
                    optional=(m in ("cli", "akta-review")),
                ),
            )
        step(
            "strict_contract",
            lambda: _run(
                [
                    sys.executable,
                    "-c",
                    "from akta.scope_contract import validate_scope_runtime_contract; "
                    "validate_scope_runtime_contract(strict=True)",
                ],
                env={"AKTA_STRICT_SCOPE_CONTRACT": "1", "SCOPE_REPO_PATH": scope_repo},
            ),
        )
        step("sync_scope_fixtures", lambda: _run(
            [sys.executable, "scripts/sync_scope_contract_fixtures.py", "--scope-repo", scope_repo],
        ))
        step("demo_pilot_bundle", lambda: _run([sys.executable, "scripts/generate_pilot_bundle.py"]))
        step("verify_pilot_bundle", lambda: _run(
            [sys.executable, "scripts/verify_reconstructable_cross_repo.py", "--pilot-mode"],
        ))
        step("strict_cross_repo", lambda: _run(
            [sys.executable, "scripts/demo_reconstructable_experiment.py", "--cross-repo"],
            env={"AKTA_STRICT_SCOPE_CONTRACT": "1", "SCOPE_REPO_PATH": scope_repo},
        ))
    else:
        report["steps"].append({
            "name": "scope_live",
            "passed": False,
            "error": "SCOPE_REPO_PATH not set; live SCOPE gate required for v1.0 release verify",
        })
        raise RuntimeError("SCOPE_REPO_PATH required for verify_v1_release")

    step("pf_runtime_proof", lambda: _run(
        [sys.executable, "scripts/demo_pf_runtime_proof.py"],
        require_repo="PF_CORE_REPO_PATH",
        optional=not os.environ.get("PF_CORE_REPO_PATH"),
    ))
    step("pcs_core_ingest", lambda: _run(
        [sys.executable, "-m", "pytest", "tests/contracts/test_pcs_core_live_ingest.py", "-v", "-m", "integration"],
        require_repo="PCS_CORE_REPO_PATH",
        optional=not os.environ.get("PCS_CORE_REPO_PATH"),
    ))
    step("vsa_live", lambda: _run(
        [sys.executable, "-m", "pytest", "tests/contracts/test_vsa_live_contract.py", "-v", "-m", "integration"],
        require_repo="VSA_REPO_PATH",
        optional=not os.environ.get("VSA_REPO_PATH"),
    ))
    step("memory_roundtrip", lambda: _run(
        [sys.executable, "-m", "pytest", "tests/contracts/test_scientific_memory_roundtrip.py", "-v", "-m", "integration"],
        require_repo="MEMORY_REPO_PATH",
        optional=not os.environ.get("MEMORY_REPO_PATH"),
    ))
    step("pcs_bench_live", lambda: _run(
        [
            sys.executable,
            "-c",
            "from adapters.pcs_bench.runner import run_pcs_bench_suite; "
            "from pathlib import Path; import json; "
            "r=run_pcs_bench_suite('scenarios/canonical_5.jsonl','scenarios/expected_decisions.jsonl'); "
            "Path('evals/reports').mkdir(parents=True, exist_ok=True); "
            "Path('evals/reports/pcs_bench_live.json').write_text(json.dumps(r, indent=2)); "
            "assert r.get('passed'), r",
        ],
        require_repo="PCS_BENCH_REPO_PATH",
        optional=not os.environ.get("PCS_BENCH_REPO_PATH"),
    ))

    if os.name == "nt":
        step("eval_bench_v1", lambda: _run(
            [sys.executable, "-m", "pytest", "tests/test_eval_bench_v1.py", "-v"],
        ))
        step("behavioral_smoke", lambda: _run([sys.executable, "evals/behavioral_runner.py"]))
    else:
        step("eval_bench_v1", lambda: _run(["make", "eval-bench-v1"]))

    report["passed"] = all(
        s.get("passed", False) or s.get("skipped") for s in report["steps"]
    ) and not any(s.get("error") for s in report["steps"])
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify AKTA v1.0 release readiness")
    parser.add_argument("--skip-ci", action="store_true", help="Skip make ci (not for release tags)")
    parser.add_argument("--out", type=Path, default=ROOT / "evals" / "reports" / "verify_v1_release.json")
    args = parser.parse_args(argv)

    try:
        report = verify_v1_release(skip_ci=args.skip_ci)
    except RuntimeError as exc:
        report = {"passed": False, "error": str(exc), "steps": []}

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"passed": report.get("passed"), "steps": len(report.get("steps", []))}, indent=2))
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
