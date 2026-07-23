"""Strict negotiation peer-authentication (P0-H)."""

from __future__ import annotations

import pytest

from akta.scope_negotiation import consume_scope_summary, negotiate_scope_contract


def _full_peer() -> dict[str, str]:
    return {
        "scope_package_version": "2.1.0",
        "scope_core_version": "scope-core-v2.1",
        "akta_review_contract_version": "scope-akta-review-v1.0",
        "grant_schema_version": "scope-grant-v2",
        "envelope_schema_version": "scientific-authorization-envelope-v2",
        "summary_schema_version": "scope-akta-review-summary-v1.0",
        "policy_manifest_version": "scope-policy-v2.1",
    }


def test_strict_rejects_legacy_envelope_ids() -> None:
    peer = _full_peer()
    peer["envelope_schema_version"] = "akta-capability-envelope-v1.0"
    peer["grant_schema_version"] = "akta-scope-grant-v1.0"
    result = negotiate_scope_contract(peer_versions=peer, strict=True)
    assert not result.ok
    assert any("legacy" in e for e in result.errors)


def test_strict_rejects_missing_peer_versions() -> None:
    result = negotiate_scope_contract(peer_versions={}, strict=True)
    assert not result.ok
    assert any("peer missing" in e for e in result.errors)


def test_strict_accepts_full_peer() -> None:
    result = negotiate_scope_contract(peer_versions=_full_peer(), strict=True)
    assert result.ok, result.errors


def test_session_required_does_not_invent_session_id() -> None:
    result = negotiate_scope_contract(
        peer_versions=_full_peer(),
        summary={"status": "session_required", "required_roles": ["domain_scientist"]},
        strict=True,
    )
    assert not result.ok
    assert any("session_id" in e for e in result.errors)
    assert result.session_id is None


def test_session_required_with_real_identity() -> None:
    result = negotiate_scope_contract(
        peer_versions=_full_peer(),
        summary={
            "status": "session_required",
            "session_id": "SCOPE-SESSION-ABC",
            "packet_id": "pkt-1",
            "required_roles": ["domain_scientist"],
            "summary_schema_version": "scope-akta-review-summary-v1.0",
            "scope_contract_version": "scope-akta-review-v1.0",
        },
        strict=True,
    )
    assert result.ok, result.errors
    assert result.session_id == "SCOPE-SESSION-ABC"
    assert result.packet_id == "pkt-1"


def test_completed_summary_requires_authenticated_ids() -> None:
    result = consume_scope_summary(
        {
            "status": "completed",
            "decision_path": "/tmp/decision.json",
            "grant_path": "/tmp/grant.json",
            "approved_scope": "protocol_draft",
        },
        peer_versions=_full_peer(),
        strict=True,
    )
    assert not result.ok
    assert any("decision_id" in e for e in result.errors)
    assert any("grant_id" in e for e in result.errors)


def test_completed_summary_with_hashes() -> None:
    result = consume_scope_summary(
        {
            "status": "completed",
            "decision_id": "dec-1",
            "grant_id": "grant-1",
            "decision_hash": "sha256:" + ("a" * 64),
            "grant_hash": "sha256:" + ("b" * 64),
            "approved_scope": "protocol_draft",
            "summary_schema_version": "scope-akta-review-summary-v1.0",
        },
        peer_versions=_full_peer(),
        strict=True,
    )
    assert result.ok, result.errors
