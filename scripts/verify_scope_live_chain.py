"""Verify live SCOPE adapter chain conformance (v0.7).

Usage:
  python scripts/verify_scope_live_chain.py --scope-repo ../SCOPE --mode python-import
  python scripts/verify_scope_live_chain.py --scope-cli scope --mode cli

Fails when python-import or CLI falls back to simulation, SCOPE artifacts are synthetic,
decision lacks decision_id, grant lacks authorization.approved_scope, or PCS export
skips real grant validation.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


def _is_synthetic_packet(packet: dict[str, Any]) -> bool:
    if packet.get("adapter_mode") == "simulated":
        return True
    if not packet.get("packet_id"):
        return True
    if packet.get("packet_mode") in ("trigger_only", "trigger_plus_record") and not packet.get("packet_id"):
        return True
    return False


def _is_synthetic_grant(grant: dict[str, Any]) -> bool:
    if grant.get("adapter_mode") == "simulated":
        return True
    if grant.get("granted_scope") and not (grant.get("authorization") or {}).get("approved_scope"):
        return True
    return False


def _review_required_fixture() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    from akta import AKTAGate, AKTAContext
    from akta.records import AKTARecord

    gate = AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")
    decision = gate.evaluate(
        ai_output={"summary": "Update active protocol threshold."},
        requested_tool="protocol_editor.update_active_protocol",
        requested_action="update_threshold",
        context=AKTAContext.from_dict({
            "evidence_state": "E4_internally_consistent_evidence",
            "validation_status": "V3_preliminary_experimental_support",
        }),
        deployment_profile="P4_protocol_drafting_assistant",
        domain_overlay="generic_lab_v0",
    )
    d = decision.to_dict()
    record = decision.to_record().to_dict()
    record["review_trigger"] = d["review_trigger"]
    return d, record, d["review_trigger"]


def verify_live_scope_chain(
    *,
    mode: str,
    scope_repo: Path | None = None,
    scope_cli: str | None = None,
) -> dict[str, Any]:
    """Run live SCOPE chain and PCS grant validation checks."""
    from adapters.pcs.export_artifact import export_pcs_bundle
    from adapters.scope.client import (
        ADAPTER_MODE_AKTA_REVIEW_CLI,
        ADAPTER_MODE_CLI,
        ADAPTER_MODE_PYTHON_IMPORT,
        ADAPTER_MODE_SIMULATED,
        SCOPE_CLI_MODE_AKTA_REVIEW,
        submit_review_trigger,
    )
    from akta.records import AKTARecord

    report: dict[str, Any] = {
        "mode": mode,
        "passed": False,
        "checks": [],
    }

    if mode == "python-import":
        if scope_repo is None:
            report["error"] = "python-import mode requires --scope-repo or SCOPE_REPO_PATH"
            return report
        if not scope_repo.is_dir():
            report["error"] = f"SCOPE repo not found: {scope_repo}"
            return report
        os.environ["SCOPE_REPO_PATH"] = str(scope_repo.resolve())
        os.environ.pop("SCOPE_CLI", None)
        expected_mode = ADAPTER_MODE_PYTHON_IMPORT
    elif mode == "cli":
        cli = scope_cli or os.environ.get("SCOPE_CLI", "scope")
        os.environ["SCOPE_CLI"] = cli
        os.environ.pop("SCOPE_REPO_PATH", None)
        os.environ.pop("SCOPE_CLI_MODE", None)
        expected_mode = ADAPTER_MODE_CLI
    elif mode == "akta-review":
        cli = scope_cli or os.environ.get("SCOPE_CLI", "scope")
        os.environ["SCOPE_CLI"] = cli
        os.environ["SCOPE_CLI_MODE"] = SCOPE_CLI_MODE_AKTA_REVIEW
        os.environ.pop("SCOPE_REPO_PATH", None)
        expected_mode = ADAPTER_MODE_AKTA_REVIEW_CLI
    else:
        report["error"] = f"Unknown mode: {mode}"
        return report

    decision, record, trigger = _review_required_fixture()
    scope_result = submit_review_trigger(
        trigger,
        record=record,
        grant_scope="protocol_draft",
        reviewer_id="protocol_owner",
    )

    report["adapter_mode"] = scope_result.adapter_mode
    report["checks"].append({
        "name": "adapter_mode_not_simulated",
        "passed": scope_result.adapter_mode == expected_mode,
        "detail": scope_result.adapter_mode,
    })

    if scope_result.adapter_mode == ADAPTER_MODE_SIMULATED:
        report["error"] = "SCOPE adapter fell back to simulated mode"
        return report

    if scope_result.error:
        report["error"] = scope_result.error
        return report

    packet = scope_result.review_packet or {}
    decision_artifact = scope_result.decision or {}
    grant = scope_result.grant or {}

    packet_ok = not _is_synthetic_packet(packet)
    report["checks"].append({
        "name": "packet_not_synthetic",
        "passed": packet_ok,
        "detail": "packet_id present and not simulated",
    })

    decision_id_ok = bool(decision_artifact.get("decision_id"))
    report["checks"].append({
        "name": "decision_has_decision_id",
        "passed": decision_id_ok,
        "detail": decision_artifact.get("decision_id"),
    })

    grant_shape_ok = bool((grant.get("authorization") or {}).get("approved_scope"))
    report["checks"].append({
        "name": "grant_has_authorization_approved_scope",
        "passed": grant_shape_ok,
        "detail": (grant.get("authorization") or {}).get("approved_scope"),
    })

    grant_not_synthetic = not _is_synthetic_grant(grant)
    report["checks"].append({
        "name": "grant_not_synthetic",
        "passed": grant_not_synthetic,
    })

    narrow_ok = False
    overbroad_rejected = False
    narrow_error: str | None = None
    overbroad_error: str | None = None
    try:
        export_pcs_bundle(
            AKTARecord(record),
            ROOT / "dist" / "_scope_live_verify_narrow",
            decision=decision,
            scope_grant=grant,
            validate=True,
        )
        narrow_ok = True
    except ValueError as exc:
        narrow_error = str(exc)

    overbroad_grant = {
        "authorization": {"approved_scope": "robot_queue_submission"},
        "source": {"requested_scope": "active_protocol_update"},
    }
    try:
        export_pcs_bundle(
            AKTARecord(record),
            ROOT / "dist" / "_scope_live_verify_overbroad",
            decision=decision,
            scope_grant=overbroad_grant,
            validate=True,
        )
    except ValueError as exc:
        overbroad_rejected = True
        overbroad_error = str(exc)

    report["checks"].append({
        "name": "pcs_export_accepts_narrow_grant",
        "passed": narrow_ok,
        "detail": narrow_error,
    })
    report["checks"].append({
        "name": "pcs_export_rejects_overbroad_grant",
        "passed": overbroad_rejected,
        "detail": overbroad_error,
    })

    report["passed"] = all(c["passed"] for c in report["checks"])
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify live SCOPE chain conformance (v0.7)")
    parser.add_argument("--scope-repo", type=Path, default=None, help="Path to SCOPE sibling repo")
    parser.add_argument("--scope-cli", type=str, default=None, help="SCOPE CLI command name")
    parser.add_argument(
        "--mode",
        choices=("python-import", "cli", "akta-review"),
        required=True,
        help="SCOPE adapter mode to verify",
    )
    args = parser.parse_args(argv)

    scope_repo = args.scope_repo
    if scope_repo is None and os.environ.get("SCOPE_REPO_PATH"):
        scope_repo = Path(os.environ["SCOPE_REPO_PATH"])

    if args.mode == "python-import" and scope_repo is None:
        sibling = ROOT.parent / "SCOPE"
        if sibling.is_dir():
            scope_repo = sibling

    if args.mode == "python-import" and scope_repo is None:
        print("SKIP: SCOPE repo not available; set --scope-repo or SCOPE_REPO_PATH")
        return 0

    report = verify_live_scope_chain(
        mode=args.mode,
        scope_repo=scope_repo,
        scope_cli=args.scope_cli,
    )
    print(json.dumps(report, indent=2))
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
