"""Shared pytest fixtures for AKTA unit tests."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _compat_structured_actions_for_unit_tests(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    """Default unit tests to legacy known-tool behavior unless opted in.

    Production/pilot/release still require declarations via schema + env/mode.
    Structured-action dedicated tests set AKTA_REQUIRE_STRUCTURED_ACTIONS=1
    (or delete this env) explicitly.
    """
    if "structured_action" in request.node.nodeid or "test_structured_action" in request.node.nodeid:
        return
    if request.node.get_closest_marker("require_structured_actions"):
        monkeypatch.setenv("AKTA_REQUIRE_STRUCTURED_ACTIONS", "1")
        return
    monkeypatch.setenv("AKTA_REQUIRE_STRUCTURED_ACTIONS", "0")
