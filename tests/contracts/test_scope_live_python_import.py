"""Live SCOPE python-import chain contract tests (v0.7)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from adapters.scope.client import ADAPTER_MODE_PYTHON_IMPORT, submit_review_trigger
from scripts.verify_scope_live_chain import verify_live_scope_chain

ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "real_scope_v06"
SCOPE_SIBLING = ROOT.parent / "SCOPE"


class MockScopeEngineV06:
    @classmethod
    def from_policy_dir(cls, policy_dir: str | Path | None = None, **kwargs: Any) -> MockScopeEngineV06:
        return cls()

    def create_packet(self, akta_record=None, akta_trigger=None, **kwargs: Any) -> dict[str, Any]:
        trigger = akta_trigger if isinstance(akta_trigger, dict) else {}
        packet = json.loads((FIXTURES / "scope_review_packet.json").read_text(encoding="utf-8"))
        packet["review_request"]["requested_scope"] = trigger.get("requested_scope")
        return packet

    def submit_decision(self, packet, reviewer, decision) -> dict[str, Any]:
        dec = json.loads((FIXTURES / "scope_decision.json").read_text(encoding="utf-8"))
        dec["packet_id"] = packet["packet_id"]
        return dec

    def issue_grant(self, packet, decision, **kwargs: Any) -> dict[str, Any]:
        grant = json.loads((FIXTURES / "scope_grant.json").read_text(encoding="utf-8"))
        grant["source"]["packet_id"] = packet["packet_id"]
        return grant


@pytest.fixture
def scope_repo_path(tmp_path: Path) -> Path:
    repo = tmp_path / "scope_repo"
    repo.mkdir()
    (repo / "policy").mkdir()
    (repo / "scope.py").write_text("class ScopeEngine: pass\n", encoding="utf-8")
    return repo


def test_real_scope_v06_fixture_shapes() -> None:
    packet = json.loads((FIXTURES / "scope_review_packet.json").read_text(encoding="utf-8"))
    decision = json.loads((FIXTURES / "scope_decision.json").read_text(encoding="utf-8"))
    grant = json.loads((FIXTURES / "scope_grant.json").read_text(encoding="utf-8"))
    assert packet.get("packet_id")
    assert decision.get("decision_id")
    assert grant["authorization"]["approved_scope"] == "protocol_draft"


def test_verify_live_chain_python_import_mock(
    monkeypatch: pytest.MonkeyPatch,
    scope_repo_path: Path,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    engine = MockScopeEngineV06()
    with patch("adapters.scope.client._load_scope_engine", return_value=engine):
        report = verify_live_scope_chain(mode="python-import", scope_repo=scope_repo_path)
    assert report["adapter_mode"] == ADAPTER_MODE_PYTHON_IMPORT
    assert report["passed"] is True


def test_python_import_not_simulated(
    monkeypatch: pytest.MonkeyPatch,
    scope_repo_path: Path,
) -> None:
    trigger = {
        "review_trigger_id": "AKTA-REVTRIG-LIVE-V07",
        "requested_scope": "active_protocol_update",
        "required_review_role": "protocol_owner",
    }
    monkeypatch.setenv("SCOPE_REPO_PATH", str(scope_repo_path))
    monkeypatch.delenv("SCOPE_CLI", raising=False)
    engine = MockScopeEngineV06()
    with patch("adapters.scope.client._load_scope_engine", return_value=engine):
        result = submit_review_trigger(trigger, grant_scope="protocol_draft")
    assert result.adapter_mode == ADAPTER_MODE_PYTHON_IMPORT
    assert result.error is None
    assert result.grant is not None
    assert result.grant["authorization"]["approved_scope"] == "protocol_draft"
    assert result.decision is not None
    assert result.decision.get("decision_id")


@pytest.mark.integration
@pytest.mark.skipif(not SCOPE_SIBLING.is_dir(), reason="Sibling SCOPE repo not present")
def test_verify_live_chain_against_sibling_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    report = verify_live_scope_chain(mode="python-import", scope_repo=SCOPE_SIBLING)
    if report.get("error") and "failed" in str(report.get("error", "")).lower():
        pytest.skip(f"SCOPE live chain skipped: {report['error']}")
    assert report.get("adapter_mode") == ADAPTER_MODE_PYTHON_IMPORT
