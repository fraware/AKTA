"""Tests for structured classification and classifier hardening."""

from __future__ import annotations

from pathlib import Path

import pytest

from akta import AKTAContext
from akta.classify import classify, classify_from_structured_action
from akta.classifier_plugins import ConservativeFallbackClassifierPlugin
from akta.policy import PolicyBundle
from akta.tool_registry import ToolRegistry

ROOT = Path(__file__).resolve().parent.parent


def test_structured_action_priority() -> None:
    action, source, _ = classify_from_structured_action(
        {"action_type": "A7_resource_or_queue_prioritization"},
        None,
    )
    assert action == "A7_resource_or_queue_prioritization"
    assert source == "structured_action"


def test_tool_payload_priority() -> None:
    action, source, _ = classify_from_structured_action(
        None,
        {"action_type": "A6_experimental_planning"},
    )
    assert action == "A6_experimental_planning"
    assert source == "tool_payload"


def test_classify_uses_structured_over_regex() -> None:
    policy = PolicyBundle.from_dir(ROOT / "policy")
    registry = ToolRegistry(policy.tool_registry)
    tool_spec = registry.resolve("unregistered.custom_tool")
    result = classify(
        policy,
        "unregistered.custom_tool",
        "search",
        tool_spec,
        AKTAContext.from_dict({
            "structured_action": {"action_type": "A4_recommendation"},
        }),
    )
    assert result.action_type == "A4_recommendation"
    assert result.matched_source == "structured_action"


def test_conservative_fallback_disabled_without_env() -> None:
    plugin = ConservativeFallbackClassifierPlugin()
    assert plugin.is_enabled() is False


def test_allowed_log_nonconseq_respects_consequentiality() -> None:
    from akta.consequentiality import ConsequentialityResult
    from akta.evaluate import resolve_conditional_decision
    from akta.tool_registry import ToolSpec

    policy = PolicyBundle.from_dir(ROOT / "policy")
    tool_spec = ToolSpec(
        name="t", action_type="A4_recommendation",
        mutates_state=False, external_effect=False, default_permission="allowed",
    )
    cons = ConsequentialityResult(True, "consequential")
    decision = resolve_conditional_decision(
        policy, "allowed_log_nonconseq", "P1_literature_hypothesis_assistant",
        "A4_recommendation", tool_spec, "literature_search.query", cons,
    )
    assert decision == "review_required"
    noncons = ConsequentialityResult(False, "informational")
    decision2 = resolve_conditional_decision(
        policy, "allowed_log_nonconseq", "P1_literature_hypothesis_assistant",
        "A4_recommendation", tool_spec, "literature_search.query", noncons,
    )
    assert decision2 == "allowed_with_logging"


def test_negation_suppresses_prioritize_keyword() -> None:
    from akta.classify import classify_from_action_text

    action, _ = classify_from_action_text("do_not_prioritize_search_only")
    assert action != "A7_resource_or_queue_prioritization"


def test_structured_action_overrides_negated_nl() -> None:
    policy = PolicyBundle.from_dir(ROOT / "policy")
    registry = ToolRegistry(policy.tool_registry)
    tool_spec = registry.resolve("literature_search.query")
    result = classify(
        policy,
        "literature_search.query",
        "do_not_prioritize",
        tool_spec,
        AKTAContext.from_dict({
            "structured_action": {"action_type": "A1_retrieval_or_summary"},
        }),
    )
    assert result.action_type == "A1_retrieval_or_summary"
    assert result.matched_source == "structured_action"


def test_adversarial_structured_escalation_over_tool_registry() -> None:
    policy = PolicyBundle.from_dir(ROOT / "policy")
    registry = ToolRegistry(policy.tool_registry)
    tool_spec = registry.resolve("literature_search.query")
    result = classify(
        policy,
        "literature_search.query",
        "search",
        tool_spec,
        AKTAContext.from_dict({
            "structured_action": {"action_type": "A7_resource_or_queue_prioritization"},
        }),
    )
    assert result.action_type == "A7_resource_or_queue_prioritization"
    assert result.matched_source == "structured_action"
