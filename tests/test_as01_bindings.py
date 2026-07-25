"""AS-01 binding set and VSA digest hardening tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from adapters.vsa.import_report import (
    VSAImportError,
    compute_vsa_bundle_digest,
    import_vsa_report,
    normalize_vsa_bundle,
    resolve_vsa_source,
)
from akta.bindings import build_binding_set, verify_policy_hashes
from akta.errors import AKTAError
from akta.gate import AKTAGate
from akta.hash import hash_object
from akta.records import validate_against_schema

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "as01"


def _load(name: str) -> dict:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def test_binding_set_schema_valid() -> None:
    bindings = build_binding_set(
        decision_id="AKTA-DEC-AS01",
        record_id="AKTA-SAR-AS01",
        policy_hash="sha256:" + "a" * 64,
        tool_registry_hash="sha256:" + "b" * 64,
        requested_tool="analysis.summarize",
        action_class="literature_summary",
        scientific_question={"q": "does X work?"},
        proposed_action={"tool": "analysis.summarize"},
        vsa_bundle=_load("vsa_report_valid.json"),
    )
    validate_against_schema(bindings, "akta_binding_set.schema.json")
    assert bindings["binding_set_version"] == "akta-binding-set-v1"
    assert bindings["vsa_decision_time_bundle_digest"].startswith("sha256:")


def test_binding_set_schema_invalid_missing_required() -> None:
    with pytest.raises(Exception):
        validate_against_schema(
            {"binding_set_version": "akta-binding-set-v1"},
            "akta_binding_set.schema.json",
        )


def test_vsa_bundle_digest_mismatch() -> None:
    report = _load("vsa_report_digest_mismatch.json")
    with pytest.raises(VSAImportError, match="vsa_bundle_digest_mismatch"):
        normalize_vsa_bundle(report, declared_digest=report["declared_digest"])


def test_vsa_missing_digest_require() -> None:
    report = _load("vsa_report_valid.json")
    with pytest.raises(VSAImportError, match="missing_digest"):
        normalize_vsa_bundle(report, require_declared_digest=True)


def test_ambiguous_evidence_refs() -> None:
    ctx = _load("context_ambiguous_refs.json")
    with pytest.raises(VSAImportError, match="ambiguous_evidence_refs"):
        resolve_vsa_source(ctx)


def test_prefer_vsa_bundle_over_report() -> None:
    report = _load("vsa_report_valid.json")
    bundle = normalize_vsa_bundle(report)
    ctx = {
        "vsa_report": {**report, "overall_evidence_strength": "none"},
        "vsa_bundle": bundle,
    }
    resolved = resolve_vsa_source(ctx)
    assert resolved.get("bundle_digest") == bundle["bundle_digest"]


def test_import_attaches_bundle_digest() -> None:
    report = _load("vsa_report_valid.json")
    ctx = import_vsa_report(report)
    assert ctx["vsa_bundle"]["bundle_digest"] == compute_vsa_bundle_digest(ctx["vsa_bundle"])
    assert ctx["vsa_decision_time_bundle_digest"].startswith("sha256:")


def test_stale_policy_hash_errors() -> None:
    stale = _load("stale_policy_hashes.json")
    errors = verify_policy_hashes(
        bindings=stale,
        loaded_policy_hash="sha256:" + "1" * 64,
        loaded_overlay_hash=None,
        loaded_tool_registry_hash="sha256:" + "2" * 64,
    )
    assert any("stale_policy_hash" in e for e in errors)
    assert any("stale_tool_registry_hash" in e for e in errors)


def test_gate_rejects_stale_declared_policy_hashes() -> None:
    gate = AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")
    stale = _load("stale_policy_hashes.json")
    with pytest.raises(AKTAError, match="stale_policy_hash"):
        gate.evaluate(
            ai_output="summarize literature",
            requested_tool="analysis.literature_summary",
            requested_action="summarize",
            context={
                "evidence_state": "E4_internally_consistent_evidence",
                "metadata": {"declared_policy_hashes": stale},
            },
        )


def test_gate_populates_bindings() -> None:
    gate = AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")
    report = _load("vsa_report_valid.json")
    vsa_ctx = import_vsa_report(report)
    decision = gate.evaluate(
        ai_output="summarize literature on topic",
        requested_tool="analysis.literature_summary",
        requested_action="summarize",
        context=vsa_ctx,
    )
    data = decision.to_dict()
    assert "bindings" in data
    validate_against_schema(data["bindings"], "akta_binding_set.schema.json")
    assert data["bindings"]["policy_hash"] == data["policy_hash"]
    assert data["bindings"]["vsa_decision_time_bundle_digest"] == vsa_ctx[
        "vsa_decision_time_bundle_digest"
    ]
    record = decision.to_record(context=vsa_ctx)
    assert record.to_dict()["bindings"]["decision_id"] == data["decision_id"]
    assert record.to_dict()["bindings"]["record_id"] == record.to_dict()["record_id"]


def test_vsa_digest_roundtrip() -> None:
    report = _load("vsa_report_valid.json")
    digest = hash_object(
        {k: v for k, v in normalize_vsa_bundle(report).items() if k != "bundle_digest"}
    )
    bundle = normalize_vsa_bundle(report, declared_digest=digest)
    assert bundle["bundle_digest"] == digest
