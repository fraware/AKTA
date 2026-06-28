"""SCOPE adapter — simulated, python-import, or real CLI client (v0.5)."""

from __future__ import annotations

import importlib
import importlib.util
import json
import logging
import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from akta.scope_contract import (
    _scope_grant_approved_scope,
    _scope_grant_requested_scope,
    assemble_review_packet,
    validate_approval_grant,
)

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


def _akta_repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _resolve_scope_repo_root(explicit: Path | None = None) -> Path | None:
    """Locate SCOPE repo root for PYTHONPATH isolation (AKTA also owns ``adapters``)."""
    if explicit is not None:
        return explicit.resolve()
    env_path = os.environ.get("SCOPE_REPO_PATH")
    if env_path:
        return Path(env_path).resolve()
    try:
        from importlib.metadata import files as dist_files

        for dist_file in dist_files("scope-protocol") or ():
            if not dist_file.is_file():
                continue
            normalized = str(dist_file).replace("\\", "/")
            if normalized.endswith("scope/__init__.py"):
                return Path(str(dist_file.locate())).resolve().parent.parent
    except Exception:
        logger.debug("Could not resolve scope-protocol install location", exc_info=True)
    sibling = _akta_repo_root().parent / "SCOPE"
    if (sibling / "scope" / "__init__.py").is_file():
        return sibling.resolve()
    return None


def _scope_subprocess_env(scope_repo: Path | None = None) -> dict[str, str]:
    """Build subprocess env with SCOPE repo first on PYTHONPATH."""
    env = os.environ.copy()
    root = _resolve_scope_repo_root(scope_repo)
    if root is None:
        return env
    existing = env.get("PYTHONPATH", "")
    prefix = str(root)
    env["PYTHONPATH"] = prefix + (os.pathsep + existing if existing else "")
    return env


def _module_from_scope_repo(module_name: str, repo_str: str) -> bool:
    mod = sys.modules.get(module_name)
    if mod is None:
        return False
    mod_file = getattr(mod, "__file__", "") or ""
    return repo_str.replace("\\", "/") in mod_file.replace("\\", "/")


@contextmanager
def _scope_import_context(repo_path: Path) -> Iterator[None]:
    """Temporarily prefer SCOPE repo packages over AKTA's ``adapters`` namespace."""
    repo_str = str(repo_path.resolve())
    saved_path = sys.path.copy()
    saved_modules: dict[str, Any] = {}

    for name in list(sys.modules):
        if not (
            name == "adapters"
            or name.startswith("adapters.")
            or name == "scope"
            or name.startswith("scope.")
        ):
            continue
        if _module_from_scope_repo(name, repo_str):
            continue
        saved_modules[name] = sys.modules.pop(name)

    if repo_str not in sys.path:
        sys.path.insert(0, repo_str)

    try:
        yield
    finally:
        for name in list(sys.modules):
            if _module_from_scope_repo(name, repo_str):
                del sys.modules[name]
        sys.path[:] = saved_path
        sys.modules.update(saved_modules)


def _discover_scope_engine_class(repo_path: Path) -> type[Any]:
    """Import ScopeEngine from SCOPE repo."""
    scope_file = repo_path / "scope.py"
    scope_pkg = repo_path / "scope" / "__init__.py"
    if scope_file.is_file():
        spec = importlib.util.spec_from_file_location("akta_scope_bridge", scope_file)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load scope module from {repo_path}")
        scope_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(scope_mod)
    elif scope_pkg.is_file():
        scope_mod = importlib.import_module("scope")
    else:
        raise ImportError(f"No scope.py or scope/ package found in {repo_path}")

    if hasattr(scope_mod, "ScopeEngine"):
        return scope_mod.ScopeEngine
    for attr in ("Scope", "ReviewEngine", "ScopeReviewEngine"):
        if hasattr(scope_mod, attr):
            return getattr(scope_mod, attr)
    raise ImportError(f"No ScopeEngine-compatible class found in {repo_path}")


def _load_scope_engine(repo_path: Path) -> Any:
    """Construct SCOPE v0.5 engine via ScopeEngine.from_policy_dir."""
    engine_cls = _discover_scope_engine_class(repo_path)
    if not hasattr(engine_cls, "from_policy_dir"):
        raise ImportError(
            f"ScopeEngine in {repo_path} lacks from_policy_dir (SCOPE v0.5 required)"
        )
    policy_dir = repo_path / "policy"
    if not policy_dir.is_dir():
        raise ImportError(f"SCOPE policy directory not found: {policy_dir}")
    return engine_cls.from_policy_dir(policy_dir)


def _reviewer_role(trigger: dict[str, Any]) -> str:
    return str(trigger.get("required_review_role") or "protocol_owner")


def _decision_input_for_grant(granted: str, trigger: dict[str, Any]) -> dict[str, Any]:
    requested = trigger.get("requested_scope", "protocol_draft")
    if granted == requested:
        return {
            "type": "approve_scope",
            "approved_scope": granted,
            "rationale": "Approved at requested scope.",
        }
    return {
        "type": "approve_narrower_scope",
        "approved_scope": granted,
        "rationale": (
            f"Narrow approval from {requested} to {granted} per protocol owner review."
        ),
    }


def _validate_scope_chain_grant(
    grant: dict[str, Any],
    trigger: dict[str, Any],
    record: dict[str, Any] | None,
) -> str | None:
    approved = _scope_grant_approved_scope(grant)
    requested = _scope_grant_requested_scope(grant, record, trigger)
    if not approved:
        return "SCOPE grant missing approved_scope (granted_scope or authorization.approved_scope)"
    if not requested:
        return "SCOPE grant missing requested_scope for validation"
    try:
        validate_approval_grant(granted_scope=approved, requested_scope=requested)
    except ValueError as exc:
        return str(exc)
    return None


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

    reviewer = {"reviewer_id": reviewer_id, "role": _reviewer_role(trigger)}
    decision_input = _decision_input_for_grant(granted, trigger)

    try:
        with _scope_import_context(repo_path):
            engine = _load_scope_engine(repo_path)
            packet = engine.create_packet(akta_record=record, akta_trigger=trigger)
            decision = engine.submit_decision(packet, reviewer=reviewer, decision=decision_input)
            grant = engine.issue_grant(packet, decision)
    except ImportError as exc:
        return ScopeAdapterResult(
            adapter_mode=ADAPTER_MODE_PYTHON_IMPORT,
            error=f"SCOPE python-import failed: {exc}",
        )
    except Exception as exc:
        return ScopeAdapterResult(
            adapter_mode=ADAPTER_MODE_PYTHON_IMPORT,
            error=f"SCOPE engine invocation failed: {exc}",
        )

    validation_error = _validate_scope_chain_grant(grant, trigger, record)
    if validation_error:
        return ScopeAdapterResult(
            adapter_mode=ADAPTER_MODE_PYTHON_IMPORT,
            review_packet=packet,
            grant=grant,
            decision=decision,
            error=validation_error,
        )

    return ScopeAdapterResult(
        adapter_mode=ADAPTER_MODE_PYTHON_IMPORT,
        review_packet=packet,
        grant=grant,
        decision=decision,
    )


def _run_scope_cli(
    cmd: list[str],
    *,
    scope_repo: Path | None = None,
) -> subprocess.CompletedProcess[str] | ScopeAdapterResult:
    scope_root = _resolve_scope_repo_root(scope_repo)
    run_kwargs: dict[str, Any] = {
        "capture_output": True,
        "text": True,
        "timeout": 60,
        "check": False,
        "env": _scope_subprocess_env(scope_root),
    }
    if scope_root is not None:
        run_kwargs["cwd"] = scope_root
    try:
        proc = subprocess.run(cmd, **run_kwargs)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return ScopeAdapterResult(adapter_mode=ADAPTER_MODE_CLI, error=str(exc))
    if proc.returncode != 0:
        step = " ".join(cmd[1:3]) if len(cmd) >= 3 else "scope"
        return ScopeAdapterResult(
            adapter_mode=ADAPTER_MODE_CLI,
            error=proc.stderr.strip() or f"scope {step} exited {proc.returncode}",
        )
    return proc


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
        reviewer_path = tmp_path / "reviewer.json"
        decision_input_path = tmp_path / "decision_input.json"

        reviewer_path.write_text(
            json.dumps(
                {"reviewer_id": reviewer_id, "role": _reviewer_role(trigger)},
                indent=2,
            ),
            encoding="utf-8",
        )
        decision_input_path.write_text(
            json.dumps(_decision_input_for_grant(granted, trigger), indent=2),
            encoding="utf-8",
        )

        packet_cmd = [
            cli,
            "packet",
            "create",
            "--akta-trigger",
            str(trigger_path),
            "--out",
            str(packet_path),
        ]
        if record is not None:
            record_path = tmp_path / "akta_record.json"
            record_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
            packet_cmd.extend(["--akta-record", str(record_path)])

        result = _run_scope_cli(packet_cmd)
        if isinstance(result, ScopeAdapterResult):
            return result

        decision_cmd = [
            cli,
            "decision",
            "submit",
            "--packet",
            str(packet_path),
            "--reviewer",
            str(reviewer_path),
            "--decision",
            str(decision_input_path),
            "--out",
            str(decision_path),
        ]
        result = _run_scope_cli(decision_cmd)
        if isinstance(result, ScopeAdapterResult):
            return result

        grant_cmd = [
            cli,
            "grant",
            "issue",
            "--packet",
            str(packet_path),
            "--decision",
            str(decision_path),
            "--out",
            str(grant_path),
        ]
        result = _run_scope_cli(grant_cmd)
        if isinstance(result, ScopeAdapterResult):
            return result

        try:
            packet = json.loads(packet_path.read_text(encoding="utf-8"))
            decision = json.loads(decision_path.read_text(encoding="utf-8"))
            grant = json.loads(grant_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            return ScopeAdapterResult(adapter_mode=ADAPTER_MODE_CLI, error=str(exc))

    validation_error = _validate_scope_chain_grant(grant, trigger, record)
    if validation_error:
        return ScopeAdapterResult(
            adapter_mode=ADAPTER_MODE_CLI,
            review_packet=packet,
            grant=grant,
            decision=decision,
            error=validation_error,
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
        "adapter_mode": ADAPTER_MODE_SIMULATED,
    }
    decision = {
        "status": "granted",
        "granted_scope": granted,
        "reviewer_id": reviewer_id,
        "adapter_mode": ADAPTER_MODE_SIMULATED,
    }
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
