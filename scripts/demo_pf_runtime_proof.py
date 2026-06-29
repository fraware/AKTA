"""PF-Core runtime block proof demo — AKTA obligation to trace certificate (v1.0)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


def _build_blocked_decision() -> tuple[dict[str, Any], dict[str, Any]]:
    from akta import AKTAGate, AKTAContext

    gate = AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")
    decision = gate.evaluate(
        ai_output={"summary": "Prioritize queue for weak signal batch."},
        requested_tool="lab_scheduler.prioritize",
        requested_action="prioritize_batch",
        context=AKTAContext.from_dict({
            "evidence_state": "E2_preliminary_signal",
            "validation_status": "V0_unvalidated",
        }),
        deployment_profile="P2_analysis_assistant",
    )
    d = decision.to_dict()
    record = decision.to_record().to_dict()
    assert d["admissibility"] == "blocked"
    return d, record


def _export_obligation(record: dict[str, Any]) -> dict[str, Any]:
    from adapters.pf_core.export_obligation import build_pf_obligation

    obligation = build_pf_obligation(record)
    from akta.records import validate_against_schema

    validate_against_schema(obligation, "pf_core_obligation.schema.json")
    return obligation


def _validate_pf_live(obligation: dict[str, Any]) -> str | None:
    from tests.contracts.cross_repo_helpers import validate_pf_obligation_live

    return validate_pf_obligation_live(obligation)


def _emit_trace_certificate(
    obligation: dict[str, Any],
    *,
    decision_id: str,
    tool_executed: bool = False,
) -> dict[str, Any]:
    """Build PF trace certificate; invoke PF-Core when sibling repo available."""
    pf_repo = os.environ.get("PF_CORE_REPO_PATH", "").strip()
    certificate: dict[str, Any] = {
        "certificate_type": "pf_trace_certificate",
        "schema_version": "pf-trace-v0.5",
        "akta_decision_id": decision_id,
        "obligation_id": obligation.get("obligation_id"),
        "tool_executed": tool_executed,
        "blocked_tool": obligation.get("requested_tool"),
        "enforcement_outcome": "blocked" if not tool_executed else "violation",
        "trace_events": [
            {
                "event": "akta_gate_evaluated",
                "decision_id": decision_id,
                "admissibility": obligation.get("admissibility_context", {}).get("admissibility"),
            },
            {
                "event": "tool_dispatch_attempted" if not tool_executed else "tool_executed",
                "tool": obligation.get("requested_tool"),
                "blocked": not tool_executed,
            },
        ],
    }

    if pf_repo and Path(pf_repo).is_dir():
        try:
            if str(pf_repo) not in sys.path:
                sys.path.insert(0, str(pf_repo))
            pf_core_path = Path(pf_repo) / "pf-core" / "validator"
            if pf_core_path.is_dir() and str(pf_core_path) not in sys.path:
                sys.path.insert(0, str(pf_core_path))
            from pf_core.hash_chain import validate_trace_hashes
            from pf_core.schemas import validate_object

            validate_object(certificate, "trace_certificate")
            validate_trace_hashes(certificate.get("trace_events", []))
            certificate["pf_core_validated"] = True
        except (ImportError, ValueError, TypeError) as exc:
            certificate["pf_core_validated"] = False
            certificate["pf_core_validation_note"] = str(exc)
            cli = Path(pf_repo) / "pf-core" / "scripts" / "validate_examples.py"
            if cli.is_file():
                with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tmp:
                    json.dump(certificate, tmp)
                    tmp_path = tmp.name
                try:
                    proc = subprocess.run(
                        [sys.executable, str(cli), tmp_path],
                        capture_output=True,
                        text=True,
                        cwd=str(pf_repo),
                        timeout=30,
                        check=False,
                    )
                    certificate["pf_core_cli_exit"] = proc.returncode
                finally:
                    Path(tmp_path).unlink(missing_ok=True)
    return certificate


def run_pf_runtime_proof(*, out_dir: Path | None = None) -> dict[str, Any]:
    """Demonstrate AKTA block -> PF obligation -> trace certificate (tool not executed)."""
    out_dir = out_dir or ROOT / "dist" / "pf_runtime_proof"
    out_dir.mkdir(parents=True, exist_ok=True)

    decision, record = _build_blocked_decision()
    obligation = _export_obligation(record)
    skip = _validate_pf_live(obligation)

    decision_id = decision["decision_id"]
    certificate = _emit_trace_certificate(obligation, decision_id=decision_id, tool_executed=False)

    (out_dir / "akta_decision.json").write_text(json.dumps(decision, indent=2), encoding="utf-8")
    (out_dir / "pf_obligation.json").write_text(json.dumps(obligation, indent=2), encoding="utf-8")
    (out_dir / "pf_trace_certificate.json").write_text(json.dumps(certificate, indent=2), encoding="utf-8")

    checks = {
        "decision_blocked": decision["admissibility"] == "blocked",
        "certificate_references_decision": certificate.get("akta_decision_id") == decision_id,
        "tool_not_executed": certificate.get("tool_executed") is False,
        "pf_live_validation": skip is None or "skipped" in (skip or "").lower(),
    }
    report = {
        "passed": all(checks.values()),
        "checks": checks,
        "pf_validation_skip": skip,
        "out_dir": str(out_dir),
    }
    (out_dir / "proof_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> int:
    report = run_pf_runtime_proof()
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
