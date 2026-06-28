"""Shared pytest fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_scope_adapter_env(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default tests use simulated SCOPE unless marked integration."""
    if request.node.get_closest_marker("integration"):
        return
    monkeypatch.delenv("SCOPE_REPO_PATH", raising=False)
    monkeypatch.delenv("SCOPE_CLI", raising=False)
