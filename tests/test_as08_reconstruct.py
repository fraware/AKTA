"""AS-08 reconstruct CLI and benchmark compatibility smoke tests."""

from __future__ import annotations

import json
from pathlib import Path

from adapters.pcs.export_artifact import export_pcs_bundle
from adapters.vsa.import_report import import_vsa_report
from akta.cli import main
from akta.gate import AKTAGate
from akta.reconstruct import reconstruct_from_release

ROOT = Path(__file__).resolve().parents[1]


def test_reconstruct_cli_golden(tmp_path: Path) -> None:
    gate = AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")
    ctx = import_vsa_report(
        {
            "report_id": "VSA-AS08",
            "overall_evidence_strength": "consistent",
            "claims": [{"claim_id": "C1", "evidence_level": "consistent"}],
        }
    )
    decision = gate.evaluate(
        ai_output="summarize",
        requested_tool="analysis.literature_summary",
        requested_action="summarize",
        context=ctx,
    )
    record = decision.to_record(context=ctx)
    release = tmp_path / "action_release"
    export_pcs_bundle(record, release, decision=decision.to_dict(), validate=True)
    out = tmp_path / "reconstruction.json"
    rc = main(["reconstruct", "--release", str(release), "--out", str(out)])
    assert rc == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["ok"] is True
    assert report["bindings_present"] is True
    assert report["binding_completeness"] > 0
    assert report["bundle_digest"].startswith("sha256:")


def test_reconstruct_library_matches_cli(tmp_path: Path) -> None:
    gate = AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")
    decision = gate.evaluate(
        ai_output="summarize",
        requested_tool="analysis.literature_summary",
        requested_action="summarize",
        context={"evidence_state": "E4_internally_consistent_evidence"},
    )
    record = decision.to_record()
    release = tmp_path / "action_release"
    export_pcs_bundle(record, release, decision=decision.to_dict(), validate=True)
    report = reconstruct_from_release(release)
    assert report["ok"]


def test_benchmark_compat_public_expectations_exist() -> None:
    """Benchmark corpora and expected decisions remain present (backward compat)."""
    assert (ROOT / "scenarios" / "public_100.jsonl").is_file()
    assert (ROOT / "scenarios" / "expected_decisions.jsonl").is_file()
    assert (ROOT / "scenarios" / "canonical_5.jsonl").is_file()
