"""AKTA 1.1 WS10: lifecycle context semantics."""

from __future__ import annotations

from akta.lifecycle_semantics import (
    check_expires_after_bindings,
    compare_evidence_rank_non_decreasing,
    status_lifecycle_errors,
)


def test_status_authoritative_revocation() -> None:
    errors = status_lifecycle_errors(
        {"status": "revoked", "cardinality_remaining": 1, "revoked": True},
        context_metadata={"grant_use_count": 0},
    )
    assert any("revok" in e for e in errors)


def test_status_authoritative_remaining_uses_ignore_caller_count() -> None:
    errors = status_lifecycle_errors(
        {"status": "active", "cardinality_remaining": 0},
        context_metadata={"grant_use_count": 0},
    )
    assert any("remaining uses" in e for e in errors)


def test_evidence_comparator_allows_improvement() -> None:
    assert compare_evidence_rank_non_decreasing("E2_weak", "E4_strong")
    assert not compare_evidence_rank_non_decreasing("E4_strong", "E1_anecdotal")


def test_expires_after_missing_bound_requires_renewed_review() -> None:
    grant = {
        "constraints": {},
        "expiration": {"expires_after": ["protocol_version_change"]},
    }
    result = check_expires_after_bindings(
        grant,
        context={"protocol_version": "v2"},
        ledger_status={"status": "active", "cardinality_remaining": 1},
    )
    assert not result.ok
    assert result.renewed_review_required


def test_expires_after_protocol_change() -> None:
    grant = {
        "constraints": {"protocol_version": "v1"},
        "expiration": {"expires_after": ["protocol_version_change"]},
    }
    result = check_expires_after_bindings(
        grant,
        context={"protocol_version": "v2"},
        ledger_status={"status": "active", "cardinality_remaining": 1},
    )
    assert not result.ok
    assert any("Protocol" in r or "protocol" in r.lower() for r in result.reasons)
