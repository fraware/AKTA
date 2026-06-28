"""Live SCOPE CLI chain contract tests (v0.7)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from adapters.scope.client import ADAPTER_MODE_CLI, ScopeAdapterResult
from scripts.verify_scope_live_chain import verify_live_scope_chain

ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "real_scope_v06"
SCOPE_SIBLING = ROOT.parent / "SCOPE"


def _fixture_scope_result() -> ScopeAdapterResult:
    return ScopeAdapterResult(
        adapter_mode=ADAPTER_MODE_CLI,
        review_packet=json.loads((FIXTURES / "scope_review_packet.json").read_text(encoding="utf-8")),
        decision=json.loads((FIXTURES / "scope_decision.json").read_text(encoding="utf-8")),
        grant=json.loads((FIXTURES / "scope_grant.json").read_text(encoding="utf-8")),
    )


def test_verify_live_chain_cli_mock(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SCOPE_CLI", "scope-mock")
    with patch(
        "adapters.scope.client.submit_review_trigger",
        return_value=_fixture_scope_result(),
    ):
        report = verify_live_scope_chain(mode="cli", scope_cli="scope-mock")
    assert report["adapter_mode"] == ADAPTER_MODE_CLI
    assert report["passed"] is True


@pytest.mark.integration
@pytest.mark.skipif(not SCOPE_SIBLING.is_dir(), reason="Sibling SCOPE repo not present")
def test_verify_live_chain_cli_against_sibling(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCOPE_CLI", "scope")
    report = verify_live_scope_chain(mode="cli", scope_cli="scope")
    if report.get("error"):
        pytest.skip(f"SCOPE CLI live chain skipped: {report['error']}")
    assert report.get("adapter_mode") == ADAPTER_MODE_CLI
