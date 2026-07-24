"""UTC absolute expiration + event-set union on intersection."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from scientific_authorization_contracts.errors import EnvelopeValidationError


def parse_iso_utc(value: str | None) -> datetime | None:
    if value is None or value == "":
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise EnvelopeValidationError(
            f"Invalid absolute_expiration timestamp: {value}"
        ) from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def normalize_expiration(raw: dict[str, Any] | None) -> dict[str, Any]:
    data = dict(raw or {})
    events: list[str] = []
    if isinstance(data.get("expires_after"), list):
        events.extend(str(e) for e in data["expires_after"])
    elif data.get("expires_on"):
        events.append(str(data["expires_on"]))
    abs_exp = data.get("absolute_expiration")
    if abs_exp not in (None, ""):
        # Canonicalize to Zulu when parseable.
        parsed = parse_iso_utc(str(abs_exp))
        abs_exp = parsed.strftime("%Y-%m-%dT%H:%M:%SZ") if parsed else abs_exp
    else:
        abs_exp = None
    result: dict[str, Any] = {
        "absolute_expiration": abs_exp,
        "expires_after": sorted(set(events)),
    }
    if data.get("mode"):
        result["mode"] = data["mode"]
    return result


def expiration_is_shorter_or_equal(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """True if a is equal to or more restrictive than b."""
    a_n = normalize_expiration(a)
    b_n = normalize_expiration(b)
    if not b_n.get("absolute_expiration") and not b_n.get("expires_after"):
        return True
    if not a_n.get("absolute_expiration") and not a_n.get("expires_after"):
        return False

    a_abs = parse_iso_utc(a_n.get("absolute_expiration"))
    b_abs = parse_iso_utc(b_n.get("absolute_expiration"))
    if b_abs is not None:
        if a_abs is None or a_abs > b_abs:
            return False

    b_events = set(b_n.get("expires_after") or [])
    a_events = set(a_n.get("expires_after") or [])
    if b_events and not b_events.issubset(a_events):
        return False
    return True


def expiration_intersection(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    a_n = normalize_expiration(a)
    b_n = normalize_expiration(b)
    a_abs = parse_iso_utc(a_n.get("absolute_expiration"))
    b_abs = parse_iso_utc(b_n.get("absolute_expiration"))
    if a_abs is None:
        abs_exp = b_n.get("absolute_expiration")
    elif b_abs is None:
        abs_exp = a_n.get("absolute_expiration")
    else:
        abs_exp = (a_abs if a_abs <= b_abs else b_abs).strftime("%Y-%m-%dT%H:%M:%SZ")
    events = sorted(set(a_n.get("expires_after") or []) | set(b_n.get("expires_after") or []))
    return {"absolute_expiration": abs_exp, "expires_after": events}
