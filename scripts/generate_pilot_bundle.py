"""Generate frozen pilot bundle under dist/pilot_bundle/ (AKTA v0.8.1)."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
PILOT_OUT_DIR = ROOT / "dist" / "pilot_bundle"


def _load_demo_module():
    import importlib.util

    demo_path = ROOT / "scripts" / "demo_reconstructable_experiment.py"
    spec = importlib.util.spec_from_file_location("demo_reconstructable_experiment", demo_path)
    assert spec is not None and spec.loader is not None
    demo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(demo)
    return demo

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


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def build_quality_report(
    *,
    out_dir: Path,
    adapter_mode: str,
    scope_summary: dict[str, Any],
    trigger: dict[str, Any],
    record: dict[str, Any],
    pcs_dir: Path,
) -> dict[str, Any]:
    """Pilot QA checks: IAL/SAL, tools, hash linkage, adapter_mode."""
    from akta.scope_contract import get_fixture_contract_version

    demo = _load_demo_module()
    _linkage_report = demo._linkage_report
    _summary_contract_checks = demo._summary_contract_checks

    checks: list[dict[str, Any]] = []

    def _check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"field": name, "ok": ok, "detail": detail})

    summary_checks = _summary_contract_checks(scope_summary, trigger)
    _check("summary_contract.all_ok", summary_checks["all_ok"])

    ial = scope_summary.get("identity_assurance_level")
    sal = scope_summary.get("signing_assurance_level")
    _check("summary.identity_assurance_level", bool(ial), str(ial or ""))
    _check("summary.signing_assurance_level", bool(sal), str(sal or ""))

    origin = scope_summary.get("summary_origin")
    simulated = adapter_mode == "simulated" or origin == "akta_simulated"
    _check("adapter_mode.not_simulated", not simulated, adapter_mode)
    _check(
        "summary.not_synthetic_without_provenance",
        origin not in ("akta_simulated", "akta_synthesized"),
        str(origin or "scope_akta_review"),
    )

    allowed = scope_summary.get("allowed_tools")
    blocked = scope_summary.get("blocked_tools")
    _check("summary.allowed_tools", isinstance(allowed, list), f"{len(allowed or [])} tools")
    _check("summary.blocked_tools", isinstance(blocked, list), f"{len(blocked or [])} tools")

    artifact_paths = {
        "01_akta_decision.json": out_dir / "01_akta_decision_pre_grant.json",
        "02_akta_record.json": out_dir / "02_akta_record.json",
        "03_review_trigger.json": out_dir / "03_review_trigger.json",
        "04_scope_review_summary.json": out_dir / "04_scope_review_summary.json",
        "07_scope_grant.json": out_dir / "07_scope_grant.json",
        "10_pcs_bundle": pcs_dir,
    }
    linkage = _linkage_report(artifact_paths)
    _check("linkage.all_linked", linkage["all_linked"])

    manifest_path = pcs_dir / "manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        _check(
            "pcs.manifest.record_hash",
            manifest.get("record_hash") == record.get("record_hash"),
            manifest.get("record_hash", ""),
        )
        required_pcs = {
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
        }
        files = set(manifest.get("files") or [])
        missing = sorted(required_pcs - files)
        _check("pcs.manifest.files", not missing, ", ".join(missing) if missing else "complete")
    else:
        _check("pcs.manifest.present", False, "missing manifest.json")

    contract_version = get_fixture_contract_version()
    _check(
        "scope.fixture_contract_version",
        contract_version == "akta-scope-contract-v0.8.1",
        contract_version,
    )

    return {
        "pilot_bundle_version": "akta-pilot-v0.8.1",
        "adapter_mode": adapter_mode,
        "scope_fixture_contract_version": contract_version,
        "summary_origin": origin,
        "identity_assurance_level": ial,
        "signing_assurance_level": sal,
        "checks": checks,
        "all_ok": all(c["ok"] for c in checks),
    }


def run_pilot_bundle(*, require_live_scope: bool = False) -> int:
    from adapters.scope.client import ADAPTER_MODE_SIMULATED, detect_adapter_mode
    from akta.scope_contract import get_fixture_contract_version, validate_scope_runtime_contract

    adapter_mode = detect_adapter_mode()
    if require_live_scope and adapter_mode == ADAPTER_MODE_SIMULATED:
        print(
            "generate-pilot-bundle: requires live SCOPE (set SCOPE_REPO_PATH or SCOPE_CLI); "
            f"got adapter_mode={adapter_mode}",
            file=sys.stderr,
        )
        return 1

    validate_scope_runtime_contract()

    demo = _load_demo_module()

    out_dir = PILOT_OUT_DIR
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    demo.DEFAULT_OUT_DIR = out_dir
    demo.CROSS_REPO_OUT_DIR = out_dir
    code = demo.run_demo(cross_repo=bool(
        os.environ.get("SCOPE_REPO_PATH") or os.environ.get("SCOPE_CLI")
    ))
    if code != 0:
        return code

    rename_map = {
        "01_akta_decision.json": "01_akta_decision_pre_grant.json",
        "01_akta_decision_after_grant.json": "08_akta_decision_after_grant.json",
        "08_pf_obligation.json": "09_pf_obligation.json",
        "09_pf_trace_certificate.json": "10_pf_trace_certificate.json",
        "10_pcs_bundle": "11_pcs_bundle",
        "11_scientific_memory_import.json": "12_scientific_memory_import.json",
        "12_pcs_bench_report.json": "13_pcs_bench_report.json",
    }
    for old_name, new_name in rename_map.items():
        old_path = out_dir / old_name
        new_path = out_dir / new_name
        if old_path.exists():
            if new_path.exists():
                if new_path.is_dir():
                    shutil.rmtree(new_path)
                else:
                    new_path.unlink()
            old_path.rename(new_path)

    if (out_dir / "README.md").is_file():
        (out_dir / "README.md").unlink()

    pcs_dir = out_dir / "11_pcs_bundle"
    record = json.loads((out_dir / "02_akta_record.json").read_text(encoding="utf-8"))
    trigger = json.loads((out_dir / "03_review_trigger.json").read_text(encoding="utf-8"))
    scope_summary = json.loads((out_dir / "04_scope_review_summary.json").read_text(encoding="utf-8"))

    quality = build_quality_report(
        out_dir=out_dir,
        adapter_mode=adapter_mode,
        scope_summary=scope_summary,
        trigger=trigger,
        record=record,
        pcs_dir=pcs_dir,
    )
    _write_json(out_dir / "14_quality_report.json", quality)

    contract_version = get_fixture_contract_version()
    recon_path = out_dir / "reconstruction_report.md"
    recon_md = recon_path.read_text(encoding="utf-8")
    if "scope fixture contract_version" not in recon_md.lower():
        recon_md += (
            f"\n## SCOPE fixture contract_version\n\n"
            f"- AKTA fixture contract_version: `{contract_version}`\n"
            f"- Pilot bundle version: `akta-pilot-v0.8.1`\n"
            f"- SCOPE adapter mode: `{adapter_mode}`\n"
        )
        recon_path.write_text(recon_md, encoding="utf-8")

    print(f"Pilot bundle written to {out_dir}")
    print(f"Quality report: all_ok={quality['all_ok']}")
    for name in PILOT_ARTIFACTS:
        if not (out_dir / name).exists():
            print(f"  Missing pilot artifact: {name}", file=sys.stderr)
            return 1

    if require_live_scope and not quality["all_ok"]:
        return 1
    return 0


if __name__ == "__main__":
    require_live = "--require-live-scope" in sys.argv
    sys.exit(run_pilot_bundle(require_live_scope=require_live))

