"""Overlay governance tests for production mode (v0.5)."""

from __future__ import annotations

import hashlib
import hmac
import shutil
from pathlib import Path

import pytest
import yaml

from akta import AKTAGate, AKTAContext
from akta.errors import PolicyError
from akta.overlays import DomainOverlay

ROOT = Path(__file__).resolve().parent.parent


def _policy_with_deploy_key(tmp_path: Path, deploy_key: bytes) -> Path:
    policy_dir = tmp_path / "policy"
    shutil.copytree(ROOT / "policy", policy_dir)
    manifest_path = policy_dir / "policy_manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    payload = "|".join(f"{k}:{v}" for k, v in sorted(manifest["files"].items()))
    manifest["signature"]["value"] = hmac.new(deploy_key, payload.encode("utf-8"), hashlib.sha256).hexdigest()
    manifest_path.write_text(yaml.dump(manifest, sort_keys=False), encoding="utf-8")
    return policy_dir


def test_core_reference_overlay_tier() -> None:
    overlay = DomainOverlay.load("generic_lab_v0", ROOT / "overlays")
    assert overlay.tier == "core_reference"


def test_experimental_overlay_refused_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AKTA_PRODUCTION_MODE", "1")
    with pytest.raises(PolicyError, match="Production mode refuses overlay"):
        DomainOverlay.load("biology_v0", ROOT / "overlays")


def test_experimental_overlay_ok_in_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AKTA_PRODUCTION_MODE", raising=False)
    monkeypatch.delenv("AKTA_VERIFY_POLICY", raising=False)
    overlay = DomainOverlay.load("biology_v0", ROOT / "overlays")
    assert overlay.tier == "experimental_domain_overlay"


def test_gate_refuses_experimental_overlay_in_production(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deploy_key = b"production-overlay-gate-test-v0.5"
    policy_dir = _policy_with_deploy_key(tmp_path, deploy_key)
    monkeypatch.setenv("AKTA_PRODUCTION_MODE", "1")
    monkeypatch.setenv("AKTA_POLICY_HMAC_KEY", deploy_key.decode("utf-8"))
    gate = AKTAGate.from_policy_dir(policy_dir, overlays_dir=ROOT / "overlays")
    with pytest.raises(PolicyError, match="Production mode refuses overlay"):
        gate.evaluate(
            ai_output={"summary": "Schedule passage"},
            requested_tool="cell_culture.schedule",
            requested_action="schedule_passage",
            context=AKTAContext.from_dict({"evidence_state": "E4_internally_consistent_evidence"}),
            deployment_profile="P5_review_gated_experimental_planner",
            domain_overlay="biology_v0",
        )


def test_overlay_governance_fields_present() -> None:
    overlays = (
        "generic_lab_v0",
        "materials_v0",
        "computational_science_v0",
        "biology_v0",
        "chemistry_v0",
        "clinical_v0",
    )
    required = ("tier", "maintainer", "review_status", "review_date", "non_certification_statement")
    for name in overlays:
        overlay = DomainOverlay.load(name, ROOT / "overlays")
        for field in required:
            assert overlay.data.get(field), f"{name} missing {field}"


def test_experimental_overlays_not_operational() -> None:
    for name in ("biology_v0", "chemistry_v0", "clinical_v0"):
        overlay = DomainOverlay.load(name, ROOT / "overlays")
        assert overlay.tier == "experimental_domain_overlay"
        assert not overlay.operational
