"""Cross-process differential: SCOPE vs AKTA ``request_contained_by_envelope``.

Serializes grant+request vectors, evaluates in an AKTA process and a SCOPE
contracts process, then deep-compares the structured ``(ok, reason)`` result.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCOPE_ROOT = Path(os.environ.get("SCOPE_ROOT", Path.home() / "SCOPE"))
SCOPE_CONTRACTS = (
    SCOPE_ROOT
    / "scientific-authorization-contracts"
    / "src"
)

_VECTORS = [
    {
        "name": "covered_draft",
        "envelope": {
            "envelope_version": "scientific-authorization-envelope-v2",
            "capability_id": "CAP-0123456789ABCDEF0123456789ABCDEF",
            "family": "protocol",
            "operation": "draft",
            "target": {"type": "protocol", "protocol_id": "protocol-v3"},
            "allowed_tools": ["protocol_editor.draft_change"],
            "blocked_tools": ["robot_queue.submit"],
            "cardinality": {"mode": "single", "maximum_uses": 1, "maximum_items": 1},
            "environment": {"tenant_id": "tenant-a", "project_id": "project-123"},
            "responsibility_ceiling": "R4_methodological_modification",
            "constraints": {},
            "expiration": {"absolute_expiration": None, "expires_after": []},
        },
        "request": {
            "family": "protocol",
            "operation": "draft",
            "requested_tool": "protocol_editor.draft_change",
            "target": {"type": "protocol", "protocol_id": "protocol-v3"},
            "environment": {"tenant_id": "tenant-a", "project_id": "project-123"},
            "responsibility_level": "R3_recommendation",
            "item_count": 1,
        },
        "uses_consumed": 0,
    },
    {
        "name": "tool_blocked",
        "envelope": {
            "envelope_version": "scientific-authorization-envelope-v2",
            "capability_id": "CAP-0123456789ABCDEF0123456789ABCDEF",
            "family": "protocol",
            "operation": "draft",
            "target": {"type": "protocol", "protocol_id": "protocol-v3"},
            "allowed_tools": ["protocol_editor.draft_change"],
            "blocked_tools": ["protocol_editor.draft_change"],
            "cardinality": {"mode": "single", "maximum_uses": 1, "maximum_items": 1},
            "environment": {"tenant_id": "tenant-a"},
            "responsibility_ceiling": "R4_methodological_modification",
            "constraints": {},
            "expiration": {"absolute_expiration": None, "expires_after": []},
        },
        "request": {
            "family": "protocol",
            "operation": "draft",
            "requested_tool": "protocol_editor.draft_change",
            "target": {"type": "protocol", "protocol_id": "protocol-v3"},
            "environment": {"tenant_id": "tenant-a"},
            "responsibility_level": "R3_recommendation",
            "item_count": 1,
        },
        "uses_consumed": 0,
    },
    {
        "name": "wrong_tenant",
        "envelope": {
            "envelope_version": "scientific-authorization-envelope-v2",
            "capability_id": "CAP-0123456789ABCDEF0123456789ABCDEF",
            "family": "protocol",
            "operation": "draft",
            "target": {"type": "protocol", "protocol_id": "protocol-v3"},
            "allowed_tools": ["protocol_editor.draft_change"],
            "blocked_tools": [],
            "cardinality": {"mode": "single", "maximum_uses": 1, "maximum_items": 1},
            "environment": {"tenant_id": "tenant-a"},
            "responsibility_ceiling": "R4_methodological_modification",
            "constraints": {},
            "expiration": {"absolute_expiration": None, "expires_after": []},
        },
        "request": {
            "family": "protocol",
            "operation": "draft",
            "requested_tool": "protocol_editor.draft_change",
            "target": {"type": "protocol", "protocol_id": "protocol-v3"},
            "environment": {"tenant_id": "tenant-b"},
            "responsibility_level": "R3_recommendation",
            "item_count": 1,
        },
        "uses_consumed": 0,
    },
    {
        "name": "item_count_exceeded",
        "envelope": {
            "envelope_version": "scientific-authorization-envelope-v2",
            "capability_id": "CAP-0123456789ABCDEF0123456789ABCDEF",
            "family": "protocol",
            "operation": "draft",
            "target": {"type": "protocol", "protocol_id": "protocol-v3"},
            "allowed_tools": ["protocol_editor.draft_change"],
            "blocked_tools": [],
            "cardinality": {"mode": "single", "maximum_uses": 1, "maximum_items": 1},
            "environment": {"tenant_id": "tenant-a"},
            "responsibility_ceiling": "R4_methodological_modification",
            "constraints": {},
            "expiration": {"absolute_expiration": None, "expires_after": []},
        },
        "request": {
            "family": "protocol",
            "operation": "draft",
            "requested_tool": "protocol_editor.draft_change",
            "target": {"type": "protocol", "protocol_id": "protocol-v3"},
            "environment": {"tenant_id": "tenant-a"},
            "responsibility_level": "R3_recommendation",
            "item_count": 5,
        },
        "uses_consumed": 0,
    },
    {
        "name": "operation_not_covered",
        "envelope": {
            "envelope_version": "scientific-authorization-envelope-v2",
            "capability_id": "CAP-0123456789ABCDEF0123456789ABCDEF",
            "family": "protocol",
            "operation": "draft",
            "target": {"type": "protocol", "protocol_id": "protocol-v3"},
            "allowed_tools": ["protocol_editor.draft_change", "protocol_editor.update_active_protocol"],
            "blocked_tools": [],
            "cardinality": {"mode": "single", "maximum_uses": 1, "maximum_items": 1},
            "environment": {"tenant_id": "tenant-a"},
            "responsibility_ceiling": "R4_methodological_modification",
            "constraints": {},
            "expiration": {"absolute_expiration": None, "expires_after": []},
        },
        "request": {
            "family": "protocol",
            "operation": "update_active",
            "requested_tool": "protocol_editor.update_active_protocol",
            "target": {"type": "protocol", "protocol_id": "protocol-v3"},
            "environment": {"tenant_id": "tenant-a"},
            "responsibility_level": "R3_recommendation",
            "item_count": 1,
        },
        "uses_consumed": 0,
    },
]


_WORKER = r"""
import json, sys
payload = json.load(sys.stdin)
backend = payload["backend"]
envelope = payload["envelope"]
request = payload["request"]
uses = int(payload.get("uses_consumed") or 0)
if backend == "akta":
    from akta.contracts_runtime_api import request_contained_by_envelope
    ok, reason = request_contained_by_envelope(envelope, request, uses_consumed=uses)
elif backend == "scope":
    from scientific_authorization_contracts.runtime_request import (
        request_contained_by_envelope,
    )
    ok, reason = request_contained_by_envelope(envelope, request, uses_consumed=uses)
else:
    raise SystemExit(f"unknown backend {backend!r}")
json.dump({"ok": bool(ok), "reason": reason}, sys.stdout)
"""


def _run_backend(backend: str, vector: dict, *, pythonpath: list[str]) -> dict:
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(pythonpath + [env.get("PYTHONPATH", "")])
    # Force unit mode so AKTA shim is allowed when contracts 2.2 is absent.
    env["AKTA_REQUEST_MODE"] = "unit"
    proc = subprocess.run(
        [sys.executable, "-c", _WORKER],
        input=json.dumps(
            {
                "backend": backend,
                "envelope": vector["envelope"],
                "request": vector["request"],
                "uses_consumed": vector.get("uses_consumed", 0),
            }
        ),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"{backend} worker failed for {vector['name']}: "
            f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
        )
    return json.loads(proc.stdout)


@pytest.mark.parametrize("vector", _VECTORS, ids=lambda v: v["name"])
def test_akta_scope_request_contained_differential(vector: dict) -> None:
    if not (SCOPE_CONTRACTS / "scientific_authorization_contracts").is_dir():
        pytest.skip(f"SCOPE contracts tree not found at {SCOPE_CONTRACTS}")

    akta_result = _run_backend(
        "akta",
        vector,
        pythonpath=[str(ROOT)],
    )
    scope_result = _run_backend(
        "scope",
        vector,
        pythonpath=[str(SCOPE_CONTRACTS)],
    )
    assert akta_result == scope_result, (
        f"differential mismatch for {vector['name']}: "
        f"akta={akta_result} scope={scope_result}"
    )
