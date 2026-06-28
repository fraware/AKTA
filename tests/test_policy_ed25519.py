"""Ed25519 policy signing tests (v0.6)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent


pytest.importorskip("cryptography")

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from akta.policy_integrity import (
    ED25519_ALGORITHM,
    sign_manifest_ed25519,
    verify_ed25519_signature,
    verify_policy_integrity,
)


def test_ed25519_sign_and_verify(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    private_key = Ed25519PrivateKey.generate()
    private_bytes = private_key.private_bytes_raw()
    public_bytes = private_key.public_key().public_bytes_raw()

    policy_dir = tmp_path / "policy"
    policy_dir.mkdir()
    (policy_dir / "action_ontology.yaml").write_text("test: true\n", encoding="utf-8")

    from akta.hash import hash_file_content

    manifest = {
        "version": "test",
        "files": {"action_ontology.yaml": hash_file_content("test: true\n")},
    }
    signed = sign_manifest_ed25519(manifest, private_bytes)
    (policy_dir / "policy_manifest.yaml").write_text(yaml.dump(signed), encoding="utf-8")

    import base64
    monkeypatch.setenv("AKTA_POLICY_PUBLIC_KEY", base64.b64encode(public_bytes).decode())
    monkeypatch.delenv("AKTA_PRODUCTION_MODE", raising=False)
    verify_ed25519_signature(signed)
    assert verify_policy_integrity(policy_dir) is True


def test_require_signed_policy_rejects_unsigned(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    policy_dir = tmp_path / "policy"
    policy_dir.mkdir()
    (policy_dir / "action_ontology.yaml").write_text("x: 1\n", encoding="utf-8")
    from akta.hash import hash_file_content

    manifest = {
        "version": "test",
        "files": {"action_ontology.yaml": hash_file_content("x: 1\n")},
    }
    (policy_dir / "policy_manifest.yaml").write_text(yaml.dump(manifest), encoding="utf-8")
    monkeypatch.setenv("AKTA_REQUIRE_SIGNED_POLICY", "1")

    from akta.errors import PolicyError

    with pytest.raises(PolicyError, match="missing signature"):
        verify_policy_integrity(policy_dir)
