"""Tests for optional classifier plugins (v0.2)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from akta import AKTAGate, AKTAContext
from akta.classifier_plugins import (
    ClassifierPlugin,
    ModelAssistedClassifierPlugin,
    ConservativeFallbackClassifierPlugin,
    PluginClassification,
    get_classifier_plugins,
    register_classifier_plugin,
    run_plugin_classification,
)
from akta.classify import classify
from akta.policy import PolicyBundle
from akta.tool_registry import ToolRegistry

ROOT = Path(__file__).resolve().parent.parent


class _StubPlugin(ClassifierPlugin):
    def __init__(self, action: str = "A2_hypothesis_generation") -> None:
        self._action = action

    @property
    def name(self) -> str:
        return "stub_plugin"

    def is_enabled(self) -> bool:
        return True

    def classify(self, policy, requested_tool, requested_action, tool_spec, context, ai_output=None):
        if requested_tool != "stub_only.custom_tool":
            return None
        return PluginClassification(
            action_type=self._action,
            confidence=0.72,
            rationale="stub plugin classification",
            source="stub_plugin",
        )


def test_conservative_fallback_disabled_by_default() -> None:
    plugin = ConservativeFallbackClassifierPlugin()
    assert plugin.is_enabled() is False
    assert get_classifier_plugins(enabled_only=True) == []


def test_model_assisted_alias_disabled_by_default() -> None:
    plugin = ModelAssistedClassifierPlugin()
    assert plugin.is_enabled() is False


def test_conservative_fallback_enabled_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AKTA_CONSERVATIVE_CLASSIFIER_FALLBACK", "true")
    plugin = ConservativeFallbackClassifierPlugin()
    assert plugin.is_enabled() is True
    result = plugin.classify(
        PolicyBundle.from_dir(ROOT / "policy"),
        "unregistered.custom_mutator",
        "unknown_action",
        ToolRegistry(PolicyBundle.from_dir(ROOT / "policy").tool_registry).resolve("unregistered.custom_mutator"),
        AKTAContext(),
    )
    assert result is not None
    assert result.action_type == "A3_evidence_interpretation"
    assert "conservative_fallback" in result.uncertainty_flags


def test_model_assisted_enabled_via_legacy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AKTA_MODEL_ASSISTED_CLASSIFIER", "true")
    plugin = ModelAssistedClassifierPlugin()
    assert plugin.is_enabled() is True


def test_register_custom_plugin() -> None:
    register_classifier_plugin(_StubPlugin(), replace=True)
    policy = PolicyBundle.from_dir(ROOT / "policy")
    registry = ToolRegistry(policy.tool_registry)
    tool_spec = registry.resolve("unregistered.custom_mutator")
    result = run_plugin_classification(
        policy,
        "stub_only.custom_tool",
        "unclear_action",
        tool_spec,
        AKTAContext(),
    )
    assert result is not None
    assert result.action_type == "A2_hypothesis_generation"
    assert result.source == "stub_plugin"


def test_classify_uses_plugin_when_deterministic_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AKTA_CONSERVATIVE_CLASSIFIER_FALLBACK", "1")
    policy = PolicyBundle.from_dir(ROOT / "policy")
    registry = ToolRegistry(policy.tool_registry)
    tool_spec = registry.resolve("unregistered.custom_mutator")
    result = classify(
        policy,
        "unregistered.custom_mutator",
        "unclear_action",
        tool_spec,
        AKTAContext(),
        ai_output="unclear",
    )
    assert result.classifier_mode in ("plugin_assisted", "conservative_fallback", "llm_classifier")


def test_plugin_does_not_override_deterministic_classification(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AKTA_CONSERVATIVE_CLASSIFIER_FALLBACK", "1")
    register_classifier_plugin(_StubPlugin(), replace=True)
    gate = AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")
    decision = gate.evaluate(
        ai_output={"summary": "Search literature."},
        requested_tool="literature_search.query",
        requested_action="search",
        context=AKTAContext(),
        deployment_profile="P1_literature_hypothesis_assistant",
    )
    assert decision.to_dict()["scientific_action_type"] == "A1_retrieval_or_summary"
