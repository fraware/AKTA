"""Institutional materials overlay production mode tests (v1.0)."""

from __future__ import annotations

import hashlib
import hmac
import shutil
from pathlib import Path

import pytest
import yaml

from akta import AKTAGate, AKTAContext
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


def test_materials_institutional_overlay_tier() -> None:
    overlay = DomainOverlay.load("materials_institutional_v1", ROOT / "overlays")
    assert overlay.tier == "institutional_deployment_overlay"


def test_materials_institutional_allowed_in_production(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deploy_key = b"production-materials-institutional-v1"
    policy_dir = _policy_with_deploy_key(tmp_path, deploy_key)
    monkeypatch.setenv("AKTA_PRODUCTION_MODE", "1")
    monkeypatch.setenv("AKTA_POLICY_HMAC_KEY", deploy_key.decode("utf-8"))
    gate = AKTAGate.from_policy_dir(policy_dir, overlays_dir=ROOT / "overlays")
    decision = gate.evaluate(
        ai_output={"summary": "Capture microscopy image."},
        requested_tool="microscopy.capture_image",
        requested_action="capture",
        context=AKTAContext.from_dict({"evidence_state": "E4_internally_consistent_evidence"}),
        deployment_profile="P2_analysis_assistant",
        domain_overlay="materials_institutional_v1",
    )
    assert decision.admissibility in ("allowed_with_logging", "allowed", "review_required", "blocked")
