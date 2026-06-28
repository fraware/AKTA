"""Policy integrity mode tests (v0.7)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent

pytest.importorskip("cryptography")

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from akta.errors import PolicyError
from akta.policy_integrity import sign_manifest_ed25519, verify_policy_integrity
from akta.policy_signing import (
    INTEGRITY_MODE_DEPLOYMENT_HMAC_ATTESTED,
    INTEGRITY_MODE_DEV_UNSIGNED,
    INTEGRITY_MODE_RELEASE_ED25519_SIGNED,
    verify_policy_bundle_integrity,
)


def _minimal_policy_dir(tmp_path: Path, *, signed_hmac: bool = False, signed_ed25519: bool = False) -> Path:
    policy_dir = tmp_path / "policy"
    policy_dir.mkdir()
    (policy_dir / "action_ontology.yaml").write_text("test: true\n", encoding="utf-8")
    from akta.hash import hash_file_content

    manifest = {
        "version": "test",
        "files": {"action_ontology.yaml": hash_file_content("test: true\n")},
    }
    if signed_ed25519:
        private_key = Ed25519PrivateKey.generate()
        manifest = sign_manifest_ed25519(manifest, private_key.private_bytes_raw())
        public_bytes = private_key.public_key().public_bytes_raw()
        import base64

        registry = {
            "version": "test",
            "keys": [{
                "key_id": manifest["signature"]["key_id"],
                "algorithm": "Ed25519",
                "public_key": base64.b64encode(public_bytes).decode("ascii"),
                "status": "active",
            }],
        }
        (policy_dir / "release_keys.yaml").write_text(yaml.dump(registry), encoding="utf-8")
    elif signed_hmac:
        import hashlib
        import hmac

        key = b"deployment-secret-key"
        payload = "|".join(f"{k}:{v}" for k, v in sorted(manifest["files"].items()))
        sig = hmac.new(key, payload.encode("utf-8"), hashlib.sha256).hexdigest()
        manifest["signature"] = {"algorithm": "HMAC-SHA256", "value": sig}

    if signed_hmac or signed_ed25519:
        (policy_dir / "policy_manifest.yaml").write_text(yaml.dump(manifest), encoding="utf-8")
    return policy_dir


def test_production_mode_refuses_unsigned(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    policy_dir = _minimal_policy_dir(tmp_path)
    monkeypatch.setenv("AKTA_PRODUCTION_MODE", "1")
    with pytest.raises(PolicyError, match="no policy_manifest.yaml|missing signature"):
        verify_policy_bundle_integrity(policy_dir)


def test_require_signed_policy_refuses_hmac_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    policy_dir = _minimal_policy_dir(tmp_path, signed_hmac=True)
    monkeypatch.setenv("AKTA_REQUIRE_SIGNED_POLICY", "1")
    monkeypatch.delenv("AKTA_PRODUCTION_MODE", raising=False)
    with pytest.raises(PolicyError, match="release_ed25519_signed|HMAC-only"):
        verify_policy_bundle_integrity(policy_dir)


def test_verify_policy_accepts_hmac_when_allowed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    policy_dir = _minimal_policy_dir(tmp_path, signed_hmac=True)
    monkeypatch.setenv("AKTA_VERIFY_POLICY", "1")
    monkeypatch.setenv("AKTA_POLICY_HMAC_KEY", "deployment-secret-key")
    monkeypatch.delenv("AKTA_REQUIRE_SIGNED_POLICY", raising=False)
    result = verify_policy_bundle_integrity(policy_dir)
    assert result.integrity_mode == INTEGRITY_MODE_DEPLOYMENT_HMAC_ATTESTED


def test_ed25519_verifies_against_release_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    policy_dir = _minimal_policy_dir(tmp_path, signed_ed25519=True)
    monkeypatch.delenv("AKTA_PRODUCTION_MODE", raising=False)
    result = verify_policy_bundle_integrity(policy_dir)
    assert result.integrity_mode == INTEGRITY_MODE_RELEASE_ED25519_SIGNED


def test_dev_unsigned_outside_production(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    policy_dir = _minimal_policy_dir(tmp_path)
    monkeypatch.delenv("AKTA_PRODUCTION_MODE", raising=False)
    monkeypatch.delenv("AKTA_VERIFY_POLICY", raising=False)
    result = verify_policy_bundle_integrity(policy_dir)
    assert result.integrity_mode == INTEGRITY_MODE_DEV_UNSIGNED
    assert result.verified is False


def test_verify_policy_integrity_compat_bool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    policy_dir = _minimal_policy_dir(tmp_path, signed_hmac=True)
    monkeypatch.setenv("AKTA_POLICY_HMAC_KEY", "deployment-secret-key")
    assert verify_policy_integrity(policy_dir) is True


def test_gate_records_integrity_mode_on_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from akta import AKTAGate, AKTAContext

    monkeypatch.delenv("AKTA_PRODUCTION_MODE", raising=False)
    monkeypatch.delenv("AKTA_VERIFY_POLICY", raising=False)
    monkeypatch.delenv("AKTA_REQUIRE_SIGNED_POLICY", raising=False)

    gate = AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")
    assert gate.policy.integrity_mode in (
        INTEGRITY_MODE_DEV_UNSIGNED,
        INTEGRITY_MODE_DEPLOYMENT_HMAC_ATTESTED,
        INTEGRITY_MODE_RELEASE_ED25519_SIGNED,
    )

    decision = gate.evaluate(
        ai_output={"summary": "Search literature."},
        requested_tool="literature_search.query",
        requested_action="search",
        context=AKTAContext.from_dict({"evidence_state": "E1_anecdotal_or_informal_observation"}),
        deployment_profile="P1_literature_hypothesis_assistant",
    )
    assert decision.to_dict().get("policy_integrity_mode") == gate.policy.integrity_mode
