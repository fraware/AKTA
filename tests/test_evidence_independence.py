"""AKTA 1.2 P0-11: evidence independence property tests (Hypothesis)."""

from __future__ import annotations

import pytest
from hypothesis import given, settings, strategies as st

from akta.evidence_independence import (
    DECISION_PROVENANCE_LAYERS,
    build_decision_layer_provenance,
    check_evidence_independence,
    grant_must_not_upgrade_block,
    provenance_objects_for_authorization,
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

_GRANT_IDS = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="-_"),
    min_size=1,
    max_size=24,
)
_SCOPES = st.sampled_from(
    ["protocol_draft", "active_protocol_update", "analysis_only", "robot_submit"]
)
_TOOLS = st.lists(
    st.sampled_from(
        [
            "protocol_editor.draft_change",
            "protocol_editor.update_active_protocol",
            "robot_queue.submit",
            "notebook.run_analysis",
            "unknown.consequential.tool",
        ]
    ),
    min_size=0,
    max_size=4,
    unique=True,
)


def _grant_shape(grant_id: str, scope: str, tools: list[str]) -> dict:
    return {
        "grant_id": grant_id,
        "authorization": {
            "approved_scope": scope,
            "allowed_tools": tools,
            "authorization_envelope": {
                "family": "protocol",
                "operation": "draft",
                "allowed_tools": tools,
            },
        },
        "constraints": {"tenant_id": "lab-a"},
    }


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
    assert result.layers.evidence_layer.satisfied_by_grant is False
    assert result.layers.evidence_never_satisfied_by_grant is True


def test_final_composition_not_fed_into_evidence_layer() -> None:
    """P0-11: distinct objects; final must not overwrite evidence_layer."""
    provenance = build_decision_layer_provenance(
        evidence_decision="blocked",
        evidence_reason="weak evidence block",
        deployment_profile_decision="allowed",
        domain_overlay_decision=None,
        authorization_decision="authorization_satisfied",
        tool_decision=None,
        final_decision="draft_only",
        final_reason="composed after grant",
        scope_grant={"grant_id": "G3"},
        authorization_satisfied_by_grant=True,
    )
    assert provenance.evidence_layer.decision == "blocked"
    assert provenance.final_composition.decision == "draft_only"
    assert provenance.evidence_layer.decision != provenance.final_composition.decision
    objects = provenance_objects_for_authorization(provenance)
    for name in DECISION_PROVENANCE_LAYERS:
        assert name in objects
    assert objects["evidence_layer"]["layer"] == "evidence_layer"
    assert objects["final_composition"]["layer"] == "final_composition"
    assert "ok" not in objects["evidence_layer"]


@given(grant_id=_GRANT_IDS, scope=_SCOPES, tools=_TOOLS)
@settings(max_examples=40, deadline=None)
def test_hypothesis_grant_cannot_upgrade_evidence_block(
    grant_id: str, scope: str, tools: list[str]
) -> None:
    grant = _grant_shape(grant_id, scope, tools)
    result = check_evidence_independence(
        scope_grant=grant,
        pre_layers={
            "evidence": {"decision": "blocked", "reason": "weak evidence block"}
        },
        post_decision="allowed",
        post_reason="cleared by grant",
    )
    assert not result.ok
    assert grant_may_satisfy_evidence() is False


@given(grant_id=_GRANT_IDS, scope=_SCOPES, tools=_TOOLS)
@settings(max_examples=40, deadline=None)
def test_hypothesis_missing_evidence_abstention(
    grant_id: str, scope: str, tools: list[str]
) -> None:
    grant = _grant_shape(grant_id, scope, tools)
    result = check_evidence_independence(
        scope_grant=grant,
        pre_layers={
            "abstain_missing_evidence": {
                "decision": "abstain_insufficient_context",
                "reason": "missing evidence",
            }
        },
        post_decision="allowed",
    )
    assert not result.ok


@given(grant_id=_GRANT_IDS, scope=_SCOPES, tools=_TOOLS)
@settings(max_examples=40, deadline=None)
def test_hypothesis_unsupported_profile_block(
    grant_id: str, scope: str, tools: list[str]
) -> None:
    grant = _grant_shape(grant_id, scope, tools)
    result = check_evidence_independence(
        scope_grant=grant,
        pre_layers={
            "unsupported_autonomous_profile": {
                "decision": "blocked",
                "reason": "unsupported autonomous profile P7",
            }
        },
        post_decision="allowed",
    )
    assert not result.ok


@given(grant_id=_GRANT_IDS, scope=_SCOPES, tools=_TOOLS)
@settings(max_examples=40, deadline=None)
def test_hypothesis_domain_overlay_block(
    grant_id: str, scope: str, tools: list[str]
) -> None:
    grant = _grant_shape(grant_id, scope, tools)
    result = check_evidence_independence(
        scope_grant=grant,
        pre_layers={
            "domain_overlay": {
                "decision": "blocked",
                "reason": "domain overlay block",
            }
        },
        post_decision="allowed",
    )
    assert not result.ok


@given(grant_id=_GRANT_IDS, scope=_SCOPES, tools=_TOOLS)
@settings(max_examples=40, deadline=None)
def test_hypothesis_unknown_consequential_tool(
    grant_id: str, scope: str, tools: list[str]
) -> None:
    grant = _grant_shape(grant_id, scope, tools)
    result = check_evidence_independence(
        scope_grant=grant,
        pre_layers={
            "unknown_consequential_tool": {
                "decision": "blocked",
                "reason": "unknown consequential tool",
            }
        },
        post_decision="allowed",
    )
    assert not result.ok


def test_p7_autonomous_operator_refusal_preserved_under_grant() -> None:
    """P7 refusal is a protected block; grants cannot upgrade it."""
    grant = _grant_shape("G-P7", "protocol_draft", ["robot_queue.submit"])
    result = check_evidence_independence(
        scope_grant=grant,
        pre_layers={
            "unsupported_autonomous_profile": {
                "decision": "blocked",
                "reason": "P7 fully autonomous scientific operator unsupported",
            }
        },
        post_decision="allowed",
        post_reason="grant tried to clear P7",
    )
    assert not result.ok
    assert any("unsupported_autonomous_profile" in v for v in result.violations)
