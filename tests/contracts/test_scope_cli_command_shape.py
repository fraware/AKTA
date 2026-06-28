"""SCOPE CLI adapter contract tests (v0.5 command shapes)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from adapters.scope.client import ADAPTER_MODE_CLI, submit_review_trigger


def _make_cli_side_effect() -> tuple:
    """Simulate scope packet create / decision submit / grant issue CLI chain."""
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        proc = type("Proc", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        if cmd[1:3] == ["packet", "create"]:
            trigger_path = Path(cmd[cmd.index("--akta-trigger") + 1])
            trigger = json.loads(trigger_path.read_text(encoding="utf-8"))
            out = Path(cmd[cmd.index("--out") + 1])
            out.write_text(
                json.dumps({
                    "packet_id": "SCOPE-PKT-CLI01",
                    "packet_type": "scope_review_packet",
                    "review_request": {"requested_scope": trigger.get("requested_scope")},
                }),
                encoding="utf-8",
            )
        elif cmd[1:3] == ["decision", "submit"]:
            decision_input = json.loads(
                Path(cmd[cmd.index("--decision") + 1]).read_text(encoding="utf-8")
            )
            reviewer = json.loads(Path(cmd[cmd.index("--reviewer") + 1]).read_text(encoding="utf-8"))
            out = Path(cmd[cmd.index("--out") + 1])
            out.write_text(
                json.dumps({
                    "decision_id": "SCOPE-DEC-CLI01",
                    "decision": decision_input,
                    "reviewer": reviewer,
                }),
                encoding="utf-8",
            )
        elif cmd[1:3] == ["grant", "issue"]:
            packet = json.loads(Path(cmd[cmd.index("--packet") + 1]).read_text(encoding="utf-8"))
            decision = json.loads(Path(cmd[cmd.index("--decision") + 1]).read_text(encoding="utf-8"))
            approved = decision["decision"]["approved_scope"]
            out = Path(cmd[cmd.index("--out") + 1])
            out.write_text(
                json.dumps({
                    "grant_id": "SCOPE-GRANT-CLI01",
                    "authorization": {"approved_scope": approved},
                    "source": {
                        "requested_scope": packet["review_request"]["requested_scope"],
                    },
                }),
                encoding="utf-8",
            )
        return proc

    return fake_run, calls


def test_scope_cli_v05_command_shapes(monkeypatch: pytest.MonkeyPatch) -> None:
    trigger = {
        "review_trigger_id": "AKTA-REVTRIG-CLI01",
        "requested_scope": "active_protocol_update",
        "required_review_role": "protocol_owner",
    }
    record = {"record_id": "AKTA-SAR-CLI01", "review_trigger": trigger}
    monkeypatch.setenv("SCOPE_CLI", "scope")
    monkeypatch.delenv("SCOPE_REPO_PATH", raising=False)

    side_effect, calls = _make_cli_side_effect()
    captured: dict[str, Any] = {}

    def fake_run_with_capture(cmd, **kwargs):
        proc = side_effect(cmd, **kwargs)
        if cmd[1:3] == ["decision", "submit"]:
            captured["reviewer"] = json.loads(
                Path(cmd[cmd.index("--reviewer") + 1]).read_text(encoding="utf-8")
            )
            captured["decision_input"] = json.loads(
                Path(cmd[cmd.index("--decision") + 1]).read_text(encoding="utf-8")
            )
        return proc

    with patch("adapters.scope.client.subprocess.run", side_effect=fake_run_with_capture):
        result = submit_review_trigger(
            trigger,
            record=record,
            grant_scope="protocol_draft",
            reviewer_id="protocol_owner",
        )

    assert result.adapter_mode == ADAPTER_MODE_CLI
    assert result.error is None
    assert len(calls) == 3

    packet_cmd = calls[0]
    assert packet_cmd[:4] == ["scope", "packet", "create", "--akta-trigger"]
    assert "--akta-record" in packet_cmd
    assert "--out" in packet_cmd
    assert "--trigger" not in packet_cmd
    assert "--grant-scope" not in packet_cmd

    decision_cmd = calls[1]
    assert decision_cmd[:4] == ["scope", "decision", "submit", "--packet"]
    assert "--reviewer" in decision_cmd
    assert "--decision" in decision_cmd
    assert "--grant-scope" not in decision_cmd

    grant_cmd = calls[2]
    assert grant_cmd[:4] == ["scope", "grant", "issue", "--packet"]
    assert "--decision" in grant_cmd
    assert grant_cmd[grant_cmd.index("--decision") + 1].endswith("scope_decision.json")

    reviewer_path = Path(decision_cmd[decision_cmd.index("--reviewer") + 1])
    assert reviewer_path.name == "reviewer.json"
    reviewer = captured["reviewer"]
    decision_input = captured["decision_input"]
    assert reviewer == {"reviewer_id": "protocol_owner", "role": "protocol_owner"}
    assert decision_input["type"] == "approve_narrower_scope"
    assert decision_input["approved_scope"] == "protocol_draft"

    assert result.grant is not None
    assert result.grant["authorization"]["approved_scope"] == "protocol_draft"


def test_scope_cli_invalid_grant_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    trigger = {
        "review_trigger_id": "AKTA-REVTRIG-CLI02",
        "requested_scope": "active_protocol_update",
    }
    monkeypatch.setenv("SCOPE_CLI", "scope")
    monkeypatch.delenv("SCOPE_REPO_PATH", raising=False)

    side_effect, _ = _make_cli_side_effect()
    with patch("adapters.scope.client.subprocess.run", side_effect=side_effect):
        result = submit_review_trigger(trigger, grant_scope="robot_queue_submission")

    assert result.adapter_mode == ADAPTER_MODE_CLI
    assert result.error is not None


def test_scope_cli_missing_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    trigger = {
        "review_trigger_id": "AKTA-REVTRIG-CLI03",
        "requested_scope": "protocol_draft",
    }
    monkeypatch.setenv("SCOPE_CLI", "nonexistent-scope-cli-xyz")
    monkeypatch.delenv("SCOPE_REPO_PATH", raising=False)

    with patch(
        "adapters.scope.client.subprocess.run",
        side_effect=FileNotFoundError("scope not found"),
    ):
        result = submit_review_trigger(trigger)

    assert result.adapter_mode == ADAPTER_MODE_CLI
    assert result.error is not None
