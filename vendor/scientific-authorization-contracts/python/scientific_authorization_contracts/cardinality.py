"""Cardinality field-by-field intersection and validation."""

from __future__ import annotations

from typing import Any

from scientific_authorization_contracts.errors import EnvelopeValidationError

MODE_RANK = {"single": 0, "bounded": 1, "unbounded": 2}


def _min_defined(a: Any, b: Any) -> Any:
    if a is None:
        return b
    if b is None:
        return a
    return min(int(a), int(b))


def narrowest_compatible_mode(a: str, b: str) -> str:
    if a not in MODE_RANK or b not in MODE_RANK:
        raise EnvelopeValidationError(f"Unknown cardinality mode: {a!r} / {b!r}")
    return a if MODE_RANK[a] <= MODE_RANK[b] else b


def normalize_cardinality(raw: dict[str, Any] | None) -> dict[str, Any]:
    data = dict(raw or {"mode": "unbounded"})
    mode = str(data.get("mode") or "unbounded")
    if mode not in MODE_RANK:
        raise EnvelopeValidationError(f"Unknown cardinality mode: {mode}")
    maximum_uses = data.get("maximum_uses")
    if maximum_uses is None and data.get("max") is not None:
        maximum_uses = data.get("max")
    maximum_items = data.get("maximum_items")
    if mode == "single":
        if maximum_uses is None:
            maximum_uses = 1
        if maximum_items is None:
            maximum_items = 1
    if maximum_uses is not None:
        maximum_uses = int(maximum_uses)
        if maximum_uses <= 0:
            raise EnvelopeValidationError("maximum_uses must be positive when set")
    if maximum_items is not None:
        maximum_items = int(maximum_items)
        if maximum_items <= 0:
            raise EnvelopeValidationError("maximum_items must be positive when set")
    if mode == "single" and maximum_uses is not None and maximum_uses > 1:
        raise EnvelopeValidationError("mode=single cannot have maximum_uses > 1")
    if mode == "bounded" and maximum_uses is None and maximum_items is None:
        raise EnvelopeValidationError("mode=bounded requires a finite maximum_uses or maximum_items")
    result: dict[str, Any] = {
        "mode": mode,
        "maximum_uses": maximum_uses,
        "maximum_items": maximum_items,
    }
    if "consumed_uses" in data:
        result["consumed_uses"] = int(data["consumed_uses"])
    return result


def cardinality_is_narrower_or_equal(a: dict[str, Any], b: dict[str, Any]) -> bool:
    a_n = normalize_cardinality(a)
    b_n = normalize_cardinality(b)
    if MODE_RANK[a_n["mode"]] > MODE_RANK[b_n["mode"]]:
        return False
    for field_name in ("maximum_uses", "maximum_items"):
        a_max = a_n.get(field_name)
        b_max = b_n.get(field_name)
        if b_max is not None and a_max is not None and int(a_max) > int(b_max):
            return False
        if b_max is not None and a_max is None and a_n["mode"] != "single":
            return False
    return True


def cardinality_intersection(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    a_n = normalize_cardinality(a)
    b_n = normalize_cardinality(b)
    mode = narrowest_compatible_mode(str(a_n["mode"]), str(b_n["mode"]))
    maximum_uses = _min_defined(a_n.get("maximum_uses"), b_n.get("maximum_uses"))
    maximum_items = _min_defined(a_n.get("maximum_items"), b_n.get("maximum_items"))
    if mode == "single":
        maximum_uses = 1 if maximum_uses is None else min(int(maximum_uses), 1)
        maximum_items = 1 if maximum_items is None else min(int(maximum_items), 1)
    return normalize_cardinality(
        {
            "mode": mode,
            "maximum_uses": maximum_uses,
            "maximum_items": maximum_items,
        }
    )
