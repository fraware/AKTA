"""Contracts 2.2 runtime API shim for AKTA request/containment (P0-3/4/5).

Prefer symbols from the installed ``scientific_authorization_contracts`` package
when present (contracts >= 2.2 / SCOPE sibling tree). Until the pinned 2.2 wheel
publishes those symbols, this module supplies directive-aligned implementations.

Release / production / institutional / cross_repo modes fail closed if the
canonical symbol is absent and local fallback is not explicitly allowed for the
call site. Unit and development modes may use the local implementations so AKTA
can land surfaces before the wheel exists.

Do not treat this shim as an independent authorization vocabulary: when the
canonical package exports the symbol, that export always wins.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Callable

from akta.errors import InsufficientAuthorizationContext

# Modes that must not invent request context (no unspecified/default sentinels).
STRICT_REQUEST_MODES = frozenset(
    {
        "pilot",
        "release",
        "cross_repo",
        "production",
        "institutional",
        "institutional_release",
    }
)
# Modes that reject the local shim when the canonical contracts symbol is absent.
RELEASE_FAIL_CLOSED_MODES = frozenset(
    {
        "release",
        "production",
        "institutional",
        "institutional_release",
        "cross_repo",
    }
)
DEVELOPMENT_REQUEST_MODES = frozenset({"development", "dev", "unit", "test"})

# Reason codes (directive P0-4 taxonomy + SCOPE runtime_request alignment).
REASON_MISSING_CONTEXT = "missing_context"
REASON_INSUFFICIENT_RUNTIME_CONTEXT = "insufficient_runtime_context"
REASON_OPERATION_NOT_COVERED = "operation_not_covered"
REASON_TARGET_NOT_COVERED = "target_not_covered"
REASON_ENVIRONMENT_NOT_COVERED = "environment_not_covered"
REASON_FAMILY_NOT_COVERED = "family_not_covered"
REASON_TOOL_NOT_ALLOWED = "tool_not_allowed"
REASON_TOOL_BLOCKED = "tool_blocked"
REASON_RESPONSIBILITY_EXCEEDED = "responsibility_exceeded"
REASON_CARDINALITY_EXCEEDED = "cardinality_exceeded"
REASON_CARDINALITY_EXHAUSTED = "cardinality_exhausted"
REASON_CONSTRAINT_UNSATISFIED = "constraint_unsatisfied"
REASON_CONTROL_EVIDENCE_MISSING = "control_evidence_missing"
REASON_EXPIRATION_INVALID = "expiration_invalid"
REASON_GRANT_NOT_ACTIVE = "grant_not_active"

# Issuance/request context keys aligned with SCOPE required_context.py.
_REQUIRED_BY_FAMILY: dict[str, dict[str, list[str]]] = {
    "protocol": {
        "*": ["tenant_id", "project_id", "protocol_id"],
        "draft": ["tenant_id", "project_id", "protocol_id"],
        "update_active": ["tenant_id", "project_id", "protocol_id"],
    },
    "queue": {
        "*": ["tenant_id", "project_id"],
        "robot_submit": ["tenant_id", "project_id", "queue_id"],
        "set_priority": ["tenant_id", "project_id", "queue_id"],
        "submit_run": ["tenant_id", "project_id", "queue_id"],
    },
    "execution": {"*": ["tenant_id", "project_id"]},
    "experiment_plan": {"*": ["tenant_id", "project_id"]},
    "publication": {"*": ["tenant_id", "project_id"]},
    "permissions": {"*": ["tenant_id"]},
    "interpretation": {"*": ["tenant_id", "project_id"]},
    "recommendation": {"*": ["tenant_id", "project_id"]},
    "memory": {"*": ["tenant_id"]},
}

_ALWAYS_REQUIRED = frozenset(
    {"family", "operation", "requested_tool", "responsibility_level", "item_count"}
)


def resolve_request_mode(explicit: str | None = None) -> str:
    if explicit:
        return explicit.strip().lower()
    for key in ("AKTA_REQUEST_MODE", "AKTA_GRANT_MODE"):
        value = os.environ.get(key, "").strip().lower()
        if value:
            return value
    from akta.policy_integrity import is_production_mode, require_signed_policy

    if is_production_mode() or require_signed_policy():
        return "production"
    return "unit"


def migration_fallbacks_allowed(*, mode: str | None = None) -> bool:
    """True only when development + explicit migration flag + runtime auth off."""
    resolved = resolve_request_mode(mode)
    if resolved not in DEVELOPMENT_REQUEST_MODES:
        return False
    flag = os.environ.get("AKTA_ALLOW_AUTH_MIGRATION_FALLBACKS", "").strip().lower()
    if flag not in ("1", "true", "yes"):
        return False
    runtime = os.environ.get("AKTA_RUNTIME_AUTHORIZATION", "enabled").strip().lower()
    return runtime in ("0", "false", "no", "disabled", "off")


def _import_contracts_attr(name: str) -> Any | None:
    try:
        import scientific_authorization_contracts as contracts
    except ImportError:
        return None
    attr = getattr(contracts, name, None)
    if callable(attr) or attr is not None:
        return attr
    # Submodule layouts used by SCOPE sibling contracts tree.
    for module_name in (
        "scientific_authorization_contracts.runtime_request",
        "scientific_authorization_contracts.required_context",
        "scientific_authorization_contracts.request",
    ):
        try:
            mod = __import__(module_name, fromlist=[name])
        except ImportError:
            continue
        attr = getattr(mod, name, None)
        if attr is not None:
            return attr
    return None


def _require_or_local(
    name: str,
    local: Callable[..., Any],
    *,
    mode: str | None = None,
    aliases: tuple[str, ...] = (),
) -> Callable[..., Any]:
    """Return contracts symbol when present; else local or fail closed."""
    for candidate in (name, *aliases):
        imported = _import_contracts_attr(candidate)
        if callable(imported):
            return imported
    resolved = resolve_request_mode(mode)
    if resolved in RELEASE_FAIL_CLOSED_MODES:
        raise ImportError(
            f"contracts API {name!r} is required in mode={resolved!r} but is "
            f"absent from scientific_authorization_contracts "
            f"(AKTA 1.2 / contracts 2.2). Install the pinned wheel or use a "
            f"non-release mode with the documented shim."
        )
    return local


def _shim_required_request_fields(family: str, operation: str) -> frozenset[str]:
    keys = set(_ALWAYS_REQUIRED)
    family_spec = _REQUIRED_BY_FAMILY.get(family) or {}
    for key in family_spec.get("*") or []:
        keys.add(key)
    if operation and operation in family_spec:
        for key in family_spec[operation]:
            keys.add(key)
    return frozenset(keys)


def required_request_fields(
    family: str,
    operation: str,
    *,
    mode: str | None = None,
) -> frozenset[str]:
    """Return field names that must be present on the requested action."""

    def _via_required_context_keys(fam: str, op: str) -> frozenset[str]:
        imported = _import_contracts_attr("required_context_keys")
        if not callable(imported):
            raise TypeError("required_context_keys unavailable")
        keys = set(_ALWAYS_REQUIRED)
        keys.update(str(k) for k in imported(fam, op))
        # Normalize SCOPE issuance naming onto request field names.
        if "protocol_version" in keys:
            keys.discard("protocol_version")
            keys.add("protocol_id")
        return frozenset(keys)

    imported = _import_contracts_attr("required_request_fields")
    if callable(imported):
        result = imported(family, operation)
        return frozenset(result)

    resolved = resolve_request_mode(mode)
    if resolved in RELEASE_FAIL_CLOSED_MODES:
        # Prefer required_context_keys from SCOPE contracts when 2.2 naming absent.
        try:
            return _via_required_context_keys(family, operation)
        except (ImportError, TypeError) as exc:
            raise ImportError(
                "required_request_fields is required in release modes but absent "
                "from scientific_authorization_contracts"
            ) from exc
    try:
        return _via_required_context_keys(family, operation)
    except (ImportError, TypeError):
        return _shim_required_request_fields(family, operation)


def _target_covered(runtime_target: dict[str, Any], grant_target: dict[str, Any]) -> bool:
    if not grant_target:
        return True
    if not runtime_target:
        return False
    for key, value in grant_target.items():
        if key not in runtime_target or runtime_target[key] != value:
            return False
    return True


def _operation_covered(family: str, granted_op: str, requested_op: str) -> bool:
    imported = _import_contracts_attr("operation_covers")
    if callable(imported):
        try:
            return bool(imported(family, granted_op, requested_op))
        except Exception:
            return False
    from akta.shared_contracts import family_operations

    ops = family_operations().get(family) or []
    if requested_op not in ops or granted_op not in ops:
        return False
    return ops.index(requested_op) <= ops.index(granted_op)


def _responsibility_ok(requested: str, ceiling: str) -> bool:
    from akta.shared_contracts import responsibility_rank

    ranks = responsibility_rank()
    if requested not in ranks or ceiling not in ranks:
        return False
    return ranks[requested] <= ranks[ceiling]


def _evaluate_grant_constraints(
    constraints: dict[str, Any],
    request: dict[str, Any],
    runtime_evidence: dict[str, Any],
) -> tuple[bool, str | None]:
    imported = _import_contracts_attr("evaluate_constraint_runtime")
    runtime = {**request, **runtime_evidence}
    if isinstance(runtime_evidence.get("control_evidence"), dict):
        runtime["control_evidence"] = dict(runtime_evidence["control_evidence"])
    if callable(imported):
        ok, reason = imported(constraints, runtime)
        if ok:
            return True, None
        reason_s = str(reason or REASON_CONSTRAINT_UNSATISFIED)
        if reason_s.startswith("constraint_not_satisfied:"):
            key = reason_s.split(":", 1)[1]
            # Mandatory controls without evidence map to control_evidence_missing.
            if key.startswith("requires_"):
                return False, REASON_CONTROL_EVIDENCE_MISSING
            return False, REASON_CONSTRAINT_UNSATISFIED
        return False, reason_s

    control_evidence = dict(runtime.get("control_evidence") or {})
    for key, expected in (constraints or {}).items():
        if key.startswith("requires_") and bool(expected):
            entry = control_evidence.get(key)
            if not isinstance(entry, dict) or not entry.get("satisfied"):
                return False, REASON_CONTROL_EVIDENCE_MISSING
            has_artifact = bool(entry.get("artifact_id") and entry.get("artifact_hash"))
            has_trace = bool(entry.get("trace_id") and entry.get("trace_hash"))
            if not (has_artifact or has_trace):
                return False, REASON_CONTROL_EVIDENCE_MISSING
            continue
        if key in runtime and runtime[key] != expected:
            return False, REASON_CONSTRAINT_UNSATISFIED
        if key not in runtime and key not in control_evidence:
            # Soft keys: only fail when runtime supplies a conflicting value.
            continue
    return True, None


def _shim_request_contained_by_envelope(
    envelope: dict[str, Any] | Any,
    request: dict[str, Any],
    *,
    uses_consumed: int = 0,
    require_bound_context: bool = True,
) -> tuple[bool, str | None]:
    env = envelope if isinstance(envelope, dict) else dict(envelope)
    tool = request.get("requested_tool")
    if tool is None or tool == "":
        return False, REASON_INSUFFICIENT_RUNTIME_CONTEXT
    blocked = list(env.get("blocked_tools") or [])
    allowed = list(env.get("allowed_tools") or [])
    if tool in blocked:
        return False, REASON_TOOL_BLOCKED
    if tool not in allowed and "*" not in allowed:
        return False, REASON_TOOL_NOT_ALLOWED

    env_family = env.get("family")
    req_family = request.get("family")
    if env_family and req_family not in (None, env_family):
        return False, REASON_FAMILY_NOT_COVERED

    operation = request.get("operation")
    if operation:
        if not _operation_covered(str(env_family or ""), str(env.get("operation") or ""), str(operation)):
            return False, REASON_OPERATION_NOT_COVERED
    elif require_bound_context:
        return False, REASON_INSUFFICIENT_RUNTIME_CONTEXT

    grant_environment = dict(env.get("environment") or {})
    if grant_environment:
        runtime_env = dict(request.get("environment") or {})
        for key, value in grant_environment.items():
            if key not in runtime_env:
                if require_bound_context:
                    return False, REASON_INSUFFICIENT_RUNTIME_CONTEXT
                continue
            if runtime_env[key] != value:
                return False, REASON_ENVIRONMENT_NOT_COVERED

    grant_target = dict(env.get("target") or {})
    if grant_target:
        runtime_target = dict(request.get("target") or {})
        if not runtime_target:
            if require_bound_context:
                return False, REASON_INSUFFICIENT_RUNTIME_CONTEXT
        elif not _target_covered(runtime_target, grant_target):
            return False, REASON_TARGET_NOT_COVERED

    resp = request.get("responsibility_level")
    ceiling = str(env.get("responsibility_ceiling") or "")
    if resp:
        if not _responsibility_ok(str(resp), ceiling):
            return False, REASON_RESPONSIBILITY_EXCEEDED
    elif require_bound_context and ceiling:
        return False, REASON_INSUFFICIENT_RUNTIME_CONTEXT

    card = dict(env.get("cardinality") or {})
    mode = str(card.get("mode") or "single")
    max_uses = card.get("maximum_uses", card.get("max"))
    if mode == "single" and int(uses_consumed) >= 1:
        return False, REASON_CARDINALITY_EXHAUSTED
    if max_uses is not None and int(uses_consumed) >= int(max_uses):
        return False, REASON_CARDINALITY_EXHAUSTED
    item_count = int(request.get("item_count") or 1)
    max_items = card.get("maximum_items")
    if max_items is not None and item_count > int(max_items):
        return False, REASON_CARDINALITY_EXCEEDED

    evidence: dict[str, Any] = {}
    if isinstance(request.get("runtime_evidence"), dict):
        evidence.update(request["runtime_evidence"])
    if isinstance(request.get("control_evidence"), dict):
        evidence.setdefault("control_evidence", request["control_evidence"])
    ok, reason = _evaluate_grant_constraints(
        dict(env.get("constraints") or {}),
        request,
        evidence,
    )
    if not ok:
        return False, reason
    return True, None


def request_contained_by_envelope(
    envelope: dict[str, Any] | Any,
    request: dict[str, Any],
    *,
    uses_consumed: int = 0,
    require_bound_context: bool = True,
    mode: str | None = None,
) -> tuple[bool, str | None]:
    """Thin adapter to the canonical SCOPE/contracts runtime evaluator."""
    impl = _require_or_local(
        "request_contained_by_envelope",
        _shim_request_contained_by_envelope,
        mode=mode,
    )
    return impl(
        envelope,
        request,
        uses_consumed=uses_consumed,
        require_bound_context=require_bound_context,
    )


@dataclass(frozen=True)
class GrantSatisfactionResult:
    """Structured containment outcome (directive P0-4 taxonomy)."""

    satisfied: bool
    reason_code: str | None = None
    errors: tuple[str, ...] = ()
    comparator: str = "request_contained_by_envelope"
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def covers(self) -> bool:
        return self.satisfied

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["covers"] = self.satisfied
        return payload


def _expiration_invalid(
    grant_envelope: dict[str, Any],
    runtime_evidence: dict[str, Any],
) -> bool:
    exp = dict(grant_envelope.get("expiration") or {})
    absolute = exp.get("absolute_expiration")
    if not absolute:
        return False
    now = runtime_evidence.get("now") or runtime_evidence.get("checked_at")
    if now is None:
        now = datetime.now(timezone.utc).isoformat()
    try:
        return str(now) > str(absolute)
    except Exception:
        return True


def _shim_request_satisfies_grant(
    *,
    grant_envelope: dict[str, Any],
    requested_action: dict[str, Any],
    runtime_evidence: dict[str, Any] | None = None,
    uses_consumed: int = 0,
    require_bound_context: bool = True,
    mode: str | None = None,
) -> GrantSatisfactionResult:
    evidence = dict(runtime_evidence or {})
    request = dict(requested_action)
    # Flatten control evidence onto the request for constraint evaluators.
    if "control_evidence" in evidence and "control_evidence" not in request:
        request["control_evidence"] = dict(evidence["control_evidence"])
    if "runtime_evidence" not in request:
        request["runtime_evidence"] = evidence

    ledger_status = evidence.get("ledger_status")
    if isinstance(ledger_status, dict):
        status = str(ledger_status.get("status") or "")
        if status and status != "active":
            return GrantSatisfactionResult(
                satisfied=False,
                reason_code=REASON_GRANT_NOT_ACTIVE,
                errors=(f"grant status not active ({status})",),
            )
        remaining = ledger_status.get("cardinality_remaining")
        if remaining is None:
            remaining = ledger_status.get("single_use_remaining")
        if remaining is not None:
            # Prefer explicit uses_consumed; otherwise derive from remaining=0.
            if int(remaining) <= 0:
                return GrantSatisfactionResult(
                    satisfied=False,
                    reason_code=REASON_CARDINALITY_EXHAUSTED,
                    errors=("no remaining use for grant (cardinality_remaining=0)",),
                )

    if _expiration_invalid(grant_envelope, evidence):
        return GrantSatisfactionResult(
            satisfied=False,
            reason_code=REASON_EXPIRATION_INVALID,
            errors=("grant absolute_expiration is in the past",),
        )

    family = str(request.get("family") or "")
    operation = str(request.get("operation") or "")
    if family and operation:
        try:
            required = required_request_fields(family, operation, mode=mode)
        except ImportError as exc:
            return GrantSatisfactionResult(
                satisfied=False,
                reason_code=REASON_MISSING_CONTEXT,
                errors=(str(exc),),
            )
        supplied = _supplied_field_names(request)
        missing = frozenset(required - supplied)
        if missing:
            return GrantSatisfactionResult(
                satisfied=False,
                reason_code=REASON_MISSING_CONTEXT,
                errors=(f"missing required request fields: {sorted(missing)}",),
                details={"missing": sorted(missing)},
            )

    ok, reason = request_contained_by_envelope(
        grant_envelope,
        request,
        uses_consumed=uses_consumed,
        require_bound_context=require_bound_context,
        mode=mode,
    )
    if ok:
        return GrantSatisfactionResult(satisfied=True, reason_code=None)
    code = str(reason or REASON_OPERATION_NOT_COVERED)
    # Normalize SCOPE alias onto directive taxonomy.
    if code == REASON_INSUFFICIENT_RUNTIME_CONTEXT:
        code = REASON_MISSING_CONTEXT
    return GrantSatisfactionResult(
        satisfied=False,
        reason_code=code,
        errors=(code,),
    )


def _supplied_field_names(request: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for key, value in request.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        names.add(key)
    target = request.get("target") or {}
    if isinstance(target, dict):
        for key, value in target.items():
            if value is None or (isinstance(value, str) and not str(value).strip()):
                continue
            names.add(key)
    environment = request.get("environment") or {}
    if isinstance(environment, dict):
        for key, value in environment.items():
            if value is None or (isinstance(value, str) and not str(value).strip()):
                continue
            names.add(key)
    # protocol_id / protocol_version aliases
    if "protocol_id" in names and "protocol_version" not in names:
        names.add("protocol_version")
    if "protocol_version" in names and "protocol_id" not in names:
        names.add("protocol_id")
    return names


def request_satisfies_grant(
    *,
    grant_envelope: dict[str, Any],
    requested_action: dict[str, Any],
    runtime_evidence: dict[str, Any] | None = None,
    uses_consumed: int = 0,
    require_bound_context: bool = True,
    mode: str | None = None,
) -> GrantSatisfactionResult:
    """Compare grant requirements against independently observed request facts."""
    imported = _import_contracts_attr("request_satisfies_grant")
    if callable(imported):
        raw = imported(
            grant_envelope=grant_envelope,
            requested_action=requested_action,
            runtime_evidence=runtime_evidence,
        )
        if isinstance(raw, GrantSatisfactionResult):
            return raw
        if isinstance(raw, dict):
            return GrantSatisfactionResult(
                satisfied=bool(raw.get("satisfied", raw.get("covers", False))),
                reason_code=raw.get("reason_code") or raw.get("code"),
                errors=tuple(raw.get("errors") or ()),
                comparator=str(raw.get("comparator") or "request_satisfies_grant"),
                details=dict(raw.get("details") or {}),
            )
        if isinstance(raw, tuple) and len(raw) >= 2:
            return GrantSatisfactionResult(
                satisfied=bool(raw[0]),
                reason_code=None if raw[0] else str(raw[1]),
                errors=() if raw[0] else (str(raw[1]),),
            )
    resolved = resolve_request_mode(mode)
    if resolved in STRICT_REQUEST_MODES and imported is None:
        # Local shim still allowed for containment until 2.2 exports the symbol,
        # but only after request_contained_by_envelope resolution (which itself
        # fail-closes in strict modes when that symbol is absent).
        pass
    return _shim_request_satisfies_grant(
        grant_envelope=grant_envelope,
        requested_action=requested_action,
        runtime_evidence=runtime_evidence,
        uses_consumed=uses_consumed,
        require_bound_context=require_bound_context,
        mode=mode,
    )


def abstain_insufficient_authorization_context(
    missing: frozenset[str] | set[str] | list[str],
    *,
    family: str | None = None,
    operation: str | None = None,
) -> InsufficientAuthorizationContext:
    """Build the typed abstention error for incomplete request context."""
    return InsufficientAuthorizationContext(
        missing=frozenset(missing),
        family=family,
        operation=operation,
    )


@lru_cache(maxsize=1)
def contracts_runtime_api_report() -> dict[str, Any]:
    """Diagnostics: which symbols came from contracts vs local shim."""
    report: dict[str, Any] = {"source": {}}
    for name in (
        "required_request_fields",
        "required_context_keys",
        "request_contained_by_envelope",
        "request_satisfies_grant",
        "operation_covers",
        "evaluate_constraint_runtime",
    ):
        report["source"][name] = (
            "scientific_authorization_contracts"
            if _import_contracts_attr(name) is not None
            else "akta_shim"
        )
    return report


__all__ = [
    "DEVELOPMENT_REQUEST_MODES",
    "GrantSatisfactionResult",
    "RELEASE_FAIL_CLOSED_MODES",
    "STRICT_REQUEST_MODES",
    "abstain_insufficient_authorization_context",
    "contracts_runtime_api_report",
    "migration_fallbacks_allowed",
    "request_contained_by_envelope",
    "request_satisfies_grant",
    "required_request_fields",
    "resolve_request_mode",
]
