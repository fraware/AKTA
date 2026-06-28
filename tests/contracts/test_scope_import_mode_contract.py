"""SCOPE python-import mode contract tests (mock ScopeEngine when no sibling repo)."""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import patch

import pytest

from adapters.scope.client import ADAPTER_MODE_PYTHON_IMPORT, submit_review_trigger

ROOT = Path(__file__).resolve().parent.parent.parent


class MockScopeEngine:
    """Minimal ScopeEngine stand-in for contract tests."""

    def create_packet(self, trigger: dict[str, Any], record: dict[str, Any] | None = None) -> dict[str, Any]:
        from akta.scope_contract import assemble_review_packet

        return assemble_review_packet(trigger, record)

    def submit_decision(
        self,
        packet: dict[str, Any],
        *,
        granted_scope: str,
        reviewer_id: str,
    ) -> dict[str, Any]:
        return {
            "status": "granted",
            "granted_scope": granted_scope,
            "reviewer_id": reviewer_id,
            "packet_id": packet.get("trigger", {}).get("review_trigger_id"),
        }

    def issue_grant(self, decision: dict[str, Any], trigger: dict[str, Any] | None = None) -> dict[str, Any]:
        trigger = trigger or {}
        return {
            "grant_id": f"SCOPE-GRANT-{trigger.get('review_trigger_id', 'TEST')}",
            "granted_scope": decision["granted_scope"],
            "requested_scope": trigger.get("requested_scope"),
            "reviewer_id": decision.get("reviewer_id"),
            "review_trigger_id": trigger.get("review_trigger_id"),
        }


@pytest.fixture
def scope_repo_path(tmp_path: Path) -> Path:
    repo = tmp_path / "scope_repo"
    repo.mkdir()
    (repo / "scope.py").write_text("class ScopeEngine: pass\n", encoding="utf-8")
    return repo


def test_scope_import_mode_full_chain(monkeypatch: pytest.MonkeyPatch, scope_repo_path: Path) -> None:
    trigger = {
        "review_trigger_id": "AKTA-REVTRIG-IMPORT01",
        "requested_scope": "active_protocol_update",
        "required_review_role": "protocol_owner",
    }
    monkeypatch.setenv("SCOPE_REPO_PATH", str(scope_repo_path))
    monkeypatch.delenv("SCOPE_CLI", raising=False)

    fake_scope = ModuleType("scope")
    fake_scope.ScopeEngine = MockScopeEngine
    with patch.dict(sys.modules, {"scope": fake_scope}):
        result = submit_review_trigger(trigger, grant_scope="protocol_draft", reviewer_id="protocol_owner")

    assert result.adapter_mode == ADAPTER_MODE_PYTHON_IMPORT
    assert result.error is None
    assert result.review_packet is not None
    assert result.decision is not None
    assert result.grant is not None
    assert result.grant["granted_scope"] == "protocol_draft"


def test_scope_import_invalid_grant_fails(monkeypatch: pytest.MonkeyPatch, scope_repo_path: Path) -> None:
    trigger = {
        "review_trigger_id": "AKTA-REVTRIG-IMPORT02",
        "requested_scope": "active_protocol_update",
    }
    monkeypatch.setenv("SCOPE_REPO_PATH", str(scope_repo_path))
    monkeypatch.delenv("SCOPE_CLI", raising=False)

    fake_scope = ModuleType("scope")
    fake_scope.ScopeEngine = MockScopeEngine
    with patch.dict(sys.modules, {"scope": fake_scope}):
        result = submit_review_trigger(trigger, grant_scope="robot_queue_submission")

    assert result.adapter_mode == ADAPTER_MODE_PYTHON_IMPORT
    assert result.error is not None


def test_scope_import_missing_module_returns_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    repo = tmp_path / "empty_repo"
    repo.mkdir()
    monkeypatch.setenv("SCOPE_REPO_PATH", str(repo))
    monkeypatch.delenv("SCOPE_CLI", raising=False)
    sys.modules.pop("scope", None)

    result = submit_review_trigger({
        "review_trigger_id": "AKTA-REVTRIG-IMPORT03",
        "requested_scope": "protocol_draft",
    })
    assert result.adapter_mode == ADAPTER_MODE_PYTHON_IMPORT
    assert result.error is not None
