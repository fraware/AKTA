"""SCOPE contract negotiation tests (directive §6)."""

from __future__ import annotations

import pytest

from akta.scope_negotiation import (
    STATUS_COMPLETED,
    STATUS_SESSION_REQUIRED,
    consume_scope_summary,
    negotiate_scope_contract,
)


def _completed_summary(**overrides: object) -> dict:
    base = {
        "status": "completed",
        "adapter_contract_version": "scope-akta-review-summary-v1.0",
        "identity_assurance_level": "IAL1",
        "signing_assurance_level": "SAL1",
        "approved_scope": "protocol_draft",
        "decision_id": "SCOPE-DEC-1",
        "grant_id": "SCOPE-GRANT-1",
        "packet_id": "SCOPE-PKT-1",
    }
    base.update(overrides)
    return base


def test_negotiate_completed_ok() -> None:
    result = negotiate_scope_contract(summary=_completed_summary(), strict=False)
    assert result.ok
    assert result.status == STATUS_COMPLETED
    assert result.review_pending is False


def test_session_required_emits_pending_without_grant_load() -> None:
    summary = {
        "status": "session_required",
        "adapter_contract_version": "scope-akta-review-v1.0",
        "identity_assurance_level": "IAL2",
        "signing_assurance_level": "SAL2",
        "session_id": "SCOPE-SESSION-ABC",
        "required_roles": ["domain_scientist", "protocol_owner"],
        "next_integration_action": "open_review_queue",
        # Intentionally omit decision/grant paths — must not be required.
    }
    result = consume_scope_summary(summary, strict=False)
    assert result.status == STATUS_SESSION_REQUIRED
    assert result.review_pending is True
    assert result.session_id == "SCOPE-SESSION-ABC"
    assert "domain_scientist" in result.required_roles
    assert result.next_integration_action == "open_review_queue"
    payload = result.to_dict()
    assert payload["review_pending"] is True
    assert "decision_path" not in payload


def test_completed_requires_decision_and_grant_refs() -> None:
    summary = _completed_summary()
    summary.pop("decision_id")
    summary.pop("grant_id")
    result = consume_scope_summary(summary, strict=False)
    assert not result.ok
    assert any("decision" in e for e in result.errors)
    assert any("grant" in e for e in result.errors)


def test_strict_rejects_arbitrary_summary_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AKTA_STRICT_SCOPE_CONTRACT", "1")
    result = negotiate_scope_contract(
        summary=_completed_summary(status="kinda-done"),
        strict=True,
    )
    assert not result.ok
    assert any("summary.status" in e for e in result.errors)


def test_strict_version_mismatch() -> None:
    result = negotiate_scope_contract(
        peer_versions={"fixture_contract_version": "akta-scope-contract-v0.0.0"},
        summary=_completed_summary(),
        strict=True,
    )
    assert not result.ok
    assert any("fixture_contract_version" in e for e in result.errors)


def test_schema_validates_both_branches() -> None:
    from akta.records import validate_against_schema

    validate_against_schema(_completed_summary(), "scope_akta_review_summary.schema.json")
    validate_against_schema(
        {
            "status": "session_required",
            "adapter_contract_version": "scope-akta-review-v1.0",
            "identity_assurance_level": "IAL0",
            "signing_assurance_level": "SAL0",
            "session_id": "SCOPE-SESSION-X",
            "review_pending": True,
        },
        "scope_akta_review_summary.schema.json",
    )
