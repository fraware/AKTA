"""LLM classifier trust boundary tests (v0.5)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from akta import AKTAGate, AKTAContext
from akta.classifier_plugins import PluginClassification
from akta.classify import classify
from akta.policy import PolicyBundle
from akta.tool_registry import ToolRegistry

ROOT = Path(__file__).resolve().parent.parent


def test_tool_registry_overrides_llm_output() -> None:
    from unittest.mock import patch

    from akta.classify import run_plugin_classification

    policy = PolicyBundle.from_dir(ROOT / "policy")
    registry = ToolRegistry(policy.tool_registry)
    tool_spec = registry.resolve("lab_scheduler.prioritize")
    llm_proposal = PluginClassification(
        action_type="A4_recommendation",
        confidence=0.95,
        rationale="LLM would suggest A4",
        source="llm_classifier",
        uncertainty_flags=["llm_advisory"],
        llm_metadata={
            "model": "test",
            "prompt_hash": "abc",
            "schema": "akta_classification_v0.5",
            "confidence": 0.95,
        },
    )
    with patch("akta.classify.run_plugin_classification", return_value=llm_proposal):
        result = classify(
            policy,
            "lab_scheduler.prioritize",
            "prioritize samples",
            tool_spec,
            AKTAContext(),
            ai_output="recommend next experiment",
        )
    assert result.action_type == "A7_resource_or_queue_prioritization"
    assert result.classifier_mode == "deterministic"
    assert "llm_overridden_by_tool_registry" in result.uncertainty_flags


def test_llm_advisory_metadata_in_decision(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AKTA_LLM_CLASSIFIER", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    policy = PolicyBundle.from_dir(ROOT / "policy")
    registry = ToolRegistry(policy.tool_registry)
    tool_spec = registry.resolve("unregistered.custom_tool")

    mock_body = {
        "choices": [{
            "message": {
                "content": json.dumps({
                    "action_type": "A4_recommendation",
                    "confidence": 0.88,
                    "rationale": "Mocked LLM",
                }),
            },
        }],
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(mock_body).encode("utf-8")
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = classify(
            policy,
            "unregistered.custom_tool",
            "ambiguous",
            tool_spec,
            AKTAContext(),
            ai_output="unclear",
        )

    assert result.classifier_mode == "llm_advisory"
    assert result.llm_metadata is not None
    assert result.llm_metadata["model"]
    assert result.llm_metadata["prompt_hash"]
    assert result.llm_metadata["schema"] == "akta_classification_v0.5"


def test_low_confidence_llm_fail_closed_for_mutating(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AKTA_LLM_CLASSIFIER", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    mock_body = {
        "choices": [{
            "message": {
                "content": json.dumps({
                    "action_type": "A8_tool_or_workflow_mutation",
                    "confidence": 0.55,
                    "rationale": "Low confidence mutating",
                }),
            },
        }],
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(mock_body).encode("utf-8")
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    gate = AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")
    with patch("urllib.request.urlopen", return_value=mock_resp):
        decision = gate.evaluate(
            ai_output="unclear mutating request",
            requested_tool="unregistered.custom_mutator",
            requested_action="mutate_workflow",
            context=AKTAContext.from_dict({"evidence_state": "E4_internally_consistent_evidence"}),
            deployment_profile="P5_review_gated_experimental_planner",
        )
    assert decision.admissibility == "abstain_insufficient_context"
    d = decision.to_dict()
    assert d["classification"]["classifier_mode"] == "llm_advisory"
    assert d.get("llm_advisory") is not None


def test_core_tests_pass_with_llm_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AKTA_LLM_CLASSIFIER", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    gate = AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")
    decision = gate.evaluate(
        ai_output={"summary": "Search literature."},
        requested_tool="literature_search.query",
        requested_action="search",
        context=AKTAContext(),
        deployment_profile="P1_literature_hypothesis_assistant",
    )
    assert decision.to_dict()["classification"]["classifier_mode"] == "deterministic"
