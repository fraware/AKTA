"""P1-18: signed release evidence report coverage."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load_report_module():
    path = ROOT / "scripts" / "build_release_evidence_report.py"
    spec = importlib.util.spec_from_file_location("build_release_evidence_report", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_release_evidence_report_contains_required_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _load_report_module()
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
    monkeypatch.delenv("AKTA_WORKFLOW_RUN_ID", raising=False)
    monkeypatch.delenv("AKTA_RELEASE_EVIDENCE_HMAC_KEY", raising=False)
    monkeypatch.delenv("AKTA_POLICY_HMAC_KEY", raising=False)
    monkeypatch.delenv("AKTA_RELEASE_EVIDENCE_SIGNING_KEY", raising=False)
    monkeypatch.delenv("AKTA_POLICY_SIGNING_KEY", raising=False)

    report = mod.build_release_evidence_report(
        test_results={"commands": [{"cmd": "pytest", "ok": True}]},
        sign=False,
    )
    assert report["report_type"] == "akta_release_evidence_v2"
    assert report["verification_status"] == "unverified"
    assert report.get("unverified_reason")
    assert report["workflow_run_ids"]["absent"] is True

    component = report["component_hashes"]
    assert "akta_commit" in component
    assert "contract_wheel_sha256" in component
    assert "scope_commit" in component

    assert isinstance(report["sibling_shas"], dict)
    assert "SCOPE" in report["sibling_shas"] or report["sibling_shas"]

    assert report["schema_hashes"]
    assert report["vocabulary_hashes"]
    assert report["authorization_manifest_hash"]
    assert report["trust_registry_hashes"] or report["trust_manifest_hashes"]
    assert report["test_commands_results"]["commands"][0]["cmd"] == "pytest"
    assert "codeql" in report
    assert "dependency_audit" in report
    assert "sbom" in report
    assert "empirical_status" in report
    assert report["empirical_status"]["empirical_complete"] is False
    assert isinstance(report["known_limitations"], list)
    assert report["known_limitations"]
    assert report["report_hash"].startswith("sha256:")


def test_release_evidence_verified_when_run_id_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _load_report_module()
    monkeypatch.setenv("GITHUB_RUN_ID", "123456789")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    report = mod.build_release_evidence_report(sign=False)
    assert report["verification_status"] == "verified"
    assert report["workflow_run_ids"]["primary_run_id"] == "123456789"
    assert report.get("unverified_reason") is None


def test_release_evidence_report_hmac_signature_roundtrip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _load_report_module()
    monkeypatch.setenv("GITHUB_RUN_ID", "42")
    key = b"release-evidence-test-hmac-key"
    report = mod.build_release_evidence_report(sign=True, hmac_key=key)
    assert (report.get("signature") or {}).get("algorithm") == "HMAC-SHA256"
    assert (report.get("signature") or {}).get("value")
    mod.verify_release_evidence_signature(report, hmac_key=key)

    tampered = dict(report)
    tampered["signature"] = dict(report["signature"])
    tampered["signature"]["value"] = "0" * 64
    with pytest.raises(ValueError, match="HMAC signature verification failed"):
        mod.verify_release_evidence_signature(tampered, hmac_key=key)


def test_release_evidence_cli_writes_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mod = _load_report_module()
    out = tmp_path / "release_evidence.json"
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
    monkeypatch.delenv("AKTA_WORKFLOW_RUN_ID", raising=False)
    rc = mod.main(["--out", str(out), "--no-sign"])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["verification_status"] == "unverified"
    assert payload["report_hash"].startswith("sha256:")
