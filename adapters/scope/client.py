"""SCOPE adapter — simulated, python-import, or real CLI client (v0.5)."""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from akta.scope_contract import assemble_review_packet, validate_approval_grant

logger = logging.getLogger(__name__)

ADAPTER_MODE_SIMULATED = "simulated"
ADAPTER_MODE_PYTHON_IMPORT = "python-import"
ADAPTER_MODE_CLI = "cli"


@dataclass
class ScopeAdapterResult:
    adapter_mode: str
    review_packet: dict[str, Any] | None = None
    grant: dict[str, Any] | None = None
    decision: dict[str, Any] | None = None
    error: str | None = None


def detect_adapter_mode() -> str:
    """Auto-detect SCOPE adapter mode from environment."""
    if os.environ.get("SCOPE_REPO_PATH"):
        return ADAPTER_MODE_PYTHON_IMPORT
    if os.environ.get("SCOPE_CLI"):
        return ADAPTER_MODE_CLI
    return ADAPTER_MODE_SIMULATED


def _discover_scope_engine_class(repo_path: Path) -> type[Any]:
    """Import ScopeEngine from SCOPE repo or discover equivalent class."""
    import importlib.util

    scope_file = repo_path / "scope.py"
    scope_pkg = repo_path / "scope" / "__init__.py"
    if scope_file.is_file():
        spec = importlib.util.spec_from_file_location("akta_scope_bridge", scope_file)
    elif scope_pkg.is_file():
        spec = importlib.util.spec_from_file_location(
            "akta_scope_bridge",
            scope_pkg,
            submodule_search_locations=[str(repo_path / "scope")],
        )
    else:
        raise ImportError(f"No scope.py or scope/ package found in {repo_path}")

    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load scope module from {repo_path}")

    scope_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scope_mod)

    if hasattr(scope_mod, "ScopeEngine"):
        return scope_mod.ScopeEngine
    for attr in ("Scope", "ReviewEngine", "ScopeReviewEngine"):
        if hasattr(scope_mod, attr):
            return getattr(scope_mod, attr)
    raise ImportError(f"No ScopeEngine-compatible class found in {repo_path}")


def _python_import_scope(
    trigger: dict[str, Any],
    record: dict[str, Any] | None,
    granted: str,
    reviewer_id: str,
) -> ScopeAdapterResult:
    repo_path = Path(os.environ["SCOPE_REPO_PATH"])
    if not repo_path.is_dir():
        return ScopeAdapterResult(
            adapter_mode=ADAPTER_MODE_PYTHON_IMPORT,
            error=f"SCOPE_REPO_PATH is not a directory: {repo_path}",
        )
    try:
        engine_cls = _discover_scope_engine_class(repo_path)
        engine = engine_cls()
    except ImportError as exc:
        return ScopeAdapterResult(adapter_mode=ADAPTER_MODE_PYTHON_IMPORT, error=str(exc))

    try:
        if hasattr(engine, "create_packet"):
            packet = engine.create_packet(trigger, record=record)
        elif hasattr(engine, "packet_create"):
            packet = engine.packet_create(trigger, record)
        else:
            packet = assemble_review_packet(trigger, record)

        if hasattr(engine, "submit_decision"):
            decision = engine.submit_decision(
                packet, granted_scope=granted, reviewer_id=reviewer_id
            )
        elif hasattr(engine, "decision_submit"):
            decision = engine.decision_submit(packet, granted, reviewer_id)
        else:
            decision = {"status": "granted", "granted_scope": granted, "reviewer_id": reviewer_id}

        if hasattr(engine, "issue_grant"):
            grant = engine.issue_grant(decision, trigger=trigger)
        elif hasattr(engine, "grant_issue"):
            grant = engine.grant_issue(decision, trigger)
        else:
            grant = {
                "grant_id": f"SCOPE-GRANT-{trigger.get('review_trigger_id', 'UNKNOWN')}",
                "granted_scope": granted,
                "requested_scope": trigger.get("requested_scope"),
                "reviewer_id": reviewer_id,
                "review_trigger_id": trigger.get("review_trigger_id"),
            }
    except Exception as exc:
        return ScopeAdapterResult(adapter_mode=ADAPTER_MODE_PYTHON_IMPORT, error=str(exc))

    requested_scope = trigger.get("requested_scope", "protocol_draft")
    try:
        validate_approval_grant(granted_scope=granted, requested_scope=requested_scope)
    except ValueError as exc:
        return ScopeAdapterResult(
            adapter_mode=ADAPTER_MODE_PYTHON_IMPORT,
            review_packet=packet,
            grant=grant,
            decision=decision,
            error=str(exc),
        )

    return ScopeAdapterResult(
        adapter_mode=ADAPTER_MODE_PYTHON_IMPORT,
        review_packet=packet,
        grant=grant,
        decision=decision,
    )


def _cli_scope(
    trigger: dict[str, Any],
    record: dict[str, Any] | None,
    granted: str,
    reviewer_id: str,
) -> ScopeAdapterResult:
    cli = os.environ.get("SCOPE_CLI", "scope")
    with tempfile.TemporaryDirectory(prefix="akta-scope-") as tmp:
        tmp_path = Path(tmp)
        trigger_path = tmp_path / "review_trigger.json"
        trigger_path.write_text(json.dumps(trigger, indent=2), encoding="utf-8")
        packet_path = tmp_path / "scope_review_packet.json"
        decision_path = tmp_path / "scope_decision.json"
        grant_path = tmp_path / "scope_grant.json"

        packet_cmd = [
            cli,
            "packet",
            "create",
            "--trigger",
            str(trigger_path),
            "--out",
            str(packet_path),
        ]
        if record is not None:
            record_path = tmp_path / "akta_record.json"
            record_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
            packet_cmd.extend(["--record", str(record_path)])

        try:
            proc = subprocess.run(
                packet_cmd,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            return ScopeAdapterResult(adapter_mode=ADAPTER_MODE_CLI, error=str(exc))

        if proc.returncode != 0:
            return ScopeAdapterResult(
                adapter_mode=ADAPTER_MODE_CLI,
                error=proc.stderr or f"scope packet create exited {proc.returncode}",
            )

        decision_cmd = [
            cli,
            "decision",
            "submit",
            "--packet",
            str(packet_path),
            "--grant-scope",
            granted,
            "--reviewer",
            reviewer_id,
            "--out",
            str(decision_path),
        ]
        try:
            proc = subprocess.run(
                decision_cmd,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            return ScopeAdapterResult(adapter_mode=ADAPTER_MODE_CLI, error=str(exc))

        if proc.returncode != 0:
            return ScopeAdapterResult(
                adapter_mode=ADAPTER_MODE_CLI,
                error=proc.stderr or f"scope decision submit exited {proc.returncode}",
            )

        grant_cmd = [
            cli,
            "grant",
            "issue",
            "--decision",
            str(decision_path),
            "--out",
            str(grant_path),
        ]
        try:
            proc = subprocess.run(
                grant_cmd,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            return ScopeAdapterResult(adapter_mode=ADAPTER_MODE_CLI, error=str(exc))

        if proc.returncode != 0:
            return ScopeAdapterResult(
                adapter_mode=ADAPTER_MODE_CLI,
                error=proc.stderr or f"scope grant issue exited {proc.returncode}",
            )

        try:
            packet = json.loads(packet_path.read_text(encoding="utf-8"))
            decision = json.loads(decision_path.read_text(encoding="utf-8"))
            grant = json.loads(grant_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            return ScopeAdapterResult(adapter_mode=ADAPTER_MODE_CLI, error=str(exc))

    requested_scope = trigger.get("requested_scope", "protocol_draft")
    try:
        validate_approval_grant(granted_scope=granted, requested_scope=requested_scope)
    except ValueError as exc:
        return ScopeAdapterResult(
            adapter_mode=ADAPTER_MODE_CLI,
            review_packet=packet,
            grant=grant,
            decision=decision,
            error=str(exc),
        )

    return ScopeAdapterResult(
        adapter_mode=ADAPTER_MODE_CLI,
        review_packet=packet,
        grant=grant,
        decision=decision,
    )


def _simulated_scope(
    trigger: dict[str, Any],
    granted: str,
    reviewer_id: str,
) -> ScopeAdapterResult:
    logger.info("SCOPE adapter mode: simulated (contract-simulation only)")
    requested_scope = trigger.get("requested_scope", "protocol_draft")
    packet = assemble_review_packet(trigger)
    grant = {
        "grant_id": f"SCOPE-GRANT-{trigger.get('review_trigger_id', 'UNKNOWN')}",
        "granted_scope": granted,
        "requested_scope": requested_scope,
        "reviewer_id": reviewer_id,
        "review_trigger_id": trigger.get("review_trigger_id"),
    }
    decision = {"status": "granted", "granted_scope": granted, "reviewer_id": reviewer_id}
    try:
        validate_approval_grant(granted_scope=granted, requested_scope=requested_scope)
    except ValueError as exc:
        return ScopeAdapterResult(
            adapter_mode=ADAPTER_MODE_SIMULATED,
            review_packet=packet,
            grant=grant,
            decision=decision,
            error=str(exc),
        )
    return ScopeAdapterResult(
        adapter_mode=ADAPTER_MODE_SIMULATED,
        review_packet=packet,
        grant=grant,
        decision=decision,
    )


def submit_review_trigger(
    trigger: dict[str, Any],
    *,
    record: dict[str, Any] | None = None,
    grant_scope: str | None = None,
    reviewer_id: str = "scope_reviewer",
) -> ScopeAdapterResult:
    """Submit AKTA review trigger to SCOPE (simulated, python-import, or CLI)."""
    mode = detect_adapter_mode()
    requested_scope = trigger.get("requested_scope", "protocol_draft")
    granted = grant_scope or requested_scope

    if mode == ADAPTER_MODE_PYTHON_IMPORT:
        logger.info("SCOPE adapter mode: python-import (SCOPE_REPO_PATH)")
        return _python_import_scope(trigger, record, granted, reviewer_id)
    if mode == ADAPTER_MODE_CLI:
        logger.info("SCOPE adapter mode: cli (SCOPE_CLI=%s)", os.environ.get("SCOPE_CLI", "scope"))
        return _cli_scope(trigger, record, granted, reviewer_id)

    return _simulated_scope(trigger, granted, reviewer_id)
