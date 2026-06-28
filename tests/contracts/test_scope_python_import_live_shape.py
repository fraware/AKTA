"""SCOPE python-import adapter contract tests (v0.5 ScopeEngine.from_policy_dir)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from adapters.scope.client import ADAPTER_MODE_PYTHON_IMPORT, submit_review_trigger

ROOT = Path(__file__).resolve().parent.parent.parent
SCOPE_SIBLING = ROOT.parent / "SCOPE"


class MockScopeEngineV05:
    """Mock ScopeEngine with real SCOPE v0.5 method signatures."""

    policy_dir: Path | None = None

    def __init__(self, policy: Any = None, **kwargs: Any) -> None:
        self.policy = policy

    @classmethod
    def from_policy_dir(
        cls,
        policy_dir: str | Path | None = None,
        *,
        ledger_path: str | Path | None = None,
        session_store: Any | None = None,
    ) -> MockScopeEngineV05:
        cls.policy_dir = Path(policy_dir) if policy_dir else None
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
            "packet_id": "SCOPE-PKT-MOCK01",
            "packet_type": "scope_review_packet",
            "review_request": {"requested_scope": trigger.get("requested_scope")},
            "akta_constraints": {"blocked_tools": trigger.get("blocked_tools", [])},
        }

    def submit_decision(
        self,
        packet: dict[str, Any],
        reviewer: str | Path | dict[str, Any],
        decision: dict[str, Any],
    ) -> dict[str, Any]:
        reviewer_data = reviewer if isinstance(reviewer, dict) else {}
        return {
            "decision_id": "SCOPE-DEC-MOCK01",
            "decision": decision,
            "reviewer": reviewer_data,
            "packet_id": packet["packet_id"],
        }

    def issue_grant(
        self,
        packet: dict[str, Any],
        decision: dict[str, Any],
        *,
        constraints: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        approved = decision["decision"]["approved_scope"]
        requested = packet["review_request"]["requested_scope"]
        return {
            "grant_id": "SCOPE-GRANT-MOCK01",
            "authorization": {"approved_scope": approved},
            "source": {
                "packet_id": packet["packet_id"],
                "requested_scope": requested,
            },
        }


@pytest.fixture
def scope_repo_path(tmp_path: Path) -> Path:
    repo = tmp_path / "scope_repo"
    repo.mkdir()
    (repo / "policy").mkdir()
    (repo / "scope.py").write_text("class ScopeEngine: pass\n", encoding="utf-8")
    return repo


def test_python_import_uses_from_policy_dir(
    monkeypatch: pytest.MonkeyPatch,
    scope_repo_path: Path,
) -> None:
    trigger = {
        "review_trigger_id": "AKTA-REVTRIG-LIVE01",
        "requested_scope": "active_protocol_update",
        "required_review_role": "protocol_owner",
    }
    monkeypatch.setenv("SCOPE_REPO_PATH", str(scope_repo_path))
    monkeypatch.delenv("SCOPE_CLI", raising=False)

    engine = MockScopeEngineV05.from_policy_dir(scope_repo_path / "policy")
    with patch("adapters.scope.client._load_scope_engine", return_value=engine):
        result = submit_review_trigger(
            trigger,
            grant_scope="protocol_draft",
            reviewer_id="protocol_owner",
        )

    assert result.adapter_mode == ADAPTER_MODE_PYTHON_IMPORT
    assert result.error is None
    assert MockScopeEngineV05.policy_dir == scope_repo_path / "policy"
    assert result.review_packet is not None
    assert result.decision is not None
    assert result.grant is not None
    assert result.grant["authorization"]["approved_scope"] == "protocol_draft"


def test_python_import_v05_submit_decision_kwargs(
    monkeypatch: pytest.MonkeyPatch,
    scope_repo_path: Path,
) -> None:
    """submit_decision receives reviewer dict and decision dict (not granted_scope kwarg)."""
    calls: dict[str, Any] = {}

    class RecordingEngine(MockScopeEngineV05):
        def submit_decision(
            self,
            packet: dict[str, Any],
            reviewer: str | Path | dict[str, Any],
            decision: dict[str, Any],
        ) -> dict[str, Any]:
            calls["reviewer"] = reviewer
            calls["decision"] = decision
            return super().submit_decision(packet, reviewer, decision)

    trigger = {
        "review_trigger_id": "AKTA-REVTRIG-LIVE02",
        "requested_scope": "active_protocol_update",
        "required_review_role": "protocol_owner",
    }
    monkeypatch.setenv("SCOPE_REPO_PATH", str(scope_repo_path))
    monkeypatch.delenv("SCOPE_CLI", raising=False)

    engine = RecordingEngine()
    with patch("adapters.scope.client._load_scope_engine", return_value=engine):
        result = submit_review_trigger(
            trigger,
            grant_scope="protocol_draft",
            reviewer_id="protocol_owner",
        )

    assert result.error is None
    assert calls["reviewer"] == {"reviewer_id": "protocol_owner", "role": "protocol_owner"}
    assert calls["decision"]["type"] == "approve_narrower_scope"
    assert calls["decision"]["approved_scope"] == "protocol_draft"


def test_python_import_missing_from_policy_dir_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo = tmp_path / "scope_no_factory"
    repo.mkdir()
    (repo / "scope.py").write_text("class ScopeEngine:\n    pass\n", encoding="utf-8")
    monkeypatch.setenv("SCOPE_REPO_PATH", str(repo))
    monkeypatch.delenv("SCOPE_CLI", raising=False)

    result = submit_review_trigger({
        "review_trigger_id": "AKTA-REVTRIG-LIVE03",
        "requested_scope": "protocol_draft",
    })
    assert result.adapter_mode == ADAPTER_MODE_PYTHON_IMPORT
    assert result.error is not None
    assert "from_policy_dir" in result.error


def test_python_import_invalid_grant_rejected(
    monkeypatch: pytest.MonkeyPatch,
    scope_repo_path: Path,
) -> None:
    trigger = {
        "review_trigger_id": "AKTA-REVTRIG-LIVE04",
        "requested_scope": "active_protocol_update",
    }
    monkeypatch.setenv("SCOPE_REPO_PATH", str(scope_repo_path))
    monkeypatch.delenv("SCOPE_CLI", raising=False)

    engine = MockScopeEngineV05()
    with patch("adapters.scope.client._load_scope_engine", return_value=engine):
        result = submit_review_trigger(trigger, grant_scope="robot_queue_submission")

    assert result.error is not None


@pytest.mark.integration
@pytest.mark.skipif(not SCOPE_SIBLING.is_dir(), reason="Sibling SCOPE repo not present")
def test_python_import_smoke_against_sibling_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    """Optional live smoke when ../SCOPE exists."""
    monkeypatch.setenv("SCOPE_REPO_PATH", str(SCOPE_SIBLING))
    monkeypatch.delenv("SCOPE_CLI", raising=False)

    trigger = {
        "review_trigger_id": "AKTA-REVTRIG-SMOKE01",
        "review_trigger_version": "0.3",
        "requested_scope": "active_protocol_update",
        "required_review_role": "protocol_owner",
        "blocked_tools": ["protocol_editor.update_active_protocol"],
        "policy_hash": "sha256:" + "a" * 64,
    }
    record_path = ROOT / "examples" / "integrated_protocol_drift" / "akta_record_active_update.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["review_trigger"] = trigger
    result = submit_review_trigger(
        trigger,
        record=record,
        grant_scope="protocol_draft",
        reviewer_id="protocol_owner",
    )
    assert result.adapter_mode == ADAPTER_MODE_PYTHON_IMPORT
    if result.error:
        pytest.skip(f"SCOPE smoke skipped: {result.error}")
    assert result.review_packet is not None
    assert result.review_packet.get("packet_id")
    assert result.decision is not None
    assert result.decision.get("decision_id")
    assert result.grant is not None
    assert result.grant["authorization"]["approved_scope"] == "protocol_draft"
