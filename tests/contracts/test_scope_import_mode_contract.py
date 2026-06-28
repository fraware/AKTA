"""SCOPE python-import mode contract tests (mock ScopeEngine when no sibling repo)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from adapters.scope.client import ADAPTER_MODE_PYTHON_IMPORT, submit_review_trigger

ROOT = Path(__file__).resolve().parent.parent.parent


class MockScopeEngine:
    """Minimal ScopeEngine v0.5 stand-in for contract tests."""

    @classmethod
    def from_policy_dir(
        cls,
        policy_dir: str | Path | None = None,
        **kwargs: Any,
    ) -> MockScopeEngine:
        return cls()

    def create_packet(
        self,
        akta_record: str | Path | dict[str, Any] | None = None,
        akta_trigger: str | Path | dict[str, Any] | None = None,
        *,
        vsa_report: str | Path | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        trigger = akta_trigger if isinstance(akta_trigger, dict) else {}
        return {
            "packet_id": "SCOPE-PKT-IMPORT01",
            "review_request": {"requested_scope": trigger.get("requested_scope")},
        }

    def submit_decision(
        self,
        packet: dict[str, Any],
        reviewer: str | Path | dict[str, Any],
        decision: dict[str, Any],
    ) -> dict[str, Any]:
        reviewer_data = reviewer if isinstance(reviewer, dict) else {}
        return {
            "decision_id": "SCOPE-DEC-IMPORT01",
            "decision": decision,
            "reviewer": reviewer_data,
        }

    def issue_grant(
        self,
        packet: dict[str, Any],
        decision: dict[str, Any],
        *,
        constraints: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        approved = decision["decision"]["approved_scope"]
        return {
            "grant_id": "SCOPE-GRANT-IMPORT01",
            "granted_scope": approved,
            "requested_scope": packet["review_request"]["requested_scope"],
            "reviewer_id": decision["reviewer"].get("reviewer_id"),
        }


@pytest.fixture
def scope_repo_path(tmp_path: Path) -> Path:
    repo = tmp_path / "scope_repo"
    repo.mkdir()
    (repo / "policy").mkdir()
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

    engine = MockScopeEngine()
    with patch("adapters.scope.client._load_scope_engine", return_value=engine):
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

    engine = MockScopeEngine()
    with patch("adapters.scope.client._load_scope_engine", return_value=engine):
        result = submit_review_trigger(trigger, grant_scope="robot_queue_submission")

    assert result.adapter_mode == ADAPTER_MODE_PYTHON_IMPORT
    assert result.error is not None


def test_scope_import_missing_module_returns_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    repo = tmp_path / "empty_repo"
    repo.mkdir()
    monkeypatch.setenv("SCOPE_REPO_PATH", str(repo))
    monkeypatch.delenv("SCOPE_CLI", raising=False)

    result = submit_review_trigger({
        "review_trigger_id": "AKTA-REVTRIG-IMPORT03",
        "requested_scope": "protocol_draft",
    })
    assert result.adapter_mode == ADAPTER_MODE_PYTHON_IMPORT
    assert result.error is not None
