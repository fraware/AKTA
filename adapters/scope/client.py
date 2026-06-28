"""SCOPE adapter — subprocess or simulated contract client."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from akta.scope_contract import assemble_review_packet, validate_approval_grant


@dataclass
class ScopeAdapterResult:
    adapter_mode: str
    review_packet: dict[str, Any] | None = None
    grant: dict[str, Any] | None = None
    decision: dict[str, Any] | None = None
    error: str | None = None


def _adapter_mode() -> str:
    if os.environ.get("SCOPE_CLI") or os.environ.get("SCOPE_REPO_PATH"):
        return "subprocess"
    return "simulated"


def submit_review_trigger(
    trigger: dict[str, Any],
    *,
    grant_scope: str | None = None,
    reviewer_id: str = "scope_reviewer",
) -> ScopeAdapterResult:
    """Submit AKTA review trigger to SCOPE or simulate approval flow."""
    mode = _adapter_mode()
    requested_scope = trigger.get("requested_scope", "protocol_draft")
    granted = grant_scope or requested_scope

    if mode == "subprocess":
        return _subprocess_scope(trigger, granted, reviewer_id)

    packet = assemble_review_packet(trigger)
    grant = {
        "grant_id": f"SCOPE-GRANT-{trigger.get('review_trigger_id', 'UNKNOWN')}",
        "granted_scope": granted,
        "requested_scope": requested_scope,
        "reviewer_id": reviewer_id,
        "review_trigger_id": trigger.get("review_trigger_id"),
    }
    try:
        validate_approval_grant(
            granted_scope=granted,
            requested_scope=requested_scope,
        )
    except ValueError as exc:
        return ScopeAdapterResult(
            adapter_mode=mode,
            review_packet=packet,
            grant=grant,
            error=str(exc),
        )
    return ScopeAdapterResult(
        adapter_mode=mode,
        review_packet=packet,
        grant=grant,
        decision={"status": "granted", "granted_scope": granted},
    )


def _subprocess_scope(
    trigger: dict[str, Any],
    granted: str,
    reviewer_id: str,
) -> ScopeAdapterResult:
    cli = os.environ.get("SCOPE_CLI", "scope")
    repo = os.environ.get("SCOPE_REPO_PATH", "")
    payload = json.dumps({"trigger": trigger, "grant_scope": granted, "reviewer_id": reviewer_id})
    cmd = [cli, "review", "--stdin"]
    if repo:
        cmd.extend(["--repo", repo])
    try:
        proc = subprocess.run(
            cmd,
            input=payload,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return ScopeAdapterResult(adapter_mode="subprocess", error=str(exc))

    if proc.returncode != 0:
        return ScopeAdapterResult(
            adapter_mode="subprocess",
            error=proc.stderr or f"SCOPE exited {proc.returncode}",
        )
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return ScopeAdapterResult(adapter_mode="subprocess", error="Invalid SCOPE JSON output")
    return ScopeAdapterResult(
        adapter_mode="subprocess",
        review_packet=result.get("review_packet"),
        grant=result.get("grant"),
        decision=result.get("decision"),
    )
