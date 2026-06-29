"""Verify reconstructable cross-repo demo artifacts (AKTA v0.8 release gate)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CROSS_REPO_OUT_DIR = ROOT / "dist" / "reconstructable_cross_repo"

REQUIRED_ARTIFACTS = [
    "00_vsa_report.json",
    "01_akta_decision.json",
    "02_akta_record.json",
    "03_review_trigger.json",
    "04_scope_review_summary.json",
    "05_scope_packet.json",
    "06_scope_decision.json",
    "07_scope_grant.json",
    "08_pf_obligation.json",
    "09_pf_trace_certificate.json",
    "10_pcs_bundle",
    "11_scientific_memory_import.json",
    "12_pcs_bench_report.json",
    "01_akta_decision_after_grant.json",
    "README.md",
    "reconstruction_report.md",
]

REQUIRED_PCS_FILES = [
    "akta_decision.json",
    "akta_record.json",
    "review_trigger.json",
    "scope_review_summary.json",
    "scope_review_packet.json",
    "scope_decision.json",
    "scope_grant.json",
    "pf_obligation.json",
    "vsa_report.json",
    "manifest.json",
]


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _find_simulated_markers(out_dir: Path) -> list[str]:
    violations: list[str] = []
    for path in out_dir.rglob("*.json"):
        try:
            data = _load_json(path)
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("adapter_mode") == "simulated":
            violations.append(f"{path.relative_to(out_dir)}: adapter_mode=simulated")
    return violations


def verify(out_dir: Path = CROSS_REPO_OUT_DIR) -> int:
    errors: list[str] = []

    if not out_dir.is_dir():
        errors.append(f"Missing output directory: {out_dir}")
        _report(errors)
        return 1

    for name in REQUIRED_ARTIFACTS:
        if not (out_dir / name).exists():
            errors.append(f"Missing artifact: {name}")

    simulated = _find_simulated_markers(out_dir)
    errors.extend(simulated)

    post_grant_path = out_dir / "01_akta_decision_after_grant.json"
    if post_grant_path.is_file():
        post_grant = _load_json(post_grant_path)
        admissibility = post_grant.get("admissibility")
        if admissibility in ("allowed", "allowed_with_logging", "draft_only"):
            errors.append(
                f"Post-grant decision must not silently pass; got {admissibility}"
            )
        if admissibility not in ("blocked", "review_required", "authorization_required"):
            errors.append(f"Unexpected post-grant admissibility: {admissibility}")
    else:
        errors.append("Missing post-grant decision: 01_akta_decision_after_grant.json")

    pcs_dir = out_dir / "10_pcs_bundle"
    if pcs_dir.is_dir():
        for fname in REQUIRED_PCS_FILES:
            if not (pcs_dir / fname).exists():
                errors.append(f"PCS bundle missing: {fname}")

        from adapters.pcs.export_artifact import validate_pcs_bundle

        try:
            validate_pcs_bundle(pcs_dir)
        except ValueError as exc:
            errors.append(f"PCS bundle validation failed: {exc}")
    else:
        errors.append("Missing PCS bundle: 10_pcs_bundle")

    summary_path = out_dir / "04_scope_review_summary.json"
    if summary_path.is_file():
        summary = _load_json(summary_path)
        for field in (
            "approved_scope",
            "requested_scope",
            "identity_assurance_level",
            "signing_assurance_level",
        ):
            if not summary.get(field):
                errors.append(f"SCOPE summary missing required field: {field}")
        if not isinstance(summary.get("allowed_tools"), list):
            errors.append("SCOPE summary missing allowed_tools list")
        if not isinstance(summary.get("blocked_tools"), list):
            errors.append("SCOPE summary missing blocked_tools list")

    recon_path = out_dir / "reconstruction_report.md"
    if recon_path.is_file():
        recon = recon_path.read_text(encoding="utf-8")
        if "summary.json" not in recon.lower() and "scope_review_summary" not in recon.lower():
            errors.append("reconstruction_report.md must cite summary.json contract")
    else:
        errors.append("Missing reconstruction_report.md")

    _report(errors, out_dir=out_dir)
    return 0 if not errors else 1


def _report(errors: list[str], *, out_dir: Path | None = None) -> None:
    if errors:
        print("verify-reconstructable-cross-repo: FAILED")
        for err in errors:
            print(f"  - {err}")
    else:
        target = out_dir or CROSS_REPO_OUT_DIR
        print(f"verify-reconstructable-cross-repo: OK ({target})")


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else CROSS_REPO_OUT_DIR
    sys.exit(verify(target))
