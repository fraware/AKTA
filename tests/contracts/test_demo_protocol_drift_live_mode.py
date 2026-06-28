"""Demo script adapter mode labeling and simulated path regression."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from adapters.scope.client import ADAPTER_MODE_SIMULATED, detect_adapter_mode, submit_review_trigger
from scripts.demo_akta_scope_protocol_drift import run_demo

ROOT = Path(__file__).resolve().parent.parent.parent


def test_detect_adapter_mode_simulated_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SCOPE_REPO_PATH", raising=False)
    monkeypatch.delenv("SCOPE_CLI", raising=False)
    assert detect_adapter_mode() == ADAPTER_MODE_SIMULATED


def test_simulated_grant_explicitly_labeled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SCOPE_REPO_PATH", raising=False)
    monkeypatch.delenv("SCOPE_CLI", raising=False)
    trigger = {
        "review_trigger_id": "AKTA-REVTRIG-DEMO01",
        "requested_scope": "active_protocol_update",
    }
    result = submit_review_trigger(trigger, grant_scope="protocol_draft")
    assert result.adapter_mode == ADAPTER_MODE_SIMULATED
    assert result.grant is not None
    assert result.grant.get("adapter_mode") == ADAPTER_MODE_SIMULATED
    assert result.decision is not None
    assert result.decision.get("adapter_mode") == ADAPTER_MODE_SIMULATED


def test_demo_run_simulated_mode(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("SCOPE_REPO_PATH", raising=False)
    monkeypatch.delenv("SCOPE_CLI", raising=False)
    code = run_demo()
    captured = capsys.readouterr().out
    assert code == 0
    assert "simulated (contract simulation only)" in captured
    assert "SCOPE adapter mode:" in captured

    demo_dir = ROOT / "examples" / "integrated_protocol_drift"
    grant = json.loads((demo_dir / "scope_narrow_grant.json").read_text(encoding="utf-8"))
    assert grant.get("granted_scope") == "protocol_draft" or grant.get("authorization", {}).get(
        "approved_scope"
    ) == "protocol_draft"


def test_demo_labels_python_import_mode(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SCOPE_REPO_PATH", "/nonexistent/scope-for-label-test")
    monkeypatch.delenv("SCOPE_CLI", raising=False)

    with patch(
        "adapters.scope.client.submit_review_trigger",
        return_value=type(
            "R",
            (),
            {
                "error": "SCOPE python-import failed: test",
                "review_packet": None,
                "grant": None,
                "decision": None,
                "adapter_mode": "python-import",
            },
        )(),
    ):
        code = run_demo()

    captured = capsys.readouterr().out
    assert "python-import (SCOPE_REPO_PATH sibling repo)" in captured
    assert code == 1
