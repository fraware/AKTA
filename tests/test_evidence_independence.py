"""AKTA 1.1 WS9: evidence independence property-style tests."""

from __future__ import annotations

import pytest

from akta.evidence_independence import (
    check_evidence_independence,
    grant_must_not_upgrade_block,
)
from akta.grant_override import grant_may_satisfy_evidence


PROTECTED_BLOCKS = (
    ("evidence", "blocked", "weak evidence block"),
    ("abstain_missing_evidence", "abstain_insufficient_context", "missing evidence"),
    ("deployment_profile", "blocked", "deployment profile forbids action"),
    ("domain_overlay", "blocked", "domain overlay block"),
    ("unknown_consequential_tool", "blocked", "unknown consequential tool"),
    ("unsupported_autonomous_profile", "blocked", "unsupported autonomous profile"),
)


@pytest.mark.parametrize("kind,decision,reason", PROTECTED_BLOCKS)
def test_grant_cannot_upgrade_protected_block(
    kind: str, decision: str, reason: str
) -> None:
    grant = {"grant_id": "G1", "authorization": {"approved_scope": "protocol_draft"}}
    result = check_evidence_independence(
        scope_grant=grant,
        pre_layers={kind: {"decision": decision, "reason": reason}},
        post_decision="allowed",
        post_reason="cleared by grant",
    )
    assert not result.ok
    assert result.violations


@pytest.mark.parametrize("kind,decision,reason", PROTECTED_BLOCKS)
def test_property_grant_must_not_upgrade(
    kind: str, decision: str, reason: str
) -> None:
    assert grant_may_satisfy_evidence() is False
    violation = grant_must_not_upgrade_block(
        pre_grant_decision=decision,
        post_grant_decision="allowed",
        pre_grant_reason=reason,
        block_kind=kind,
    )
    assert violation is not None


def test_layered_provenance_never_marks_evidence_satisfied() -> None:
    grant = {"grant_id": "G2"}
    result = check_evidence_independence(
        scope_grant=grant,
        pre_layers={"evidence": {"decision": "blocked", "reason": "evidence"}},
        post_decision="blocked",
    )
    assert result.ok
    assert result.layers is not None
    assert result.layers.evidence.satisfied_by_grant is False
    assert result.layers.evidence_never_satisfied_by_grant is True
