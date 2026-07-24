"""Per-type constraint registry with contains/intersection/difference/runtime evaluators."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from scientific_authorization_contracts.errors import (
    EnvelopeConflictError,
    EnvelopeValidationError,
)
from scientific_authorization_contracts.loaders import constraint_types

RuntimeEvaluator = Callable[[Any, dict[str, Any]], bool]
ContainsFn = Callable[[Any, Any, dict[str, Any]], bool]
IntersectionFn = Callable[[Any, Any, dict[str, Any]], Any]
DifferenceFn = Callable[[Any, Any, dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class ConstraintHandler:
    schema: dict[str, Any]
    contains: ContainsFn
    intersection: IntersectionFn
    difference: DifferenceFn
    runtime_evaluator: RuntimeEvaluator


def _bool_and_contains(outer: Any, inner: Any, _spec: dict[str, Any]) -> bool:
    return not (bool(outer) and not bool(inner))


def _bool_and_intersection(a: Any, b: Any, _spec: dict[str, Any]) -> bool:
    return bool(a) and bool(b)


def _bool_or_contains(outer: Any, inner: Any, _spec: dict[str, Any]) -> bool:
    # Mandatory control: outer requiring true means inner must also be true.
    return not (bool(outer) and not bool(inner))


def _bool_or_intersection(a: Any, b: Any, _spec: dict[str, Any]) -> bool:
    # true ∩ false = true for mandatory controls.
    return bool(a) or bool(b)


def _min_ub_contains(outer: Any, inner: Any, _spec: dict[str, Any]) -> bool:
    return float(inner) <= float(outer)


def _min_ub_intersection(a: Any, b: Any, spec: dict[str, Any]) -> Any:
    result = min(float(a), float(b))
    return int(result) if spec.get("value_type") == "integer" else result


def _max_lb_contains(outer: Any, inner: Any, _spec: dict[str, Any]) -> bool:
    return float(inner) >= float(outer)


def _max_lb_intersection(a: Any, b: Any, spec: dict[str, Any]) -> Any:
    result = max(float(a), float(b))
    return int(result) if spec.get("value_type") == "integer" else result


def _set_inter_contains(outer: Any, inner: Any, _spec: dict[str, Any]) -> bool:
    return set(inner).issubset(set(outer))


def _set_inter_intersection(a: Any, b: Any, _spec: dict[str, Any]) -> list[Any]:
    return sorted(set(a) & set(b))


def _set_union_contains(outer: Any, inner: Any, _spec: dict[str, Any]) -> bool:
    return set(outer).issubset(set(inner))


def _set_union_intersection(a: Any, b: Any, _spec: dict[str, Any]) -> list[Any]:
    return sorted(set(a) | set(b))


def _max_req_contains(outer: Any, inner: Any, spec: dict[str, Any]) -> bool:
    order = list(spec.get("ordered_values") or [])
    return order.index(str(inner)) >= order.index(str(outer))


def _max_req_intersection(a: Any, b: Any, spec: dict[str, Any]) -> str:
    order = list(spec.get("ordered_values") or [])
    return order[max(order.index(str(a)), order.index(str(b)))]


def _exact_contains(outer: Any, inner: Any, _spec: dict[str, Any]) -> bool:
    return outer == inner


def _exact_intersection(a: Any, b: Any, spec: dict[str, Any]) -> Any:
    if a != b:
        raise EnvelopeConflictError(
            f"Incompatible constraint '{spec.get('_key')}'",
            conflict={
                "type": "constraint_conflict",
                "key": spec.get("_key"),
                "left": a,
                "right": b,
            },
        )
    return a


def _generic_difference(a: Any, b: Any, _spec: dict[str, Any]) -> dict[str, Any]:
    return {"left": a, "right": b, "equal": a == b}


def _runtime_bool_required(expected: Any, runtime: dict[str, Any]) -> bool:
    """
    Mandatory/permission booleans.

    When the constraint requires true, evidence must be present and bound:
    ``control_evidence.<name>.satisfied`` plus ``artifact_id``/``artifact_hash``
    (or ``trace_id``/``trace_hash``). Missing evidence fails closed — never
    default ``runtime.get("satisfied", True)``.
    """
    if not bool(expected):
        return True
    key = runtime.get("_constraint_key")
    if not key:
        return False

    # Direct key still allowed for non-mandatory permission booleans with explicit ctx.
    evidence_root = runtime.get("control_evidence")
    if isinstance(evidence_root, dict) and key in evidence_root:
        entry = evidence_root.get(key)
        if not isinstance(entry, dict):
            return False
        if not bool(entry.get("satisfied")):
            return False
        has_artifact = bool(entry.get("artifact_id") and entry.get("artifact_hash"))
        has_trace = bool(entry.get("trace_id") and entry.get("trace_hash"))
        return has_artifact or has_trace

    # Fail closed: required control with no bound evidence.
    if key in runtime and not isinstance(evidence_root, dict):
        # Explicit boolean only for permission_boolean class without evidence bag.
        return bool(runtime[key])
    return False


def _runtime_exact(expected: Any, runtime: dict[str, Any]) -> bool:
    key = runtime.get("_constraint_key")
    if key and key in runtime:
        return runtime[key] == expected
    return runtime.get("value") == expected


def _runtime_min_ub(expected: Any, runtime: dict[str, Any]) -> bool:
    value = runtime.get("value", runtime.get("observed"))
    if value is None:
        return False
    return float(value) <= float(expected)


def _runtime_max_lb(expected: Any, runtime: dict[str, Any]) -> bool:
    value = runtime.get("value", runtime.get("observed"))
    if value is None:
        return False
    return float(value) >= float(expected)


def _runtime_set_inter(expected: Any, runtime: dict[str, Any]) -> bool:
    observed = runtime.get("value", runtime.get("observed"))
    if observed is None:
        return False
    return set(observed).issubset(set(expected))


def _runtime_set_union(expected: Any, runtime: dict[str, Any]) -> bool:
    observed = runtime.get("value", runtime.get("observed"))
    if observed is None:
        return False
    return set(expected).issubset(set(observed))


def _runtime_max_req(expected: Any, runtime: dict[str, Any]) -> bool:
    order = list(runtime.get("ordered_values") or [])
    observed = runtime.get("value", runtime.get("observed"))
    if observed is None or not order:
        return False
    return order.index(str(observed)) >= order.index(str(expected))


_ALGEBRA_HANDLERS: dict[str, tuple[ContainsFn, IntersectionFn, RuntimeEvaluator]] = {
    "boolean_and": (_bool_and_contains, _bool_and_intersection, _runtime_bool_required),
    "boolean_or": (_bool_or_contains, _bool_or_intersection, _runtime_bool_required),
    "min_upper_bound": (_min_ub_contains, _min_ub_intersection, _runtime_min_ub),
    "max_lower_bound": (_max_lb_contains, _max_lb_intersection, _runtime_max_lb),
    "set_intersection": (_set_inter_contains, _set_inter_intersection, _runtime_set_inter),
    "set_union": (_set_union_contains, _set_union_intersection, _runtime_set_union),
    "max_requirement": (_max_req_contains, _max_req_intersection, _runtime_max_req),
    "exact_match": (_exact_contains, _exact_intersection, _runtime_exact),
}


def _build_registry() -> dict[str, ConstraintHandler]:
    registry: dict[str, ConstraintHandler] = {}
    for key, spec in constraint_types().items():
        algebra = str(spec["algebra"])
        if algebra not in _ALGEBRA_HANDLERS:
            raise EnvelopeValidationError(f"Unknown constraint algebra: {algebra}")
        contains_fn, intersection_fn, runtime_fn = _ALGEBRA_HANDLERS[algebra]
        registry[key] = ConstraintHandler(
            schema=dict(spec),
            contains=contains_fn,
            intersection=intersection_fn,
            difference=_generic_difference,
            runtime_evaluator=runtime_fn,
        )
    return registry


_REGISTRY: dict[str, ConstraintHandler] | None = None


def constraint_registry() -> dict[str, ConstraintHandler]:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = _build_registry()
    return _REGISTRY


def ensure_constraint_registry_complete() -> None:
    declared = set(constraint_types())
    registered = set(constraint_registry())
    missing = declared - registered
    if missing:
        raise EnvelopeValidationError(
            f"Constraint types missing registry handlers: {sorted(missing)}"
        )


def validate_constraints(constraints: dict[str, Any]) -> None:
    registry = constraint_registry()
    for key in constraints:
        if key not in registry:
            raise EnvelopeValidationError(
                f"Unknown constraint '{key}' fails closed (not in shared vocabulary)"
            )


def constraint_contains(outer: dict[str, Any], inner: dict[str, Any]) -> bool:
    validate_constraints(outer)
    validate_constraints(inner)
    registry = constraint_registry()
    keys = set(outer) | set(inner)
    for key in keys:
        handler = registry[key]
        if key not in outer:
            continue
        if key not in inner:
            return False
        if not handler.contains(outer[key], inner[key], {**handler.schema, "_key": key}):
            return False
    return True


def constraint_intersection(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    validate_constraints(a)
    validate_constraints(b)
    registry = constraint_registry()
    result: dict[str, Any] = {}
    for key in set(a) | set(b):
        handler = registry[key]
        if key not in a:
            result[key] = b[key]
            continue
        if key not in b:
            result[key] = a[key]
            continue
        result[key] = handler.intersection(
            a[key], b[key], {**handler.schema, "_key": key}
        )
    return result


def constraint_difference(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    validate_constraints(a)
    validate_constraints(b)
    return {
        "only_in_left": {k: a[k] for k in a if k not in b or a[k] != b.get(k)},
        "only_in_right": {k: b[k] for k in b if k not in a or b[k] != a.get(k)},
        "left_contains_right": constraint_contains(a, b),
        "right_contains_left": constraint_contains(b, a),
    }


def evaluate_constraint_runtime(
    constraints: dict[str, Any], runtime: dict[str, Any]
) -> tuple[bool, str | None]:
    validate_constraints(constraints)
    registry = constraint_registry()
    for key, value in constraints.items():
        ctx = dict(runtime)
        ctx["_constraint_key"] = key
        if key in registry[key].schema.get("ordered_values", []) or False:
            pass
        if "ordered_values" in registry[key].schema:
            ctx.setdefault("ordered_values", registry[key].schema["ordered_values"])
        if not registry[key].runtime_evaluator(value, ctx):
            return False, f"constraint_not_satisfied:{key}"
    return True, None
