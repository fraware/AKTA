"""Synthetic summary assurance truthfulness (AKTA-1)."""

from __future__ import annotations

from typing import Any

import pytest

from adapters.scope.client import (
    ADAPTER_MODE_CLI,
    ADAPTER_MODE_SIMULATED,
    SUMMARY_ORIGIN_SIMULATED,
    SUMMARY_ORIGIN_SYNTHESIZED,
    SUMMARY_ORIGIN_SYNTHESIZED_PROVENANCE,
    _resolve_synthetic_assurance_levels,
    _synthesize_scope_summary,
    submit_review_trigger,
)


def _minimal_chain(
    *,
    grant_provenance: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    trigger = {"requested_scope": "single_run_queue_priority", "review_trigger_id": "T1"}
    packet = {"packet_id": "PKT1"}
    decision: dict[str, Any] = {"decision_id": "DEC1"}
    grant: dict[str, Any] = {
        "grant_id": "GR1",
        "authorization": {"approved_scope": "single_run_queue_priority"},
        "requested_scope": "single_run_queue_priority",
    }
    if grant_provenance:
        grant["provenance"] = grant_provenance
    return trigger, packet, decision, grant


def test_simulated_mode_emits_lowest_assurance_levels() -> None:
    trigger, packet, decision, grant = _minimal_chain()
    summary = _synthesize_scope_summary(
        adapter_mode=ADAPTER_MODE_SIMULATED,
        trigger=trigger,
        packet=packet,
        decision=decision,
        grant=grant,
    )
    assert summary["identity_assurance_level"] == "IAL0"
    assert summary["signing_assurance_level"] == "SAL0"
    assert summary["summary_origin"] == SUMMARY_ORIGIN_SIMULATED


def test_synthetic_reads_assurance_from_scope_provenance() -> None:
    trigger, packet, decision, grant = _minimal_chain(
        grant_provenance={
            "identity_assurance_level": "IAL2",
            "signing_assurance_level": "SAL1",
        },
    )
    summary = _synthesize_scope_summary(
        adapter_mode=ADAPTER_MODE_CLI,
        trigger=trigger,
        packet=packet,
        decision=decision,
        grant=grant,
    )
    assert summary["identity_assurance_level"] == "IAL2"
    assert summary["signing_assurance_level"] == "SAL1"
    assert summary["summary_origin"] == SUMMARY_ORIGIN_SYNTHESIZED_PROVENANCE


def test_synthetic_without_provenance_never_claims_institutional_assurance() -> None:
    ial, sal, origin = _resolve_synthetic_assurance_levels(
        adapter_mode=ADAPTER_MODE_CLI,
        grant={"authorization": {"approved_scope": "protocol_draft"}},
        decision={"decision_id": "D1"},
    )
    assert ial == "IAL0"
    assert sal == "SAL0"
    assert origin == SUMMARY_ORIGIN_SYNTHESIZED


def test_submit_review_trigger_simulated_summary_is_lowest_tier() -> None:
    trigger = {
        "review_trigger_id": "AKTA-REVTRIG-SYNTH",
        "requested_scope": "single_run_queue_priority",
    }
    result = submit_review_trigger(trigger, grant_scope="single_run_queue_priority")
    assert result.error is None
    assert result.summary is not None
    assert result.adapter_mode == ADAPTER_MODE_SIMULATED
    assert result.summary["identity_assurance_level"] == "IAL0"
    assert result.summary["signing_assurance_level"] == "SAL0"
    assert result.summary["summary_origin"] == SUMMARY_ORIGIN_SIMULATED


def test_synthetic_summary_never_emits_institutional_ial_without_provenance() -> None:
    trigger, packet, decision, grant = _minimal_chain()
    summary = _synthesize_scope_summary(
        adapter_mode=ADAPTER_MODE_CLI,
        trigger=trigger,
        packet=packet,
        decision=decision,
        grant=grant,
    )
    assert summary["identity_assurance_level"] not in ("IAL3", "IAL4")
    assert summary["signing_assurance_level"] not in ("SAL2", "SAL3", "SAL4")
