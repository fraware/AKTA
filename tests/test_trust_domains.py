"""AKTA 1.1 WS3: separate trust domains; reviewer keys are not grant issuers."""

from __future__ import annotations

from pathlib import Path

from akta.trust_store import (
    GRANT_ISSUER_REGISTRY_NAME,
    MANIFEST_SIGNER_REGISTRY_NAME,
    REVIEWER_DECISION_REGISTRY_NAME,
    STATUS_ATTESTATION_REGISTRY_NAME,
    build_trust_store,
    generate_test_keypair,
    institutional_registry_is_empty,
    load_reviewer_decision_registry,
    resolve_grant_issuer_trust_store,
    resolve_manifest_signer_trust_store,
    resolve_status_attestation_trust_store,
    resolve_trust_store,
)

ROOT = Path(__file__).resolve().parent.parent
POLICY = ROOT / "policy"


def test_policy_trust_domain_registries_exist_and_ship_empty() -> None:
    for name in (
        GRANT_ISSUER_REGISTRY_NAME,
        STATUS_ATTESTATION_REGISTRY_NAME,
        MANIFEST_SIGNER_REGISTRY_NAME,
        REVIEWER_DECISION_REGISTRY_NAME,
    ):
        path = POLICY / name
        assert path.is_file(), name
    assert institutional_registry_is_empty(resolve_grant_issuer_trust_store(require_keys=True))
    assert institutional_registry_is_empty(
        resolve_status_attestation_trust_store(require_keys=True)
    )
    assert institutional_registry_is_empty(
        resolve_manifest_signer_trust_store(require_keys=True)
    )


def test_reviewer_registry_not_auto_merged_into_grant_issuers(
    tmp_path: Path, monkeypatch
) -> None:
    keys = generate_test_keypair(tmp_path / "keys")
    reviewer_path = tmp_path / REVIEWER_DECISION_REGISTRY_NAME
    reviewer_path.write_text(
        "\n".join(
            [
                "version: test-reviewer-v1",
                "default_authorized_artifact_types:",
                "  - reviewer_decision",
                "reviewers:",
                "  reviewer-1:",
                "    key_id: reviewer-1",
                "    status: active",
                "    algorithm: Ed25519",
                "    authorized_artifact_types: [reviewer_decision]",
                "    public_key_pem: |",
                *[f"      {line}" for line in keys["public_key_pem"].splitlines()],
            ]
        ),
        encoding="utf-8",
    )
    # Point policy_dir at tmp so only reviewer file exists there — grant issuer
    # must not pick up reviewer keys even if SCOPE sibling would have.
    monkeypatch.delenv("AKTA_TRUST_STORE_PATH", raising=False)
    monkeypatch.delenv("AKTA_GRANT_ISSUER_REGISTRY", raising=False)
    monkeypatch.delenv("AKTA_ISSUER_KEY_REGISTRY", raising=False)
    monkeypatch.delenv("SCOPE_REPO_PATH", raising=False)

    grant_store = resolve_grant_issuer_trust_store(policy_dir=tmp_path, require_keys=True)
    assert institutional_registry_is_empty(grant_store)

    reviewer = load_reviewer_decision_registry(reviewer_path)
    reviewer_store = build_trust_store(
        reviewer,
        base_dir=tmp_path,
        required_artifact_type="reviewer_decision",
    )
    assert not institutional_registry_is_empty(reviewer_store)
    # Explicit resolve_trust_store alias remains grant-issuer only.
    assert institutional_registry_is_empty(
        resolve_trust_store(policy_dir=tmp_path, require_keys=True)
    )
