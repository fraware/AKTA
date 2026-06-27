"""Optional classifier plugins for AKTA (disabled by default).

Deterministic classification is the default path. Plugins extend classification when
deterministic rules cannot resolve an action type. Enable via environment variables
or explicit registration for custom integrations.
"""

from __future__ import annotations

import os
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


class ModelAssistedClassifierPlugin(ClassifierPlugin):
    """Env-gated fallback when deterministic classification fails.

    Enabled when ``AKTA_MODEL_ASSISTED_CLASSIFIER`` is ``1``, ``true``, or ``yes``.
    This plugin does not call external models; it applies a conservative fail-closed
    default suitable for optional model-assisted pipelines that register a custom
    plugin subclass or replace this implementation.
    """

    ENV_VAR = "AKTA_MODEL_ASSISTED_CLASSIFIER"
    DEFAULT_ACTION = "A3_evidence_interpretation"
    DEFAULT_CONFIDENCE = 0.6

    @property
    def name(self) -> str:
        return "model_assisted_fallback"

    def is_enabled(self) -> bool:
        return os.environ.get(self.ENV_VAR, "").lower() in ("1", "true", "yes")

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
            source="model_assisted",
            uncertainty_flags=["model_assisted_fallback"],
        )


_PLUGIN_REGISTRY: list[ClassifierPlugin] = [
    ModelAssistedClassifierPlugin(),
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
