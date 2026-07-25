"""Requested authorization context builder and containment (AKTA 1.2 P0-3/4/5).

Builds the request solely from independently observed facts. Never invents
``unspecified`` / ``default`` sentinels in strict modes, and never copies grant
blocked_tools / expiration / constraints / target / environment / responsibility
into the request before containment.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from akta.capability_envelope import legacy_scope_to_envelope
from akta.contracts_runtime_api import (
    GrantSatisfactionResult,
    abstain_insufficient_authorization_context,
    migration_fallbacks_allowed,
    request_satisfies_grant,
    required_request_fields,
    resolve_request_mode,
)
from akta.errors import InsufficientAuthorizationContext
from akta.shared_contracts import _contracts, family_operations

_AKTA_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_MAPPING = _AKTA_ROOT / "policy" / "action_tool_authorization_mapping.yaml"


@dataclass(frozen=True)
class RequestedAuthorizationContext:
    """Actual requested capability inputs for containment comparison."""

    family: str
    operation: str
    target: dict
    requested_tool: str
    environment: dict
    responsibility_level: str
    item_count: int
    constraints: dict
    control_evidence: dict = field(default_factory=dict)
    scientific_context: dict = field(default_factory=dict)

    def to_request_action(self) -> dict[str, Any]:
        """Independent request facts for ``request_satisfies_grant``."""
        payload: dict[str, Any] = {
            "family": self.family,
            "operation": self.operation,
            "target": dict(self.target),
            "requested_tool": self.requested_tool,
            "environment": dict(self.environment),
            "responsibility_level": self.responsibility_level,
            "item_count": int(self.item_count),
            "constraints": dict(self.constraints),
        }
        if self.control_evidence:
            payload["control_evidence"] = dict(self.control_evidence)
        if self.scientific_context:
            payload["scientific_context"] = dict(self.scientific_context)
        # Flatten identifiers used by required_request_fields checks.
        for key in ("tenant_id", "project_id", "deployment_id", "queue_id"):
            if key in self.environment and self.environment[key] is not None:
                payload.setdefault(key, self.environment[key])
        for key in ("protocol_id", "protocol_version", "queue_entry_id"):
            if key in self.target and self.target[key] is not None:
                payload.setdefault(key, self.target[key])
        return payload

    def to_envelope(self) -> dict[str, Any]:
        """Materialize a shared authorization envelope projection (diagnostics).

        Containment must use ``to_request_action`` + ``request_satisfies_grant``,
        not envelope-vs-envelope comparison that copies grant fields.
        """
        api = _contracts()
        target = dict(self.target)
        if "id" in target and "protocol_id" not in target and target.get("type") == "protocol":
            target["protocol_id"] = target.pop("id")
        elif "id" in target and target.get("type") == "protocol":
            target.setdefault("protocol_id", target.pop("id"))
        elif "id" in target:
            target.pop("id", None)

        environment = dict(self.environment)
        tenant = target.pop("tenant_id", None) or environment.get("tenant_id")
        if tenant:
            environment["tenant_id"] = tenant
        target_env = target.pop("environment", None)
        if target_env and "deployment_id" not in environment:
            environment["deployment_id"] = str(target_env)

        cardinality: dict[str, Any] = {
            "mode": "single" if self.item_count <= 1 else "bounded",
            "maximum_uses": 1,
            "maximum_items": max(1, int(self.item_count)),
        }
        payload = {
            "envelope_version": api.ENVELOPE_VERSION,
            "capability_id": api.new_capability_id(),
            "family": self.family,
            "operation": self.operation,
            "target": target,
            "allowed_tools": [self.requested_tool] if self.requested_tool else [],
            "blocked_tools": [],
            "cardinality": cardinality,
            "environment": environment,
            "responsibility_ceiling": self.responsibility_level,
            "constraints": dict(self.constraints),
            "expiration": {"absolute_expiration": None, "expires_after": []},
        }
        return api.AuthorizationEnvelope.from_dict(payload, validate=True).to_dict()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@lru_cache(maxsize=4)
def load_action_tool_authorization_mapping(
    path: str | None = None,
) -> dict[str, Any]:
    mapping_path = Path(path) if path else _DEFAULT_MAPPING
    if not mapping_path.is_file():
        return {"version": "akta-action-tool-auth-v1", "mappings": {}}
    data = yaml.safe_load(mapping_path.read_text(encoding="utf-8")) or {}
    return data


def resolve_family_operation(
    *,
    action_class: str | None = None,
    requested_tool: str = "",
    requested_action: str = "",
    structured_action: dict[str, Any] | None = None,
    mapping_path: str | None = None,
    mode: str | None = None,
    allow_migration_fallbacks: bool | None = None,
) -> tuple[str, str]:
    """Map AKTA action class + tool → (family, operation).

    Explicit mapping table / structured_action only. Tool-name heuristics and
    last-resort defaults are forbidden unless migration fallbacks are enabled.
    """
    mapping = load_action_tool_authorization_mapping(mapping_path)
    tools = mapping.get("tools") or {}
    if requested_tool and requested_tool in tools:
        entry = tools[requested_tool]
        return str(entry["family"]), str(entry["operation"])

    action_defaults = mapping.get("action_class_defaults") or {}
    action_key = action_class or ""
    if action_key in action_defaults:
        entry = action_defaults[action_key]
        tool_overrides = entry.get("tool_overrides") or {}
        if requested_tool and requested_tool in tool_overrides:
            ov = tool_overrides[requested_tool]
            return str(ov["family"]), str(ov["operation"])
        action_overrides = entry.get("action_overrides") or {}
        if requested_action and requested_action in action_overrides:
            ov = action_overrides[requested_action]
            return str(ov["family"]), str(ov["operation"])
        return str(entry["family"]), str(entry["operation"])

    sa = structured_action or {}
    if sa.get("family") and sa.get("operation"):
        return str(sa["family"]), str(sa["operation"])

    allow = (
        migration_fallbacks_allowed(mode=mode)
        if allow_migration_fallbacks is None
        else allow_migration_fallbacks
    )
    if allow:
        legacy_scope = (
            sa.get("requested_scope")
            or mapping.get("tool_legacy_scopes", {}).get(requested_tool)
        )
        if legacy_scope:
            mig = _contracts().legacy_scope_migration()
            if legacy_scope in mig:
                return mig[legacy_scope]
        # Development-only migration heuristics (explicitly gated).
        if "protocol" in requested_tool:
            return "protocol", "draft"
        if "robot" in requested_tool:
            return "queue", "robot_submit"
        if "lab_scheduler" in requested_tool or "prioritize" in requested_action:
            return "queue", "single_run_priority"
        return "interpretation", "clarify"

    raise abstain_insufficient_authorization_context(
        {"family", "operation"},
        family=None,
        operation=None,
    )


def _first_nonempty(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def build_requested_authorization_context(
    *,
    requested_tool: str,
    requested_action: str = "",
    action_class: str | None = None,
    classification: dict[str, Any] | None = None,
    structured_action: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
    mapping_path: str | None = None,
    responsibility_level: str | None = None,
    item_count: int | None = None,
    target_overrides: dict[str, Any] | None = None,
    environment_overrides: dict[str, Any] | None = None,
    constraints_overrides: dict[str, Any] | None = None,
    control_evidence: dict[str, Any] | None = None,
    mode: str | None = None,
    allow_migration_fallbacks: bool | None = None,
) -> RequestedAuthorizationContext:
    """Build frozen request context from independent observed facts only."""
    ctx = context or {}
    metadata = dict(ctx.get("metadata") or {})
    classification = classification or {}
    structured_action = structured_action or dict(ctx.get("structured_action") or {})
    allow = (
        migration_fallbacks_allowed(mode=mode)
        if allow_migration_fallbacks is None
        else allow_migration_fallbacks
    )
    resolved_mode = resolve_request_mode(mode)

    resolved_action_class = (
        action_class
        or classification.get("action_type")
        or classification.get("action_class")
        or structured_action.get("action_type")
    )
    try:
        family, operation = resolve_family_operation(
            action_class=str(resolved_action_class) if resolved_action_class else None,
            requested_tool=requested_tool,
            requested_action=requested_action,
            structured_action=structured_action,
            mapping_path=mapping_path,
            mode=resolved_mode,
            allow_migration_fallbacks=allow,
        )
    except InsufficientAuthorizationContext:
        raise

    ops = family_operations()
    if family not in ops:
        raise ValueError(f"unknown authorization family: {family!r}")
    if operation not in ops[family]:
        raise ValueError(
            f"unknown operation {operation!r} for family {family!r}"
        )

    protocol_id = _first_nonempty(
        structured_action.get("protocol_id"),
        structured_action.get("target_id"),
        structured_action.get("target_resource"),
        ctx.get("protocol_version"),
        ctx.get("active_protocol_id"),
        metadata.get("protocol_version"),
        (target_overrides or {}).get("protocol_id"),
    )
    target_type = _first_nonempty(
        structured_action.get("target_type"),
        metadata.get("target_type"),
        (target_overrides or {}).get("type"),
    )
    if target_type is None and protocol_id is not None:
        target_type = "protocol"
    if target_type is None and allow:
        target_type = "protocol"
    target: dict[str, Any] = {}
    if target_type is not None:
        target["type"] = target_type
    if target_type == "protocol" and protocol_id is not None:
        target["protocol_id"] = protocol_id
        version = _first_nonempty(
            ctx.get("protocol_version"),
            metadata.get("protocol_version"),
            structured_action.get("protocol_version"),
            protocol_id,
        )
        if version is not None:
            target["protocol_version"] = str(version)
    if target_overrides:
        target.update(target_overrides)

    tenant_id = _first_nonempty(
        structured_action.get("tenant_id"),
        ctx.get("tenant_id"),
        metadata.get("tenant_id"),
        (environment_overrides or {}).get("tenant_id"),
    )
    project_id = _first_nonempty(
        structured_action.get("project_id"),
        ctx.get("project_id"),
        metadata.get("project_id"),
        (environment_overrides or {}).get("project_id"),
    )
    deployment_id = _first_nonempty(
        structured_action.get("target_environment"),
        ctx.get("environment"),
        metadata.get("environment"),
        ctx.get("deployment_profile"),
        metadata.get("deployment_profile"),
        (environment_overrides or {}).get("deployment_id"),
    )
    queue_id = _first_nonempty(
        structured_action.get("queue_id"),
        ctx.get("queue_id"),
        metadata.get("queue_id"),
        (environment_overrides or {}).get("queue_id"),
        (target_overrides or {}).get("queue_id"),
    )
    environment: dict[str, Any] = {
        "tenant_id": tenant_id,
        "project_id": project_id,
        "domain_overlay": ctx.get("domain_overlay") or metadata.get("domain_overlay"),
        "deployment_id": deployment_id,
    }
    if queue_id is not None:
        environment["queue_id"] = queue_id
    environment = {k: v for k, v in environment.items() if v is not None}
    if environment_overrides:
        environment.update({k: v for k, v in environment_overrides.items() if v is not None})

    level = _first_nonempty(
        responsibility_level,
        structured_action.get("responsibility_level"),
        classification.get("responsibility_level"),
        metadata.get("responsibility_level"),
        ctx.get("responsibility_level"),
    )
    if level is None and allow:
        level = "R4_methodological_modification"

    if item_count is not None:
        count: int | None = int(item_count)
    else:
        raw_count = _first_nonempty(
            structured_action.get("item_count"),
            metadata.get("item_count"),
            ctx.get("item_count"),
        )
        if raw_count is None:
            count = 1 if allow else None
        else:
            count = int(raw_count)

    constraints = dict(structured_action.get("constraints") or {})
    if constraints_overrides:
        constraints.update(constraints_overrides)

    evidence = dict(control_evidence or structured_action.get("control_evidence") or {})
    scientific = {
        k: v
        for k, v in {
            "protocol_version": target.get("protocol_version") or protocol_id,
            "evidence_state": classification.get("evidence_state")
            or ctx.get("evidence_state"),
            "validation_status": ctx.get("validation_status")
            or metadata.get("validation_status"),
        }.items()
        if v is not None
    }

    # Collect supplied fields and enforce required_request_fields.
    provisional = {
        "family": family,
        "operation": operation,
        "requested_tool": requested_tool,
        "responsibility_level": level,
        "item_count": count,
        "tenant_id": environment.get("tenant_id"),
        "project_id": environment.get("project_id"),
        "queue_id": environment.get("queue_id") or target.get("queue_id"),
        "protocol_id": target.get("protocol_id") or protocol_id,
        "protocol_version": target.get("protocol_version") or protocol_id,
        "target": target,
        "environment": environment,
    }
    supplied = {
        key
        for key, value in provisional.items()
        if value is not None and not (isinstance(value, str) and not str(value).strip())
    }
    if target.get("protocol_id"):
        supplied.add("protocol_id")
        supplied.add("protocol_version")
    for key, value in environment.items():
        if value is not None and not (isinstance(value, str) and not str(value).strip()):
            supplied.add(key)

    required = required_request_fields(family, operation, mode=resolved_mode)
    missing = frozenset(required - supplied)
    if missing and not allow:
        raise abstain_insufficient_authorization_context(
            missing, family=family, operation=operation
        )
    if missing and allow:
        # Development migration only: fill the few remaining sentinel gaps.
        if "tenant_id" in missing:
            environment["tenant_id"] = "default"
            missing = frozenset(m for m in missing if m != "tenant_id")
        if "protocol_id" in missing and target.get("type") == "protocol":
            target["protocol_id"] = "unspecified"
            missing = frozenset(m for m in missing if m != "protocol_id")
        if "responsibility_level" in missing:
            level = "R4_methodological_modification"
            missing = frozenset(m for m in missing if m != "responsibility_level")
        if "item_count" in missing:
            count = 1
            missing = frozenset(m for m in missing if m != "item_count")
        if missing:
            raise abstain_insufficient_authorization_context(
                missing, family=family, operation=operation
            )

    assert level is not None
    assert count is not None

    return RequestedAuthorizationContext(
        family=family,
        operation=operation,
        target=target,
        requested_tool=requested_tool,
        environment=environment,
        responsibility_level=str(level),
        item_count=int(count),
        constraints=constraints,
        control_evidence=evidence,
        scientific_context=scientific,
    )


@dataclass
class AuthorizationContainmentResult:
    covers: bool
    comparator: str
    requested: RequestedAuthorizationContext | None = None
    requested_envelope: dict[str, Any] | None = None
    granted_envelope: dict[str, Any] | None = None
    errors: list[str] = field(default_factory=list)
    reason_code: str | None = None
    satisfaction: GrantSatisfactionResult | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "covers": self.covers,
            "comparator": self.comparator,
            "requested": self.requested.to_dict() if self.requested else None,
            "requested_envelope": self.requested_envelope,
            "granted_envelope": self.granted_envelope,
            "errors": list(self.errors),
            "reason_code": self.reason_code,
            "satisfaction": self.satisfaction.to_dict() if self.satisfaction else None,
        }


def evaluate_authorization_containment(
    *,
    granted_envelope: dict[str, Any],
    requested: RequestedAuthorizationContext,
    ledger_status: dict[str, Any] | None = None,
    runtime_evidence: dict[str, Any] | None = None,
    uses_consumed: int = 0,
    mode: str | None = None,
) -> AuthorizationContainmentResult:
    """Compare independently observed request facts against the grant envelope."""
    evidence = dict(runtime_evidence or {})
    if ledger_status is not None:
        evidence["ledger_status"] = ledger_status
    if requested.control_evidence and "control_evidence" not in evidence:
        evidence["control_evidence"] = dict(requested.control_evidence)

    request_action = requested.to_request_action()
    satisfaction = request_satisfies_grant(
        grant_envelope=granted_envelope,
        requested_action=request_action,
        runtime_evidence=evidence,
        uses_consumed=uses_consumed,
        mode=mode,
    )

    # Diagnostic envelope projection only — not used as the containment input.
    try:
        requested_envelope = requested.to_envelope()
    except Exception:
        requested_envelope = None

    errors = list(satisfaction.errors)
    return AuthorizationContainmentResult(
        covers=satisfaction.satisfied,
        comparator=satisfaction.comparator,
        requested=requested,
        requested_envelope=requested_envelope,
        granted_envelope=granted_envelope,
        errors=errors,
        reason_code=satisfaction.reason_code,
        satisfaction=satisfaction,
    )


def legacy_requested_envelope_from_scope(
    requested_scope: str,
    *,
    allowed_tools: list[str] | None = None,
    responsibility_ceiling: str = "R4_methodological_modification",
) -> dict[str, Any]:
    """Migration helper — not used as primary comparator in strict modes."""
    return legacy_scope_to_envelope(
        approved_scope=requested_scope,
        allowed_tools=allowed_tools,
        responsibility_ceiling=responsibility_ceiling,
    )
