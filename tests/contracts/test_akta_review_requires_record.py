"""SCOPE akta-review CLI requires AKTA record (AKTA-1)."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from adapters.scope.client import (
    ADAPTER_MODE_AKTA_REVIEW_CLI,
    SCOPE_CLI_MODE_AKTA_REVIEW,
    submit_review_trigger,
)


def test_akta_review_cli_without_record_fails_before_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trigger = {
        "review_trigger_id": "AKTA-REVTRIG-NO-RECORD",
        "requested_scope": "single_run_queue_priority",
    }
    monkeypatch.setenv("SCOPE_CLI", "scope")
    monkeypatch.setenv("SCOPE_CLI_MODE", SCOPE_CLI_MODE_AKTA_REVIEW)
    monkeypatch.delenv("SCOPE_REPO_PATH", raising=False)

    with patch("adapters.scope.client.subprocess.run") as mock_run:
        result = submit_review_trigger(trigger, grant_scope="single_run_queue_priority")

    mock_run.assert_not_called()
    assert result.adapter_mode == ADAPTER_MODE_AKTA_REVIEW_CLI
    assert result.error == "SCOPE akta-review CLI mode requires an AKTA record."


def test_akta_review_cli_with_record_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    from pathlib import Path

    trigger = {
        "review_trigger_id": "AKTA-REVTRIG-WITH-RECORD",
        "requested_scope": "single_run_queue_priority",
        "required_review_role": "lab_manager",
    }
    record = {"record_id": "AKTA-SAR-WITH-RECORD", "review_trigger": trigger}
    monkeypatch.setenv("SCOPE_CLI", "scope")
    monkeypatch.setenv("SCOPE_CLI_MODE", SCOPE_CLI_MODE_AKTA_REVIEW)
    monkeypatch.delenv("SCOPE_REPO_PATH", raising=False)

    def fake_run(cmd, **kwargs):
        proc = type("Proc", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        if cmd[1:3] == ["akta", "review"]:
            out_dir = Path(cmd[cmd.index("--out-dir") + 1])
            out_dir.mkdir(parents=True, exist_ok=True)
            packet_path = out_dir / "scope_review_packet.json"
            decision_path = out_dir / "scope_decision.json"
            grant_path = out_dir / "scope_grant.json"
            packet_path.write_text(
                '{"packet_id": "SCOPE-PKT-REC", "review_request": {"requested_scope": "single_run_queue_priority"}}',
                encoding="utf-8",
            )
            decision_path.write_text(
                '{"decision_id": "SCOPE-DEC-REC", "decision": {"type": "approve", "approved_scope": "single_run_queue_priority"}}',
                encoding="utf-8",
            )
            grant_path.write_text(
                '{"grant_id": "SCOPE-GRANT-REC", "authorization": {"approved_scope": "single_run_queue_priority"}, "source": {"requested_scope": "single_run_queue_priority"}}',
                encoding="utf-8",
            )
            summary: dict[str, Any] = {
                "status": "completed",
                "packet_path": str(packet_path),
                "decision_path": str(decision_path),
                "grant_path": str(grant_path),
                "approved_scope": "single_run_queue_priority",
                "requested_scope": "single_run_queue_priority",
                "adapter_contract_version": "scope-akta-review-v0.8",
                "identity_assurance_level": "IAL0",
                "signing_assurance_level": "SAL1",
                "scope_trust_root_hash": "sha256:" + ("a" * 64),
                "allowed_tools": [],
                "blocked_tools": [],
            }
            (out_dir / "summary.json").write_text(
                __import__("json").dumps(summary, indent=2),
                encoding="utf-8",
            )
        return proc

    with patch("adapters.scope.client.subprocess.run", side_effect=fake_run) as mock_run:
        result = submit_review_trigger(
            trigger,
            record=record,
            grant_scope="single_run_queue_priority",
            reviewer_id="lab_manager",
        )

    assert mock_run.call_count == 1
    assert result.error is None
    assert result.grant is not None
    assert result.summary is not None
    assert result.summary["approved_scope"] == "single_run_queue_priority"
