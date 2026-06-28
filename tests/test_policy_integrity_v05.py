"""Tests for production vs dev policy integrity (v0.5)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from akta.errors import PolicyError
from akta.policy_integrity import verify_policy_integrity

ROOT = Path(__file__).resolve().parent.parent


def test_dev_mode_verifies_with_dev_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AKTA_PRODUCTION_MODE", raising=False)
    monkeypatch.delenv("AKTA_VERIFY_POLICY", raising=False)
    assert verify_policy_integrity(ROOT / "policy") is True


def test_production_requires_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    shutil.copytree(ROOT / "policy", tmp_path / "policy")
    (tmp_path / "policy" / "policy_manifest.yaml").unlink()
    monkeypatch.setenv("AKTA_PRODUCTION_MODE", "1")
    with pytest.raises(PolicyError, match="no policy_manifest"):
        verify_policy_integrity(tmp_path / "policy")


def test_production_rejects_dev_hmac_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    shutil.copytree(ROOT / "policy", tmp_path / "policy")
    monkeypatch.setenv("AKTA_PRODUCTION_MODE", "1")
    monkeypatch.setenv("AKTA_POLICY_HMAC_KEY", "akta-dev-policy-integrity-v0.4-test-key")
    with pytest.raises(PolicyError, match="rejects in-repo dev HMAC"):
        verify_policy_integrity(tmp_path / "policy")


def test_production_requires_hmac_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    shutil.copytree(ROOT / "policy", tmp_path / "policy")
    monkeypatch.setenv("AKTA_PRODUCTION_MODE", "1")
    monkeypatch.delenv("AKTA_POLICY_HMAC_KEY", raising=False)
    with pytest.raises(PolicyError, match="requires AKTA_POLICY_HMAC_KEY"):
        verify_policy_integrity(tmp_path / "policy")


def test_production_verifies_with_deployment_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import hashlib
    import hmac

    shutil.copytree(ROOT / "policy", tmp_path / "policy")
    manifest_path = tmp_path / "policy" / "policy_manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    deploy_key = b"production-deploy-secret-key-v0.5"
    payload = "|".join(f"{k}:{v}" for k, v in sorted(manifest["files"].items()))
    manifest["signature"]["value"] = hmac.new(deploy_key, payload.encode("utf-8"), hashlib.sha256).hexdigest()
    manifest_path.write_text(yaml.dump(manifest, sort_keys=False), encoding="utf-8")

    monkeypatch.setenv("AKTA_PRODUCTION_MODE", "1")
    monkeypatch.setenv("AKTA_POLICY_HMAC_KEY", deploy_key.decode("utf-8"))
    assert verify_policy_integrity(tmp_path / "policy") is True


def test_tampered_policy_fails_in_production(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import hashlib
    import hmac

    shutil.copytree(ROOT / "policy", tmp_path / "policy")
    deploy_key = b"production-deploy-secret-key-v0.5-tamper"
    manifest_path = tmp_path / "policy" / "policy_manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    payload = "|".join(f"{k}:{v}" for k, v in sorted(manifest["files"].items()))
    manifest["signature"]["value"] = hmac.new(deploy_key, payload.encode("utf-8"), hashlib.sha256).hexdigest()
    manifest_path.write_text(yaml.dump(manifest, sort_keys=False), encoding="utf-8")

    ontology = tmp_path / "policy" / "action_ontology.yaml"
    ontology.write_text(ontology.read_text(encoding="utf-8") + "\n# tamper\n", encoding="utf-8")

    monkeypatch.setenv("AKTA_PRODUCTION_MODE", "1")
    monkeypatch.setenv("AKTA_POLICY_HMAC_KEY", deploy_key.decode("utf-8"))
    with pytest.raises(PolicyError, match="hash mismatch"):
        verify_policy_integrity(tmp_path / "policy")
