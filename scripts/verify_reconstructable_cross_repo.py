"""Verify reconstructable cross-repo demo artifacts (AKTA v0.8 release gate)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CROSS_REPO_OUT_DIR = ROOT / "dist" / "reconstructable_cross_repo"
PILOT_OUT_DIR = ROOT / "dist" / "pilot_bundle"

CROSS_REPO_ARTIFACTS = [
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

PILOT_ARTIFACTS = [
    "00_vsa_report.json",
    "01_akta_decision_pre_grant.json",
    "02_akta_record.json",
    "03_review_trigger.json",
    "04_scope_review_summary.json",
    "05_scope_packet.json",
    "06_scope_decision.json",
    "07_scope_grant.json",
    "08_akta_decision_after_grant.json",
    "09_pf_obligation.json",
    "10_pf_trace_certificate.json",
    "11_pcs_bundle",
    "12_scientific_memory_import.json",
    "13_pcs_bench_report.json",
    "14_quality_report.json",
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

SYNTHETIC_WITHOUT_PROVENANCE_ORIGINS = frozenset({"akta_simulated", "akta_synthesized"})


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


def _verify_scope_summary(summary: dict[str, Any], *, pilot_mode: bool) -> list[str]:
    errors: list[str] = []
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

    if pilot_mode:
        adapter_mode = summary.get("adapter_mode")
        if adapter_mode == "simulated":
            errors.append("Pilot mode rejects adapter_mode=simulated in scope summary")
        origin = summary.get("summary_origin")
        if origin in SYNTHETIC_WITHOUT_PROVENANCE_ORIGINS:
            errors.append(
                f"Pilot mode rejects synthetic SCOPE summary without provenance (summary_origin={origin})"
            )
        elif origin not in (None, "akta_synthesized_from_scope_provenance", "scope_akta_review"):
            errors.append(f"Pilot mode rejects unknown summary_origin: {origin}")
        elif origin is None:
            scope_review_paths = ("packet_path", "decision_path", "grant_path")
            if not all(summary.get(field) for field in scope_review_paths):
                if adapter_mode in ("cli", "python-import"):
                    errors.append(
                        "Pilot mode rejects AKTA-synthesized summary without SCOPE provenance "
                        f"(adapter_mode={adapter_mode})"
                    )
                elif adapter_mode not in ("akta-review-cli",):
                    errors.append(
                        "Pilot mode requires real SCOPE summary (scope akta review paths or provenance)"
                    )
    return errors


def _verify_post_grant(out_dir: Path, post_grant_name: str) -> list[str]:
    errors: list[str] = []
    post_grant_path = out_dir / post_grant_name
    if not post_grant_path.is_file():
        return [f"Missing post-grant decision: {post_grant_name}"]
    post_grant = _load_json(post_grant_path)
    admissibility = post_grant.get("admissibility")
    if admissibility in ("allowed", "allowed_with_logging", "draft_only"):
        errors.append(f"Post-grant decision must not silently pass; got {admissibility}")
    if admissibility not in ("blocked", "review_required", "authorization_required"):
        errors.append(f"Unexpected post-grant admissibility: {admissibility}")
    return errors


def _verify_pcs_bundle(pcs_dir: Path, out_dir: Path) -> list[str]:
    errors: list[str] = []
    if not pcs_dir.is_dir():
        return ["Missing PCS bundle directory"]
    for fname in REQUIRED_PCS_FILES:
        if not (pcs_dir / fname).exists():
            errors.append(f"PCS bundle missing: {fname}")
    from adapters.pcs.export_artifact import validate_pcs_bundle

    try:
        validate_pcs_bundle(pcs_dir)
    except ValueError as exc:
        errors.append(f"PCS bundle validation failed: {exc}")
    return errors


def _verify_quality_report(out_dir: Path, *, pilot_mode: bool) -> list[str]:
    if not pilot_mode:
        return []
    errors: list[str] = []
    quality_path = out_dir / "14_quality_report.json"
    if not quality_path.is_file():
        return ["Missing pilot quality report: 14_quality_report.json"]
    quality = _load_json(quality_path)
    if not quality.get("all_ok"):
        errors.append("Pilot quality report all_ok is false")
    for check in quality.get("checks") or []:
        if not check.get("ok"):
            errors.append(
                f"Quality check failed: {check.get('field')} ({check.get('detail', '')})"
            )
    return errors


def _verify_reconstruction_report(recon_path: Path, *, pilot_mode: bool) -> list[str]:
    if not recon_path.is_file():
        return ["Missing reconstruction_report.md"]
    recon = recon_path.read_text(encoding="utf-8")
    errors: list[str] = []
    if "summary.json" not in recon.lower() and "scope_review_summary" not in recon.lower():
        errors.append("reconstruction_report.md must cite summary.json contract")
    if pilot_mode and "contract_version" not in recon.lower():
        errors.append("reconstruction_report.md must cite scope fixture contract_version")
    return errors


def verify(
    out_dir: Path = CROSS_REPO_OUT_DIR,
    *,
    pilot_mode: bool = False,
) -> int:
    errors: list[str] = []

    if not out_dir.is_dir():
        errors.append(f"Missing output directory: {out_dir}")
        _report(errors, out_dir=out_dir, pilot_mode=pilot_mode)
        return 1

    required = PILOT_ARTIFACTS if pilot_mode else CROSS_REPO_ARTIFACTS
    for name in required:
        if not (out_dir / name).exists():
            errors.append(f"Missing artifact: {name}")

    if not pilot_mode:
        errors.extend(_find_simulated_markers(out_dir))

    pcs_dir = out_dir / ("11_pcs_bundle" if pilot_mode else "10_pcs_bundle")
    errors.extend(_verify_pcs_bundle(pcs_dir, out_dir))

    post_grant_name = (
        "08_akta_decision_after_grant.json"
        if pilot_mode
        else "01_akta_decision_after_grant.json"
    )
    errors.extend(_verify_post_grant(out_dir, post_grant_name))

    summary_path = out_dir / "04_scope_review_summary.json"
    if summary_path.is_file():
        summary = _load_json(summary_path)
        errors.extend(_verify_scope_summary(summary, pilot_mode=pilot_mode))

    errors.extend(_verify_quality_report(out_dir, pilot_mode=pilot_mode))
    errors.extend(
        _verify_reconstruction_report(
            out_dir / "reconstruction_report.md",
            pilot_mode=pilot_mode,
        )
    )

    _report(errors, out_dir=out_dir, pilot_mode=pilot_mode)
    return 0 if not errors else 1


def _report(
    errors: list[str],
    *,
    out_dir: Path | None = None,
    pilot_mode: bool = False,
) -> None:
    label = "verify-pilot-bundle" if pilot_mode else "verify-reconstructable-cross-repo"
    if errors:
        print(f"{label}: FAILED")
        for err in errors:
            print(f"  - {err}")
    else:
        target = out_dir or (PILOT_OUT_DIR if pilot_mode else CROSS_REPO_OUT_DIR)
        print(f"{label}: OK ({target})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify reconstructable demo artifacts")
    parser.add_argument(
        "out_dir",
        nargs="?",
        default=None,
        help="Output directory to verify (default depends on mode)",
    )
    parser.add_argument(
        "--pilot-mode",
        action="store_true",
        help="Verify frozen pilot bundle with live SCOPE assurance requirements",
    )
    args = parser.parse_args(argv)

    if args.out_dir:
        target = Path(args.out_dir)
    elif args.pilot_mode:
        target = PILOT_OUT_DIR
    else:
        target = CROSS_REPO_OUT_DIR

    return verify(target, pilot_mode=args.pilot_mode)


if __name__ == "__main__":
    sys.exit(main())
