"""Tests for optional LLM classifier plugin (mocked HTTP, no real API key)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from akta import AKTAContext
from akta.classifier_plugins import OptionalLLMClassifierPlugin, run_plugin_classification
from akta.policy import PolicyBundle
from akta.tool_registry import ToolRegistry

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def policy_and_tool():
    policy = PolicyBundle.from_dir(ROOT / "policy")
    registry = ToolRegistry(policy.tool_registry)
    tool_spec = registry.resolve("unregistered.custom_tool")
    return policy, tool_spec


def test_llm_classifier_fail_closed_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AKTA_LLM_CLASSIFIER", "1")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    plugin = OptionalLLMClassifierPlugin()
    assert plugin.is_enabled() is False


def test_llm_classifier_fail_closed_flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AKTA_LLM_CLASSIFIER", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    plugin = OptionalLLMClassifierPlugin()
    assert plugin.is_enabled() is False


def test_llm_classifier_structured_output_when_mocked(
    monkeypatch: pytest.MonkeyPatch,
    policy_and_tool,
) -> None:
    policy, tool_spec = policy_and_tool
    monkeypatch.setenv("AKTA_LLM_CLASSIFIER", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    mock_body = {
        "choices": [{
            "message": {
                "content": json.dumps({
                    "action_type": "A4_recommendation",
                    "confidence": 0.88,
                    "rationale": "Mocked structured classification",
                    "alternate_action_types": [],
                }),
            },
        }],
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(mock_body).encode("utf-8")
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    plugin = OptionalLLMClassifierPlugin()
    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = plugin.classify(
            policy,
            "unregistered.custom_tool",
            "ambiguous request",
            tool_spec,
            AKTAContext.from_dict({"evidence_state": "E2_preliminary_signal"}),
            ai_output="unclear wording",
        )

    assert result is not None
    assert result.action_type == "A4_recommendation"
    assert result.source == "llm_classifier"
    assert result.confidence == 0.88


def test_llm_classifier_invalid_action_type_returns_none(
    monkeypatch: pytest.MonkeyPatch,
    policy_and_tool,
) -> None:
    policy, tool_spec = policy_and_tool
    monkeypatch.setenv("AKTA_LLM_CLASSIFIER", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    mock_body = {
        "choices": [{
            "message": {
                "content": json.dumps({
                    "action_type": "A99_invalid",
                    "confidence": 0.9,
                    "rationale": "bad type",
                }),
            },
        }],
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(mock_body).encode("utf-8")
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    plugin = OptionalLLMClassifierPlugin()
    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = run_plugin_classification(
            policy,
            "unregistered.custom_tool",
            "ambiguous",
            tool_spec,
            AKTAContext(),
            ai_output="text",
        )
    assert result is None
