"""Runtime request containment against an authorization envelope."""

from __future__ import annotations

from typing import Any

from scientific_authorization_contracts.cardinality import normalize_cardinality
from scientific_authorization_contracts.constraints import evaluate_constraint_runtime
from scientific_authorization_contracts.envelope import AuthorizationEnvelope
from scientific_authorization_contracts.environments import normalize_environment
from scientific_authorization_contracts.errors import EnvelopeValidationError
from scientific_authorization_contracts.loaders import responsibility_rank
from scientific_authorization_contracts.operations import operation_covers
from scientific_authorization_contracts.targets import (
    normalize_target,
    target_is_narrower_or_equal,
)


def request_contained_by_envelope(
    envelope: AuthorizationEnvelope | dict[str, Any],
    request: dict[str, Any],
    *,
    uses_consumed: int = 0,
    require_bound_context: bool = True,
) -> tuple[bool, str | None]:
    """Return (ok, reason_code) for whether request is authorized by envelope."""
    env = (
        envelope
        if isinstance(envelope, AuthorizationEnvelope)
        else AuthorizationEnvelope.from_dict(envelope)
    )
    tool = request.get("requested_tool")
    if tool is None:
        return False, "insufficient_runtime_context"
    if tool in env.blocked_tools:
        return False, "tool_blocked"
    if tool not in env.allowed_tools and "*" not in env.allowed_tools:
        return False, "tool_not_allowed"

    if env.family and request.get("family") not in (None, env.family):
        return False, "family_not_covered"
    if require_bound_context and env.family and request.get("family") is None:
        # Family is intrinsic to the envelope; omit is ok if operation/target present.
        pass

    operation = request.get("operation")
    if operation:
        try:
            if not operation_covers(env.family, env.operation, str(operation)):
                return False, "operation_not_covered"
        except EnvelopeValidationError:
            return False, "operation_not_covered"
    elif require_bound_context:
        return False, "insufficient_runtime_context"

    if env.environment:
        try:
            runtime_env = normalize_environment(dict(request.get("environment") or {}))
        except EnvelopeValidationError:
            return False, "environment_not_covered"
        for key, value in env.environment.items():
            if key not in runtime_env:
                if require_bound_context:
                    return False, "insufficient_runtime_context"
                continue
            if runtime_env[key] != value:
                return False, "environment_not_covered"

    if env.target:
        runtime_target = dict(request.get("target") or {})
        if not runtime_target:
            if require_bound_context:
                return False, "insufficient_runtime_context"
        else:
            try:
                runtime_target = normalize_target(
                    runtime_target, allow_type_inference=False
                )
            except EnvelopeValidationError:
                return False, "target_not_covered"
            if not target_is_narrower_or_equal(runtime_target, env.target):
                return False, "target_not_covered"

    resp = request.get("responsibility_level")
    if resp:
        ranks = responsibility_rank()
        if ranks.get(str(resp), 99) > ranks.get(env.responsibility_ceiling, 0):
            return False, "responsibility_exceeded"
    elif require_bound_context and env.responsibility_ceiling:
        return False, "insufficient_runtime_context"

    card = normalize_cardinality(env.cardinality)
    mode = card.get("mode", "single")
    max_uses = card.get("maximum_uses")
    if mode == "single" and uses_consumed >= 1:
        return False, "cardinality_exhausted"
    if max_uses is not None and uses_consumed >= int(max_uses):
        return False, "cardinality_exhausted"
    item_count = int(request.get("item_count") or 1)
    max_items = card.get("maximum_items")
    if max_items is not None and item_count > int(max_items):
        return False, "cardinality_exceeded"

    ok, reason = evaluate_constraint_runtime(env.constraints, dict(request))
    if not ok:
        return False, reason
    return True, None
