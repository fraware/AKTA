"""SCOPE akta-review CLI adapter contract tests (v0.7)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from adapters.scope.client import (
    ADAPTER_MODE_AKTA_REVIEW_CLI,
    SCOPE_CLI_MODE_AKTA_REVIEW,
    submit_review_trigger,
)

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "fixtures" / "scope_akta_review"


def _summary_fixture(out_dir: Path) -> dict[str, Any]:
    packet_path = out_dir / "scope_review_packet.json"
    decision_path = out_dir / "scope_decision.json"
    grant_path = out_dir / "scope_grant.json"
    packet_path.write_text(
        json.dumps({
            "packet_id": "SCOPE-PKT-AKTA-REVIEW01",
            "review_request": {"requested_scope": "single_run_queue_priority"},
        }),
        encoding="utf-8",
    )
    decision_path.write_text(
        json.dumps({
            "decision_id": "SCOPE-DEC-AKTA-REVIEW01",
            "decision": {
                "type": "approve",
                "approved_scope": "single_run_queue_priority",
            },
        }),
        encoding="utf-8",
    )
    grant_path.write_text(
        json.dumps({
            "grant_id": "SCOPE-GRANT-AKTA-REVIEW01",
            "authorization": {
                "approved_scope": "single_run_queue_priority",
                "blocked_tools": ["robot_queue.submit"],
            },
            "source": {"requested_scope": "single_run_queue_priority"},
        }),
        encoding="utf-8",
    )
    summary = {
        "status": "completed",
        "packet_path": str(packet_path),
        "decision_path": str(decision_path),
        "grant_path": str(grant_path),
        "approved_scope": "single_run_queue_priority",
        "requested_scope": "single_run_queue_priority",
        "adapter_contract_version": "scope-akta-review-v0.7",
        "identity_assurance_level": "IAL0",
        "signing_assurance_level": "SAL1",
        "scope_trust_root_hash": "sha256:" + ("a" * 64),
        "blocked_tools": ["robot_queue.submit"],
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def _make_akta_review_side_effect() -> tuple[Any, list[list[str]]]:
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        proc = type("Proc", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        if cmd[1:3] == ["akta", "review"]:
            out_dir = Path(cmd[cmd.index("--out-dir") + 1])
            _summary_fixture(out_dir)
        return proc

    return fake_run, calls


def test_scope_akta_review_cli_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    trigger = {
        "review_trigger_id": "AKTA-REVTRIG-AKTA-REVIEW01",
        "requested_scope": "single_run_queue_priority",
        "required_review_role": "lab_manager",
    }
    record = {"record_id": "AKTA-SAR-AKTA-REVIEW01", "review_trigger": trigger}
    monkeypatch.setenv("SCOPE_CLI", "scope")
    monkeypatch.setenv("SCOPE_CLI_MODE", SCOPE_CLI_MODE_AKTA_REVIEW)
    monkeypatch.delenv("SCOPE_REPO_PATH", raising=False)

    side_effect, calls = _make_akta_review_side_effect()
    with patch("adapters.scope.client.subprocess.run", side_effect=side_effect):
        result = submit_review_trigger(
            trigger,
            record=record,
            grant_scope="single_run_queue_priority",
            reviewer_id="lab_manager",
        )

    assert result.adapter_mode == ADAPTER_MODE_AKTA_REVIEW_CLI
    assert result.error is None
    assert len(calls) == 1
    review_cmd = calls[0]
    assert review_cmd[:3] == ["scope", "akta", "review"]
    assert "--akta-trigger" in review_cmd
    assert "--akta-record" in review_cmd
    assert "--grant-scope" in review_cmd
    assert "--decision-rationale" in review_cmd
    assert "--out-dir" in review_cmd
    assert review_cmd[review_cmd.index("--grant-scope") + 1] == "single_run_queue_priority"

    assert result.grant is not None
    assert result.decision is not None
    assert result.review_packet is not None
    assert result.grant["authorization"]["approved_scope"] == "single_run_queue_priority"
    assert result.grant["authorization"]["blocked_tools"] == ["robot_queue.submit"]


def test_scope_akta_review_cli_validates_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    trigger = {
        "review_trigger_id": "AKTA-REVTRIG-AKTA-REVIEW02",
        "requested_scope": "single_run_queue_priority",
    }
    monkeypatch.setenv("SCOPE_CLI", "scope")
    monkeypatch.setenv("SCOPE_CLI_MODE", SCOPE_CLI_MODE_AKTA_REVIEW)
    monkeypatch.delenv("SCOPE_REPO_PATH", raising=False)

    def bad_summary_run(cmd, **kwargs):
        proc = type("Proc", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        if cmd[1:3] == ["akta", "review"]:
            out_dir = Path(cmd[cmd.index("--out-dir") + 1])
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "summary.json").write_text(
                json.dumps({"status": "completed"}),
                encoding="utf-8",
            )
        return proc

    with patch("adapters.scope.client.subprocess.run", side_effect=bad_summary_run):
        result = submit_review_trigger(trigger, grant_scope="single_run_queue_priority")

    assert result.adapter_mode == ADAPTER_MODE_AKTA_REVIEW_CLI
    assert result.error is not None


def test_scope_akta_review_cli_keeps_three_step_mode_without_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trigger = {
        "review_trigger_id": "AKTA-REVTRIG-CLI-LEGACY",
        "requested_scope": "protocol_draft",
    }
    monkeypatch.setenv("SCOPE_CLI", "scope")
    monkeypatch.delenv("SCOPE_CLI_MODE", raising=False)
    monkeypatch.delenv("SCOPE_REPO_PATH", raising=False)

    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        proc = type("Proc", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        if cmd[1:3] == ["packet", "create"]:
            trigger_path = Path(cmd[cmd.index("--akta-trigger") + 1])
            trigger_data = json.loads(trigger_path.read_text(encoding="utf-8"))
            out = Path(cmd[cmd.index("--out") + 1])
            out.write_text(
                json.dumps({
                    "packet_id": "SCOPE-PKT-LEGACY",
                    "review_request": {"requested_scope": trigger_data["requested_scope"]},
                }),
                encoding="utf-8",
            )
        elif cmd[1:3] == ["decision", "submit"]:
            decision_input = json.loads(Path(cmd[cmd.index("--decision") + 1]).read_text())
            out = Path(cmd[cmd.index("--out") + 1])
            out.write_text(
                json.dumps({
                    "decision_id": "SCOPE-DEC-LEGACY",
                    "decision": decision_input,
                }),
                encoding="utf-8",
            )
        elif cmd[1:3] == ["grant", "issue"]:
            out = Path(cmd[cmd.index("--out") + 1])
            out.write_text(
                json.dumps({
                    "grant_id": "SCOPE-GRANT-LEGACY",
                    "authorization": {"approved_scope": "protocol_draft"},
                    "source": {"requested_scope": "protocol_draft"},
                }),
                encoding="utf-8",
            )
        return proc

    with patch("adapters.scope.client.subprocess.run", side_effect=fake_run):
        result = submit_review_trigger(trigger, grant_scope="protocol_draft")

    assert result.adapter_mode == "cli"
    assert len(calls) == 3
    assert calls[0][1:3] == ["packet", "create"]
