"""Verify reconstructable cross-repo demo artifacts (AKTA v0.8+ release gate)."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CROSS_REPO_OUT_DIR = ROOT / "dist" / "reconstructable_cross_repo"
PILOT_OUT_DIR = ROOT / "dist" / "pilot_bundle"

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


def verify(out_dir: Path = CROSS_REPO_OUT_DIR, *, pilot_mode: bool = False) -> int:
    errors: list[str] = []
    if pilot_mode:
        required = list(PILOT_ARTIFACTS)
        post_grant_name = "08_akta_decision_after_grant.json"
        pcs_dir_name = "11_pcs_bundle"
    else:
        required = list(REQUIRED_ARTIFACTS)
        post_grant_name = "01_akta_decision_after_grant.json"
        pcs_dir_name = "10_pcs_bundle"

    if not out_dir.is_dir():
        errors.append(f"Missing output directory: {out_dir}")
        _report(errors, pilot_mode=pilot_mode)
        return 1

    for name in required:
        if not (out_dir / name).exists():
            errors.append(f"Missing artifact: {name}")

    simulated = _find_simulated_markers(out_dir)
    errors.extend(simulated)

    post_grant_path = out_dir / post_grant_name
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
        errors.append(f"Missing post-grant decision: {post_grant_name}")

    pcs_dir = out_dir / pcs_dir_name
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
        errors.append(f"Missing PCS bundle: {pcs_dir_name}")

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
        if pilot_mode:
            if summary.get("adapter_mode") == "simulated":
                errors.append("Pilot mode rejects simulated SCOPE adapter in summary")
            ial = summary.get("identity_assurance_level")
            sal = summary.get("signing_assurance_level")
            if not ial or not str(ial).startswith("IAL"):
                errors.append(f"Pilot mode requires identity_assurance_level; got {ial!r}")
            if not sal or not str(sal).startswith("SAL"):
                errors.append(f"Pilot mode requires signing_assurance_level; got {sal!r}")
    else:
        errors.append("Missing scope review summary: 04_scope_review_summary.json")

    recon_path = out_dir / "reconstruction_report.md"
    if recon_path.is_file():
        recon = recon_path.read_text(encoding="utf-8")
        if "summary.json" not in recon.lower() and "scope_review_summary" not in recon.lower():
            errors.append("reconstruction_report.md must cite summary.json contract")
    else:
        errors.append("Missing reconstruction_report.md")

    if pilot_mode:
        quality_path = out_dir / "14_quality_report.json"
        if quality_path.is_file():
            quality = _load_json(quality_path)
            if not quality.get("all_ok") and not quality.get("all_checks_passed"):
                errors.append("14_quality_report.json reports all_checks_passed=false")
        else:
            errors.append("Missing pilot quality report: 14_quality_report.json")

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


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def build_hash_manifest(out_dir: Path) -> dict[str, str]:
    manifest: dict[str, str] = {}
    for path in sorted(out_dir.rglob("*")):
        if path.is_file():
            rel = str(path.relative_to(out_dir)).replace("\\", "/")
            manifest[rel] = file_sha256(path)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify reconstructable cross-repo artifacts")
    parser.add_argument(
        "out_dir",
        nargs="?",
        type=Path,
        default=None,
        help="Output directory (default: cross-repo or pilot dir)",
    )
    parser.add_argument(
        "--pilot-mode",
        action="store_true",
        help="Verify dist/pilot_bundle with stricter live SCOPE checks",
    )
    parser.add_argument(
        "--hash-manifest",
        action="store_true",
        help="Print sha256 manifest JSON for out_dir and exit",
    )
    args = parser.parse_args(argv)

    out_dir = args.out_dir
    if out_dir is None:
        out_dir = PILOT_OUT_DIR if args.pilot_mode else CROSS_REPO_OUT_DIR

    if args.hash_manifest:
        if not out_dir.is_dir():
            print(json.dumps({"error": f"Missing directory: {out_dir}"}, indent=2))
            return 1
        print(json.dumps(build_hash_manifest(out_dir), indent=2, sort_keys=True))
        return 0

    return verify(out_dir, pilot_mode=args.pilot_mode)


if __name__ == "__main__":
    raise SystemExit(main())
