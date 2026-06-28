"""Optional classifier plugins for AKTA (disabled by default).

Deterministic classification is the default path. Plugins extend classification when
deterministic rules cannot resolve an action type. LLM output is advisory only and
never overrides known tool-registry mappings.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from akta.context import AKTAContext
from akta.policy import PolicyBundle
from akta.tool_registry import ToolSpec


@dataclass
class PluginClassification:
    """Classification proposal from an optional classifier plugin."""

    action_type: str
    confidence: float
    rationale: str
    alternates: list[str] = field(default_factory=list)
    source: str = "plugin"
    uncertainty_flags: list[str] = field(default_factory=list)
    llm_metadata: dict[str, Any] | None = None


class ClassifierPlugin(ABC):
    """Extension point for optional, non-deterministic classifiers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable plugin identifier."""

    @abstractmethod
    def is_enabled(self) -> bool:
        """Whether this plugin should run for the current process."""

    @abstractmethod
    def classify(
        self,
        policy: PolicyBundle,
        requested_tool: str,
        requested_action: str,
        tool_spec: ToolSpec,
        context: AKTAContext,
        ai_output: Any = None,
    ) -> PluginClassification | None:
        """Return a classification proposal, or None if the plugin declines."""


class ConservativeFallbackClassifierPlugin(ClassifierPlugin):
    """Env-gated conservative fallback when deterministic classification fails.

    Enabled when ``AKTA_CONSERVATIVE_CLASSIFIER_FALLBACK`` is ``1``, ``true``, or ``yes``.
    Does not call external models; applies a conservative default action type.
    """

    ENV_VAR = "AKTA_CONSERVATIVE_CLASSIFIER_FALLBACK"
    DEFAULT_ACTION = "A3_evidence_interpretation"
    DEFAULT_CONFIDENCE = 0.6

    @property
    def name(self) -> str:
        return "conservative_fallback"

    def is_enabled(self) -> bool:
        legacy = os.environ.get("AKTA_MODEL_ASSISTED_CLASSIFIER", "").lower() in ("1", "true", "yes")
        current = os.environ.get(self.ENV_VAR, "").lower() in ("1", "true", "yes")
        return legacy or current

    def classify(
        self,
        policy: PolicyBundle,
        requested_tool: str,
        requested_action: str,
        tool_spec: ToolSpec,
        context: AKTAContext,
        ai_output: Any = None,
    ) -> PluginClassification | None:
        if not self.is_enabled():
            return None
        return PluginClassification(
            action_type=self.DEFAULT_ACTION,
            confidence=self.DEFAULT_CONFIDENCE,
            rationale=(
                f"{self.name}: deterministic classification failed; "
                f"conservative default {self.DEFAULT_ACTION} "
                f"({self.ENV_VAR} enabled)"
            ),
            source="conservative_fallback",
            uncertainty_flags=["conservative_fallback"],
        )


# Backward-compatible alias (deprecated name removed in v0.4).
ModelAssistedClassifierPlugin = ConservativeFallbackClassifierPlugin


LLM_CLASSIFICATION_SCHEMA = {
    "type": "object",
    "required": ["action_type", "confidence", "rationale"],
    "properties": {
        "action_type": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "rationale": {"type": "string"},
        "alternate_action_types": {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": False,
}

LLM_LOW_CONFIDENCE_THRESHOLD = 0.7


def _prompt_hash(system_prompt: str, user_text: str) -> str:
    payload = json.dumps({"system": system_prompt, "user": user_text[:4000]}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class OptionalLLMClassifierPlugin(ClassifierPlugin):
    """Optional OpenAI-compatible LLM classifier with strict JSON schema output.

    Enabled only when ``AKTA_LLM_CLASSIFIER`` is set AND ``OPENAI_API_KEY`` is present.
    Fails closed (returns None) without API key even if env flag is set.
    Advisory only — known tool-registry mappings override LLM output in ``classify()``.
    """

    ENV_VAR = "AKTA_LLM_CLASSIFIER"
    API_KEY_ENV = "OPENAI_API_KEY"
    MODEL_ENV = "AKTA_LLM_MODEL"
    DEFAULT_MODEL = "gpt-4o-mini"

    @property
    def name(self) -> str:
        return "optional_llm_classifier"

    def is_enabled(self) -> bool:
        flag = os.environ.get(self.ENV_VAR, "").lower() in ("1", "true", "yes")
        return flag and bool(os.environ.get(self.API_KEY_ENV))

    def classify(
        self,
        policy: PolicyBundle,
        requested_tool: str,
        requested_action: str,
        tool_spec: ToolSpec,
        context: AKTAContext,
        ai_output: Any = None,
    ) -> PluginClassification | None:
        if not self.is_enabled():
            return None
        if tool_spec.known:
            return None

        action_types = list(
            policy.action_ontology.get("action_types", {}).keys()
        )
        prompt = (
            "Classify the scientific action type for this tool request. "
            f"Tool: {requested_tool}. Action: {requested_action}. "
            f"Valid action_types: {action_types}. "
            "Respond with JSON matching schema: action_type, confidence (0-1), "
            "rationale, optional alternate_action_types."
        )
        text = ai_output if isinstance(ai_output, str) else str(ai_output or requested_action)
        model = os.environ.get(self.MODEL_ENV, self.DEFAULT_MODEL)
        phash = _prompt_hash(prompt, text)

        try:
            result = self._call_openai(prompt, text, model)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError, ValueError):
            return None

        action_type = result.get("action_type", "")
        if action_type not in action_types:
            return None

        confidence = float(result.get("confidence", 0.65))
        llm_meta = {
            "model": model,
            "prompt_hash": phash,
            "schema": "akta_classification_v0.5",
            "confidence": confidence,
        }

        return PluginClassification(
            action_type=action_type,
            confidence=confidence,
            rationale=str(result.get("rationale", "LLM classification")),
            alternates=list(result.get("alternate_action_types") or []),
            source="llm_classifier",
            uncertainty_flags=["llm_advisory"],
            llm_metadata=llm_meta,
        )

    def _call_openai(self, system_prompt: str, user_text: str, model: str) -> dict[str, Any]:
        api_key = os.environ[self.API_KEY_ENV]
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text[:4000]},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "akta_classification",
                    "strict": True,
                    "schema": LLM_CLASSIFICATION_SCHEMA,
                },
            },
            "temperature": 0,
        }
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        content = body["choices"][0]["message"]["content"]
        return json.loads(content)


_PLUGIN_REGISTRY: list[ClassifierPlugin] = [
    OptionalLLMClassifierPlugin(),
    ConservativeFallbackClassifierPlugin(),
]


def register_classifier_plugin(plugin: ClassifierPlugin, *, replace: bool = False) -> None:
    """Register a classifier plugin. Use ``replace=True`` to swap same-named plugins."""
    if replace:
        _PLUGIN_REGISTRY[:] = [p for p in _PLUGIN_REGISTRY if p.name != plugin.name]
    if not any(p.name == plugin.name for p in _PLUGIN_REGISTRY):
        _PLUGIN_REGISTRY.append(plugin)


def get_classifier_plugins(enabled_only: bool = True) -> list[ClassifierPlugin]:
    """Return registered classifier plugins."""
    plugins = list(_PLUGIN_REGISTRY)
    if enabled_only:
        plugins = [p for p in plugins if p.is_enabled()]
    return plugins


def run_plugin_classification(
    policy: PolicyBundle,
    requested_tool: str,
    requested_action: str,
    tool_spec: ToolSpec,
    context: AKTAContext,
    ai_output: Any = None,
) -> PluginClassification | None:
    """Run enabled plugins in registration order; first non-None result wins."""
    for plugin in get_classifier_plugins(enabled_only=True):
        result = plugin.classify(
            policy,
            requested_tool,
            requested_action,
            tool_spec,
            context,
            ai_output=ai_output,
        )
        if result is not None:
            return result
    return None
