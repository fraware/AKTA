"""Requested authorization context builder and containment (AKTA 1.1 WS8)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from akta.capability_envelope import authorization_covers, legacy_scope_to_envelope
from akta.shared_contracts import _contracts, family_operations

_AKTA_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_MAPPING = _AKTA_ROOT / "policy" / "action_tool_authorization_mapping.yaml"


@dataclass(frozen=True)
class RequestedAuthorizationContext:
    """Actual requested capability envelope inputs for containment comparison."""

    family: str
    operation: str
    target: dict
    requested_tool: str
    environment: dict
    responsibility_level: str
    item_count: int
    constraints: dict

    def to_envelope(self) -> dict[str, Any]:
        """Materialize a shared authorization envelope for containment checks."""
        api = _contracts()
        target = dict(self.target)
        # Normalize common aliases onto schema field names.
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
) -> tuple[str, str]:
    """Map AKTA action class + tool → (family, operation)."""
    mapping = load_action_tool_authorization_mapping(mapping_path)
    tools = mapping.get("tools") or {}
    if requested_tool and requested_tool in tools:
        entry = tools[requested_tool]
        return str(entry["family"]), str(entry["operation"])

    action_defaults = mapping.get("action_class_defaults") or {}
    action_key = action_class or ""
    if action_key in action_defaults:
        entry = action_defaults[action_key]
        # Tool-sensitive overrides (A5 draft vs update_active, A9 robot, etc.)
        tool_overrides = entry.get("tool_overrides") or {}
        if requested_tool and requested_tool in tool_overrides:
            ov = tool_overrides[requested_tool]
            return str(ov["family"]), str(ov["operation"])
        # Action-name sensitive (draft vs update)
        action_overrides = entry.get("action_overrides") or {}
        if requested_action and requested_action in action_overrides:
            ov = action_overrides[requested_action]
            return str(ov["family"]), str(ov["operation"])
        return str(entry["family"]), str(entry["operation"])

    sa = structured_action or {}
    if sa.get("family") and sa.get("operation"):
        return str(sa["family"]), str(sa["operation"])

    # Fall back to legacy scalar migration when a scope hint is present.
    legacy_scope = (
        sa.get("requested_scope")
        or mapping.get("tool_legacy_scopes", {}).get(requested_tool)
    )
    if legacy_scope:
        mig = _contracts().legacy_scope_migration()
        if legacy_scope in mig:
            return mig[legacy_scope]

    # Last resort: protocol draft for protocol tools, interpretation otherwise.
    if "protocol" in requested_tool:
        return "protocol", "draft"
    if "robot" in requested_tool:
        return "queue", "robot_submit"
    if "lab_scheduler" in requested_tool or "prioritize" in requested_action:
        return "queue", "single_run_priority"
    return "interpretation", "clarify"


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
) -> RequestedAuthorizationContext:
    """Build frozen request context from classification/tool/action/context."""
    ctx = context or {}
    metadata = dict(ctx.get("metadata") or {})
    classification = classification or {}
    structured_action = structured_action or dict(ctx.get("structured_action") or {})

    resolved_action_class = (
        action_class
        or classification.get("action_type")
        or classification.get("action_class")
        or structured_action.get("action_type")
    )
    family, operation = resolve_family_operation(
        action_class=str(resolved_action_class) if resolved_action_class else None,
        requested_tool=requested_tool,
        requested_action=requested_action,
        structured_action=structured_action,
        mapping_path=mapping_path,
    )

    # Validate vocabulary.
    ops = family_operations()
    if family not in ops:
        raise ValueError(f"unknown authorization family: {family!r}")
    if operation not in ops[family]:
        raise ValueError(
            f"unknown operation {operation!r} for family {family!r}"
        )

    protocol_id = (
        structured_action.get("protocol_id")
        or structured_action.get("target_id")
        or structured_action.get("target_resource")
        or ctx.get("protocol_version")
        or ctx.get("active_protocol_id")
        or metadata.get("protocol_version")
        or "unspecified"
    )
    target_type = (
        structured_action.get("target_type")
        or metadata.get("target_type")
        or "protocol"
    )
    target: dict[str, Any] = {"type": target_type}
    if target_type == "protocol":
        target["protocol_id"] = protocol_id
        if ctx.get("protocol_version") or metadata.get("protocol_version"):
            target["protocol_version"] = str(
                ctx.get("protocol_version") or metadata.get("protocol_version")
            )
    if target_overrides:
        target.update(target_overrides)

    environment = {
        "tenant_id": (
            structured_action.get("tenant_id")
            or ctx.get("tenant_id")
            or metadata.get("tenant_id")
            or "default"
        ),
        "domain_overlay": ctx.get("domain_overlay") or metadata.get("domain_overlay"),
        "deployment_id": (
            structured_action.get("target_environment")
            or ctx.get("environment")
            or metadata.get("environment")
            or ctx.get("deployment_profile")
            or metadata.get("deployment_profile")
        ),
    }
    environment = {k: v for k, v in environment.items() if v is not None}
    if environment_overrides:
        environment.update(environment_overrides)

    level = (
        responsibility_level
        or structured_action.get("responsibility_level")
        or classification.get("responsibility_level")
        or metadata.get("responsibility_level")
        or "R4_methodological_modification"
    )
    count = (
        item_count
        if item_count is not None
        else int(
            structured_action.get("item_count")
            or metadata.get("item_count")
            or ctx.get("item_count")
            or 1
        )
    )
    constraints = dict(structured_action.get("constraints") or {})
    if constraints_overrides:
        constraints.update(constraints_overrides)

    return RequestedAuthorizationContext(
        family=family,
        operation=operation,
        target=target,
        requested_tool=requested_tool,
        environment=environment,
        responsibility_level=str(level),
        item_count=count,
        constraints=constraints,
    )


@dataclass
class AuthorizationContainmentResult:
    covers: bool
    comparator: str
    requested: RequestedAuthorizationContext | None = None
    requested_envelope: dict[str, Any] | None = None
    granted_envelope: dict[str, Any] | None = None
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "covers": self.covers,
            "comparator": self.comparator,
            "requested": self.requested.to_dict() if self.requested else None,
            "requested_envelope": self.requested_envelope,
            "granted_envelope": self.granted_envelope,
            "errors": list(self.errors),
        }


def evaluate_authorization_containment(
    *,
    granted_envelope: dict[str, Any],
    requested: RequestedAuthorizationContext,
    ledger_status: dict[str, Any] | None = None,
) -> AuthorizationContainmentResult:
    """Compare actual request against granted envelope; enforce remaining uses."""
    errors: list[str] = []
    if ledger_status is not None:
        remaining = ledger_status.get("cardinality_remaining")
        if remaining is None:
            remaining = ledger_status.get("single_use_remaining")
        if remaining is not None and int(remaining) <= 0:
            errors.append("no remaining use for grant (cardinality_remaining=0)")
        status = str(ledger_status.get("status") or "")
        if status and status != "active":
            errors.append(f"grant status not active ({status})")

    grant_constraints = dict(granted_envelope.get("constraints") or {})
    req_constraints = dict(requested.constraints or {})
    for key in req_constraints:
        if key not in grant_constraints:
            errors.append(f"unknown request constraint not in grant: {key!r}")

    # Build envelope using only grant-authorized constraint keys so vocabulary
    # validation does not raise before our unknown-constraint errors surface.
    safe_requested = RequestedAuthorizationContext(
        family=requested.family,
        operation=requested.operation,
        target=dict(requested.target),
        requested_tool=requested.requested_tool,
        environment=dict(requested.environment),
        responsibility_level=requested.responsibility_level,
        item_count=requested.item_count,
        constraints={k: v for k, v in req_constraints.items() if k in grant_constraints},
    )
    requested_envelope = safe_requested.to_envelope()
    # Requested must honor grant blocked_tools (narrowing requires superset blocks).
    granted_blocked = list(granted_envelope.get("blocked_tools") or [])
    requested_envelope["blocked_tools"] = sorted(
        set(requested_envelope.get("blocked_tools") or []) | set(granted_blocked)
    )
    # Inherit grant expiration upper bound so the request is not treated as wider.
    grant_exp = dict(granted_envelope.get("expiration") or {})
    req_exp = dict(requested_envelope.get("expiration") or {})
    if grant_exp.get("absolute_expiration") and not req_exp.get("absolute_expiration"):
        req_exp["absolute_expiration"] = grant_exp["absolute_expiration"]
    if grant_exp.get("expires_after") and not req_exp.get("expires_after"):
        req_exp["expires_after"] = list(grant_exp["expires_after"])
    requested_envelope["expiration"] = req_exp
    requested_envelope["constraints"] = {**grant_constraints, **safe_requested.constraints}
    # Item-count defense: requested items must not exceed grant cardinality.
    granted_card = granted_envelope.get("cardinality") or {}
    max_items = granted_card.get("maximum_items")
    if max_items is not None and int(requested.item_count) > int(max_items):
        errors.append(
            f"requested item_count {requested.item_count} exceeds grant "
            f"maximum_items {max_items}"
        )
    covers, comparator = authorization_covers(
        granted_envelope=granted_envelope,
        requested_envelope=requested_envelope,
        allow_legacy_scalar=False,
    )
    if not covers:
        errors.append("requested authorization not covered by grant envelope")
    return AuthorizationContainmentResult(
        covers=covers and not errors,
        comparator=comparator,
        requested=requested,
        requested_envelope=requested_envelope,
        granted_envelope=granted_envelope,
        errors=errors,
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
