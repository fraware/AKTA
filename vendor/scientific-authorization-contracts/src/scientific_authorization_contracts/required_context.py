"""Required issuance context per capability family/operation (fail closed)."""

from __future__ import annotations

from typing import Any

# Keys that must appear in review/issuance context for the family+operation.
# Development unbound grants may bypass only when explicitly profile=development
# and runtime_usable=false.
REQUIRED_ISSUANCE_CONTEXT: dict[str, dict[str, list[str]]] = {
    "protocol": {
        "*": ["tenant_id", "project_id", "protocol_version"],
        "draft": ["tenant_id", "project_id", "protocol_version"],
        "update_active": ["tenant_id", "project_id", "protocol_version"],
    },
    "queue": {
        "*": ["tenant_id", "project_id"],
        "robot_submit": ["tenant_id", "project_id", "queue_id"],
        "set_priority": ["tenant_id", "project_id", "queue_id"],
        "submit_run": ["tenant_id", "project_id", "queue_id"],
    },
    "execution": {
        "*": ["tenant_id", "project_id"],
    },
    "experiment_plan": {
        "*": ["tenant_id", "project_id"],
    },
    "publication": {
        "*": ["tenant_id", "project_id"],
    },
    "permissions": {
        "*": ["tenant_id"],
    },
    "interpretation": {
        "*": ["tenant_id", "project_id"],
    },
    "recommendation": {
        "*": ["tenant_id", "project_id"],
    },
    "memory": {
        "*": ["tenant_id"],
    },
}


def required_context_keys(family: str, operation: str | None = None) -> list[str]:
    family_spec = REQUIRED_ISSUANCE_CONTEXT.get(family) or {}
    keys: list[str] = list(family_spec.get("*") or [])
    if operation and operation in family_spec:
        for key in family_spec[operation]:
            if key not in keys:
                keys.append(key)
    return keys


def missing_required_context(
    family: str,
    context: dict[str, Any] | None,
    *,
    operation: str | None = None,
) -> list[str]:
    ctx = dict(context or {})
    # protocol_id may stand in for protocol_version when only one is supplied.
    if ctx.get("protocol_id") and not ctx.get("protocol_version"):
        ctx["protocol_version"] = ctx["protocol_id"]
    if ctx.get("protocol_version") and not ctx.get("protocol_id"):
        ctx["protocol_id"] = ctx["protocol_version"]
    missing: list[str] = []
    for key in required_context_keys(family, operation):
        value = ctx.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(key)
    return missing
