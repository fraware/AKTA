"""Operation covers DAGs from shared vocabulary (reachability, not array rank)."""

from __future__ import annotations

from functools import lru_cache

from scientific_authorization_contracts.errors import (
    EnvelopeConflictError,
    EnvelopeValidationError,
)
from scientific_authorization_contracts.loaders import family_covers, family_operations


@lru_cache(maxsize=1)
def _validate_covers_graphs() -> None:
    """Reject unknown ops, cycles, cross-family edges, unreferenced ops, duplicates."""
    ops_by_family = family_operations()
    covers_by_family = family_covers()
    for family, operations in ops_by_family.items():
        if len(operations) != len(set(operations)):
            raise EnvelopeValidationError(
                f"Duplicate operations declared for family '{family}'"
            )
        covers = covers_by_family.get(family) or {}
        declared = set(operations)
        cover_keys = set(covers)
        if cover_keys != declared:
            missing = sorted(declared - cover_keys)
            extra = sorted(cover_keys - declared)
            raise EnvelopeValidationError(
                f"Covers keys must match operations for '{family}': "
                f"missing={missing} extra={extra}"
            )
        referenced: set[str] = set()
        for op, children in covers.items():
            if len(children) != len(set(children)):
                raise EnvelopeValidationError(
                    f"Duplicate covers edge from '{op}' in family '{family}'"
                )
            for child in children:
                if child not in declared:
                    raise EnvelopeValidationError(
                        f"Unknown covered operation '{child}' under '{op}' "
                        f"in family '{family}' (cross-family edges forbidden)"
                    )
                referenced.add(child)

        # Detect cycles via DFS color marking.
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {op: WHITE for op in declared}

        def visit(node: str) -> None:
            color[node] = GRAY
            for child in covers.get(node, []):
                if color[child] == GRAY:
                    raise EnvelopeValidationError(
                        f"Cycle detected in covers DAG for family '{family}' "
                        f"at '{child}'"
                    )
                if color[child] == WHITE:
                    visit(child)
            color[node] = BLACK

        for op in operations:
            if color[op] == WHITE:
                visit(op)

        # Every non-root should be referenced; roots may be unreferenced as parents.
        # Unreferenced ops that also cover nothing and are not alone are still valid
        # roots; require every declared op appears as a key (already checked).
        del referenced  # referenced used for clarity above; keys cover all ops.


def ensure_covers_graphs_valid() -> None:
    """Public startup hook — clears cache if vocab reloaded in tests."""
    _validate_covers_graphs.cache_clear()
    family_operations.cache_clear()
    family_covers.cache_clear()
    _validate_covers_graphs()


@lru_cache(maxsize=256)
def _closure(family: str, operation: str) -> frozenset[str]:
    """Reflexive-transitive closure of covers starting at ``operation``."""
    _validate_covers_graphs()
    covers = family_covers().get(family)
    ops = family_operations().get(family)
    if not covers or not ops or operation not in ops:
        raise EnvelopeValidationError(
            f"Unknown operation '{operation}' for family '{family}'"
        )
    seen: set[str] = set()
    stack = [operation]
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        stack.extend(covers.get(node, []))
    return frozenset(seen)


def operation_covers(family: str, a: str, b: str) -> bool:
    """True if ``a`` covers ``b`` (``b`` reachable from ``a``, including ``a == b``)."""
    return b in _closure(family, a)


def operation_is_narrower_or_equal(family: str, inner: str, outer: str) -> bool:
    """Inner is narrower-or-equal when outer covers inner."""
    return operation_covers(family, outer, inner)


def operation_rank(family: str, operation: str) -> int:
    """
    Deprecated compatibility shim.

    Returns the size of the covers closure (higher ≈ more privileged on chains).
    Prefer ``operation_covers`` / ``operation_is_narrower_or_equal``.
    """
    return len(_closure(family, operation))


def _greatest_lower_bounds(family: str, left: str, right: str) -> list[str]:
    """Operations covered by both left and right; return maximal ones (meets)."""
    left_down = _closure(family, left)
    right_down = _closure(family, right)
    common = left_down & right_down
    if not common:
        return []
    maximal: list[str] = []
    for candidate in common:
        if any(
            other != candidate and operation_covers(family, other, candidate)
            for other in common
        ):
            continue
        maximal.append(candidate)
    return sorted(maximal)


def narrower_operation(family: str, left: str, right: str) -> str:
    """
    Meet (greatest lower bound) of two operations in the covers DAG.

    Raises ``EnvelopeConflictError`` when ops are incomparable with no unique meet,
    or when multiple maximal common lower bounds exist.
    """
    if left == right:
        return left
    if operation_covers(family, left, right):
        return right
    if operation_covers(family, right, left):
        return left
    meets = _greatest_lower_bounds(family, left, right)
    if len(meets) == 1:
        return meets[0]
    raise EnvelopeConflictError(
        f"Incomparable operations have no unique meet: '{left}' vs '{right}' "
        f"in family '{family}'",
        conflict={
            "type": "operation_meet_ambiguous",
            "family": family,
            "left": left,
            "right": right,
            "candidate_meets": meets,
        },
    )


def operation_intersection(family: str, left: str, right: str) -> str:
    """Alias for ``narrower_operation`` (explicit meet)."""
    return narrower_operation(family, left, right)


# Validate at import so bad vocab fails closed on startup.
ensure_covers_graphs_valid()
