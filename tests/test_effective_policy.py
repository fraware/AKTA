"""Effective policy provenance and signed-policy hard-fail tests (PR-1)."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent

pytest.importorskip("cryptography")

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from akta import AKTAContext, AKTAGate
from akta.effective_policy import build_effective_policy_manifest
from akta.errors import PolicyError
from akta.hash import hash_file_content
from akta.policy_integrity import sign_manifest_ed25519
from akta.policy_signing import verify_policy_bundle_integrity


def _minimal_policy_dir(tmp_path: Path, *, signed_ed25519: bool = False) -> Path:
    policy_dir = tmp_path / "policy"
    policy_dir.mkdir()
    (policy_dir / "action_ontology.yaml").write_text("test: true\n", encoding="utf-8")
    manifest = {
        "version": "test",
        "files": {"action_ontology.yaml": hash_file_content("test: true\n")},
    }
    if signed_ed25519:
        private_key = Ed25519PrivateKey.generate()
        manifest = sign_manifest_ed25519(manifest, private_key.private_bytes_raw())
        public_bytes = private_key.public_key().public_bytes_raw()
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
        (policy_dir / "policy_manifest.yaml").write_text(yaml.dump(manifest), encoding="utf-8")
    return policy_dir


def test_require_signed_policy_not_bypassed_by_required_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy_dir = _minimal_policy_dir(tmp_path)
    monkeypatch.setenv("AKTA_REQUIRE_SIGNED_POLICY", "1")
    monkeypatch.delenv("AKTA_PRODUCTION_MODE", raising=False)
    with pytest.raises(PolicyError, match="no policy_manifest|missing signature"):
        verify_policy_bundle_integrity(policy_dir, required=False)


def test_production_mode_not_bypassed_by_required_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy_dir = _minimal_policy_dir(tmp_path)
    monkeypatch.setenv("AKTA_PRODUCTION_MODE", "1")
    monkeypatch.delenv("AKTA_REQUIRE_SIGNED_POLICY", raising=False)
    with pytest.raises(PolicyError, match="no policy_manifest|missing signature"):
        verify_policy_bundle_integrity(policy_dir, required=False)


def test_revoked_release_key_hard_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy_dir = _minimal_policy_dir(tmp_path, signed_ed25519=True)
    registry_path = policy_dir / "release_keys.yaml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    registry["keys"][0]["status"] = "revoked"
    registry_path.write_text(yaml.dump(registry), encoding="utf-8")

    monkeypatch.setenv("AKTA_REQUIRE_SIGNED_POLICY", "1")
    monkeypatch.delenv("AKTA_PRODUCTION_MODE", raising=False)
    with pytest.raises(PolicyError, match="revoked|status="):
        verify_policy_bundle_integrity(policy_dir, required=False)


def test_effective_policy_manifest_covers_core_inputs() -> None:
    manifest = build_effective_policy_manifest(ROOT / "policy", overlays_dir=ROOT / "overlays")
    assert manifest["manifest_version"] == "akta-effective-policy-v1.0"
    assert manifest["effective_policy_hash"].startswith("sha256:")
    assert manifest["manifest_hash"].startswith("sha256:")
    assert "action_ontology.yaml" in manifest["files"]
    assert "default_tool_registry.yaml" in manifest["files"]
    assert "scope_grant_override_rules.yaml" in manifest["files"]
    assert "release_keys.yaml" in manifest["files"]
    assert "overlays" in manifest["overlay_registry"]


def test_decision_and_record_bind_policy_block(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AKTA_PRODUCTION_MODE", raising=False)
    monkeypatch.delenv("AKTA_REQUIRE_SIGNED_POLICY", raising=False)
    monkeypatch.delenv("AKTA_VERIFY_POLICY", raising=False)

    gate = AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")
    decision = gate.evaluate(
        ai_output={"summary": "Search literature."},
        requested_tool="literature_search.query",
        requested_action="search",
        context=AKTAContext.from_dict({"evidence_state": "E1_anecdotal_or_informal_observation"}),
        deployment_profile="P1_literature_hypothesis_assistant",
    )
    d = decision.to_dict()
    assert "policy" in d
    assert d["policy"]["effective_policy_hash"].startswith("sha256:")
    assert d["policy"]["integrity_mode"] == gate.policy.integrity_mode
    assert isinstance(d["policy"]["file_versions"], dict)

    record = decision.to_record().to_dict()
    assert "policy" in record
    assert record["policy"]["effective_policy_hash"] == d["policy"]["effective_policy_hash"]
    assert record["provenance"].get("policy", {}).get("effective_policy_hash") == (
        d["policy"]["effective_policy_hash"]
    )


def test_write_effective_policy_manifest_roundtrip(tmp_path: Path) -> None:
    # Build against real policy; write into temp copy of hashes only via builder path.
    manifest = build_effective_policy_manifest(
        ROOT / "policy",
        overlays_dir=ROOT / "overlays",
        integrity_mode="deployment_hmac_attested",
    )
    out = tmp_path / "effective_policy_manifest.json"
    out.write_text(__import__("json").dumps(manifest, indent=2), encoding="utf-8")
    loaded = __import__("json").loads(out.read_text(encoding="utf-8"))
    assert loaded["effective_policy_hash"] == manifest["effective_policy_hash"]


def test_verify_effective_policy_detects_tamper(tmp_path: Path) -> None:
    from akta.effective_policy import (
        verify_effective_policy_manifest,
        write_effective_policy_manifest,
    )

    policy_dir = tmp_path / "policy"
    policy_dir.mkdir()
    (policy_dir / "action_ontology.yaml").write_text("v: 1\n", encoding="utf-8")
    (policy_dir / "scope_compatibility_manifest.json").write_text(
        '{"manifest_version":"t","akta_package_version":"1.0.0",'
        '"akta_review_contract_version":"x","grant_schema_version":"g",'
        '"capability_envelope_version":"e","summary_contract_version":"s",'
        '"fixture_contract_version":"f"}\n',
        encoding="utf-8",
    )
    write_effective_policy_manifest(policy_dir)
    (policy_dir / "scope_compatibility_manifest.json").write_text(
        '{"manifest_version":"TAMPERED","akta_package_version":"1.0.0",'
        '"akta_review_contract_version":"x","grant_schema_version":"g",'
        '"capability_envelope_version":"e","summary_contract_version":"s",'
        '"fixture_contract_version":"f"}\n',
        encoding="utf-8",
    )
    result = verify_effective_policy_manifest(policy_dir)
    assert not result["ok"]
    assert any("scope_compatibility_manifest" in e for e in result["errors"])
