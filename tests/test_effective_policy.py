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
    from akta.effective_policy import MANDATORY_RELEASE_INPUTS

    manifest = build_effective_policy_manifest(ROOT / "policy", overlays_dir=ROOT / "overlays")
    assert manifest["manifest_version"] == "akta-effective-policy-v1.2"
    assert manifest["effective_policy_hash"].startswith("sha256:")
    assert manifest["manifest_hash"].startswith("sha256:")
    assert "action_ontology.yaml" in manifest["files"]
    assert "default_tool_registry.yaml" in manifest["files"]
    assert "scope_grant_override_rules.yaml" in manifest["files"]
    assert "release_keys.yaml" in manifest["files"]
    assert "shared_contracts_pin.json" in manifest["files"]
    assert "scope_grant_issuer_registry.yaml" in manifest["files"]
    assert "release_pins.yaml" in manifest["files"]
    assert "runtime_capability_mapping.yaml" in manifest["files"]
    assert "overlays" in manifest["overlay_registry"]
    assert manifest["shared_contracts"]["package_version"]
    assert manifest["schema_hashes"]
    assert manifest["registry_hashes"]
    assert manifest["missing_optional_inputs"] == []
    assert manifest["missing_mandatory_inputs"] == []
    for name in MANDATORY_RELEASE_INPUTS:
        assert name not in manifest["missing_optional_inputs"]
        assert name in manifest["files"]


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
    assert "schema_hashes" in d["policy"]
    assert d["policy"].get("shared_contract_release_hash")
    assert d["policy"].get("issuer_registry_hash")
    assert d["policy"].get("compatibility_manifest_hash")

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


def test_mandatory_release_inputs_not_optional(tmp_path: Path) -> None:
    from akta.effective_policy import MANDATORY_RELEASE_INPUTS, build_effective_policy_manifest

    policy_dir = tmp_path / "policy"
    policy_dir.mkdir()
    (policy_dir / "action_ontology.yaml").write_text("v: 1\n", encoding="utf-8")
    manifest = build_effective_policy_manifest(policy_dir, strict_mandatory=False)
    for name in MANDATORY_RELEASE_INPUTS:
        assert name in manifest["missing_mandatory_inputs"]
        assert name not in manifest["missing_optional_inputs"]
    assert "action_ontology.yaml" not in manifest["missing_optional_inputs"]


def test_production_rejects_missing_mandatory_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from akta.effective_policy import build_effective_policy_manifest

    policy_dir = tmp_path / "policy"
    policy_dir.mkdir()
    (policy_dir / "action_ontology.yaml").write_text("v: 1\n", encoding="utf-8")
    monkeypatch.setenv("AKTA_PRODUCTION_MODE", "1")
    monkeypatch.delenv("AKTA_REQUIRE_SIGNED_POLICY", raising=False)
    with pytest.raises(PolicyError, match="missing mandatory release inputs"):
        build_effective_policy_manifest(policy_dir)


def test_production_requires_signed_stored_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from akta.effective_policy import (
        require_effective_policy_integrity,
        write_effective_policy_manifest,
    )

    policy_dir = tmp_path / "policy"
    policy_dir.mkdir()
    for name in (
        "shared_contracts_pin.json",
        "scope_compatibility_manifest.json",
    ):
        if name.endswith(".json"):
            (policy_dir / name).write_text("{}\n", encoding="utf-8")
    for name in (
        "scope_grant_issuer_registry.yaml",
        "scope_status_attestation_registry.yaml",
        "scope_policy_manifest_signer_registry.yaml",
        "release_pins.yaml",
        "runtime_capability_mapping.yaml",
    ):
        (policy_dir / name).write_text("version: t\n", encoding="utf-8")

    # Unsigned stored manifest is insufficient in production.
    write_effective_policy_manifest(policy_dir, sign=False)
    monkeypatch.setenv("AKTA_PRODUCTION_MODE", "1")
    monkeypatch.setenv("AKTA_POLICY_HMAC_KEY", "production-effective-test-key")
    with pytest.raises(PolicyError, match="missing signature|insufficient for production"):
        require_effective_policy_integrity(policy_dir)


def test_production_accepts_signed_stored_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from akta.effective_policy import (
        require_effective_policy_integrity,
        write_effective_policy_manifest,
    )

    policy_dir = tmp_path / "policy"
    policy_dir.mkdir()
    (policy_dir / "shared_contracts_pin.json").write_text("{}\n", encoding="utf-8")
    (policy_dir / "scope_compatibility_manifest.json").write_text("{}\n", encoding="utf-8")
    for name in (
        "scope_grant_issuer_registry.yaml",
        "scope_status_attestation_registry.yaml",
        "scope_policy_manifest_signer_registry.yaml",
        "release_pins.yaml",
        "runtime_capability_mapping.yaml",
    ):
        (policy_dir / name).write_text("version: t\n", encoding="utf-8")

    deploy_key = b"production-effective-signed-key"
    write_effective_policy_manifest(
        policy_dir,
        integrity_mode="deployment_hmac_attested",
        hmac_key=deploy_key,
        sign=True,
    )
    monkeypatch.setenv("AKTA_PRODUCTION_MODE", "1")
    monkeypatch.setenv("AKTA_POLICY_HMAC_KEY", deploy_key.decode("utf-8"))
    stored = require_effective_policy_integrity(
        policy_dir, integrity_mode="deployment_hmac_attested"
    )
    assert (stored.get("signature") or {}).get("algorithm") == "HMAC-SHA256"
    assert (stored.get("signature") or {}).get("value")


def test_production_rejects_recompute_without_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from akta.effective_policy import verify_effective_policy_manifest

    policy_dir = tmp_path / "policy"
    policy_dir.mkdir()
    (policy_dir / "shared_contracts_pin.json").write_text("{}\n", encoding="utf-8")
    (policy_dir / "scope_compatibility_manifest.json").write_text("{}\n", encoding="utf-8")
    for name in (
        "scope_grant_issuer_registry.yaml",
        "scope_status_attestation_registry.yaml",
        "scope_policy_manifest_signer_registry.yaml",
        "release_pins.yaml",
        "runtime_capability_mapping.yaml",
    ):
        (policy_dir / name).write_text("version: t\n", encoding="utf-8")

    monkeypatch.setenv("AKTA_PRODUCTION_MODE", "1")
    monkeypatch.setenv("AKTA_POLICY_HMAC_KEY", "k")
    result = verify_effective_policy_manifest(policy_dir)
    assert not result["ok"]
    assert any("insufficient for production" in e for e in result["errors"])
