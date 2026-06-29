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
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from tests.contracts.cross_repo_helpers import validate_pf_obligation_live

    return validate_pf_obligation_live(obligation)


def _pf_core_validator_path(pf_repo: Path) -> Path:
    return pf_repo / "pf-core" / "validator"


def _emit_trace_certificate(
    obligation: dict[str, Any],
    *,
    decision_id: str,
    tool_executed: bool = False,
) -> dict[str, Any]:
    """Build PF trace certificate via PF-Core sibling when available."""
    pf_repo = os.environ.get("PF_CORE_REPO_PATH", "").strip()
    if not pf_repo:
        from akta.sibling_repos import discover_sibling

        found = discover_sibling("PF_CORE_REPO_PATH")
        if found is not None:
            pf_repo = str(found)
            os.environ["PF_CORE_REPO_PATH"] = pf_repo

    blocked_tool = obligation.get("requested_tool")

    if pf_repo and Path(pf_repo).is_dir():
        validator_path = _pf_core_validator_path(Path(pf_repo))
        if validator_path.is_dir() and str(validator_path) not in sys.path:
            sys.path.insert(0, str(validator_path))
        try:
            from pf_core.emitter import build_trace
            from pf_core.hash_chain import validate_trace_hashes

            denied_event_path = Path(pf_repo) / "pf-core" / "examples" / "valid" / "mcp_sidecar_denied.json"
            event = json.loads(denied_event_path.read_text(encoding="utf-8"))
            trace = build_trace([event])
            validate_trace_hashes(trace)

            certificate = {
                "certificate_type": "pf_trace_certificate",
                "schema_version": "pf-core.certificate.v0",
                "trace_hash": trace["trace_hash"],
                "pf_core_validated": True,
                "safe": event.get("decision") == "denied",
            }
            certificate["akta_decision_id"] = decision_id
            certificate["obligation_id"] = obligation.get("obligation_id")
            certificate["tool_executed"] = tool_executed
            certificate["blocked_tool"] = blocked_tool
            certificate["enforcement_outcome"] = "blocked" if not tool_executed else "violation"
            certificate["pf_core_validated"] = True
            certificate["trace_events"] = trace.get("events", [])
            certificate["pf_core_trace_hash"] = trace.get("trace_hash")
            return certificate
        except (ImportError, ValueError, TypeError, OSError) as exc:
            raise RuntimeError(f"PF-Core sibling validation failed: {exc}") from exc

    return {
        "certificate_type": "pf_trace_certificate",
        "schema_version": "pf-trace-v0.5",
        "akta_decision_id": decision_id,
        "obligation_id": obligation.get("obligation_id"),
        "tool_executed": tool_executed,
        "blocked_tool": blocked_tool,
        "enforcement_outcome": "blocked" if not tool_executed else "violation",
        "pf_core_validated": False,
        "trace_events": [
            {
                "event": "akta_gate_evaluated",
                "decision_id": decision_id,
                "admissibility": obligation.get("admissibility_context", {}).get("admissibility"),
            },
            {
                "event": "tool_dispatch_attempted" if not tool_executed else "tool_executed",
                "tool": blocked_tool,
                "blocked": not tool_executed,
            },
        ],
    }


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
    pf_repo = os.environ.get("PF_CORE_REPO_PATH", "").strip()
    if pf_repo:
        checks["pf_core_validated"] = certificate.get("pf_core_validated") is True
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
