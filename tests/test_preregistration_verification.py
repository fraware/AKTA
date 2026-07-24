"""P1-16 preregistration lock verification and amendment schema tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.preregistration_lock import (
    DEFAULT_PREREG,
    PreregistrationLockError,
    assert_not_rewriting_locked_artifact,
    build_signed_amendment,
    compute_content_hash,
    load_locked_preregistration,
    validate_amendment,
    verify_preregistration_artifact,
)

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_PRIV = ROOT / "tests" / "fixtures" / "empirical" / "preregistration_signer.pem"
AMENDMENT_SCHEMA = ROOT / "evals" / "empirical" / "amendment.schema.json"


def test_locked_preregistration_verifies_hash_and_signature() -> None:
    result = verify_preregistration_artifact(DEFAULT_PREREG)
    assert result.ok, result.errors
    assert result.preregistration_id == "akta-empirical-prereg-v1.2.0"
    assert result.content_hash and result.content_hash.startswith("sha256:")
    body = load_locked_preregistration()
    assert body["immutable_signed_artifact"] is True
    assert body["preregistered_at"] == "2026-07-23T16:00:00Z"
    assert body["signature"]["algorithm"] == "Ed25519"
    assert body["signature"]["key_id"] == "akta-empirical-prereg-signer-v1"
    assert body["signature"]["public_key"]
    assert "BEGIN PUBLIC KEY" in body["signature"]["public_verification_key"]
    assert body["amendment_policy"]["artifact_may_be_rewritten"] is False


def test_locked_preregistration_detects_unauthorized_field_change(tmp_path: Path) -> None:
    original = json.loads(DEFAULT_PREREG.read_text(encoding="utf-8"))
    tampered = dict(original)
    tampered["seed"] = "tampered-seed"
    # Keep stale signature/hash so verification fails on both hash and field compare.
    path = tmp_path / "preregistration.json"
    path.write_text(json.dumps(tampered, indent=2) + "\n", encoding="utf-8")

    result = verify_preregistration_artifact(path, expected=original)
    assert result.ok is False
    joined = " ".join(result.errors)
    assert "content_hash mismatch" in joined or "unauthorized field change" in joined


def test_locked_preregistration_detects_signature_forgery(tmp_path: Path) -> None:
    original = json.loads(DEFAULT_PREREG.read_text(encoding="utf-8"))
    forged = dict(original)
    forged["signature"] = dict(original["signature"])
    forged["signature"]["value"] = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=="
    path = tmp_path / "forged.json"
    path.write_text(json.dumps(forged, indent=2) + "\n", encoding="utf-8")
    result = verify_preregistration_artifact(path)
    assert result.ok is False
    assert any("signature" in e.lower() for e in result.errors)


def test_refuse_rewrite_of_locked_artifact() -> None:
    with pytest.raises(PreregistrationLockError, match="refusing to rewrite"):
        assert_not_rewriting_locked_artifact(DEFAULT_PREREG)


def test_harness_never_rewrites_locked_preregistration(tmp_path: Path) -> None:
    from evals.empirical_impact import write_protocol_artifacts

    before = DEFAULT_PREREG.read_bytes()
    paths = write_protocol_artifacts(ROOT / "evals" / "empirical")
    after = DEFAULT_PREREG.read_bytes()
    assert before == after
    assert "preregistration" not in paths
    assert Path(paths["protocol"]).is_file()

    # Writing a copy outside the lock path is allowed only with explicit flag,
    # and still cannot target the locked path.
    with pytest.raises(PreregistrationLockError, match="refusing to rewrite"):
        write_protocol_artifacts(
            ROOT / "evals" / "empirical",
            allow_prereg_write=True,
        )

    copy_paths = write_protocol_artifacts(tmp_path, allow_prereg_write=True)
    assert Path(copy_paths["preregistration"]).is_file()
    assert Path(copy_paths["preregistration"]).resolve() != DEFAULT_PREREG.resolve()


def test_amendment_schema_file_exists_with_required_fields() -> None:
    schema = json.loads(AMENDMENT_SCHEMA.read_text(encoding="utf-8"))
    required = set(schema["required"])
    assert {
        "parent_content_hash",
        "reason",
        "changed_fields",
        "approval",
        "signature",
        "amended_at",
    } <= required


def test_valid_amendment_before_observations() -> None:
    parent = load_locked_preregistration()
    priv = FIXTURE_PRIV.read_bytes()
    amendment = build_signed_amendment(
        parent=parent,
        amendment_id="amd-test-001",
        reason="Increase N after pilot variance estimate",
        changed_fields=["power_analysis.planned_n_scenarios_per_arm"],
        changes={"power_analysis.planned_n_scenarios_per_arm": 600},
        approval={
            "approver_id": "irb-delegate-1",
            "approver_role": "institutional_review",
            "approved_at": "2026-07-23T15:00:00Z",
            "decision": "approved",
        },
        private_key_pem=priv,
        key_id="akta-empirical-prereg-signer-v1",
        amended_at="2026-07-23T15:30:00Z",
    )
    validate_amendment(amendment, parent=parent, observations_started=False)
    assert amendment["parent_content_hash"] == parent["content_hash"]
    assert amendment["amendment_hash"].startswith("sha256:")


def test_amendment_rejected_after_observations_started() -> None:
    parent = load_locked_preregistration()
    priv = FIXTURE_PRIV.read_bytes()
    amendment = build_signed_amendment(
        parent=parent,
        amendment_id="amd-test-002",
        reason="late change",
        changed_fields=["seed"],
        approval={
            "approver_id": "irb-delegate-1",
            "approver_role": "institutional_review",
            "approved_at": "2026-07-23T15:00:00Z",
            "decision": "approved",
        },
        private_key_pem=priv,
        key_id="akta-empirical-prereg-signer-v1",
        amended_at="2026-07-23T15:30:00Z",
    )
    with pytest.raises(PreregistrationLockError, match="after observations"):
        validate_amendment(amendment, parent=parent, observations_started=True)


def test_amendment_rejected_with_wrong_parent_hash() -> None:
    parent = load_locked_preregistration()
    priv = FIXTURE_PRIV.read_bytes()
    amendment = build_signed_amendment(
        parent=parent,
        amendment_id="amd-test-003",
        reason="bad parent",
        changed_fields=["seed"],
        approval={
            "approver_id": "irb-delegate-1",
            "approver_role": "institutional_review",
            "approved_at": "2026-07-23T15:00:00Z",
            "decision": "approved",
        },
        private_key_pem=priv,
        key_id="akta-empirical-prereg-signer-v1",
        amended_at="2026-07-23T15:30:00Z",
    )
    amendment["parent_content_hash"] = "sha256:" + ("ab" * 32)
    with pytest.raises(PreregistrationLockError, match="parent_content_hash"):
        validate_amendment(amendment, parent=parent, observations_started=False)


def test_content_hash_stable_for_locked_body() -> None:
    body = load_locked_preregistration()
    assert compute_content_hash(body) == body["content_hash"]
