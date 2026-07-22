"""Session-scoped grant store for multi-turn agent harness (v1.0)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from akta.review_decision import enforce_grant_expiry, is_review_expired


def _parse_iso(ts: str) -> datetime | None:
    try:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


@dataclass
class SessionGrant:
    """Active SCOPE grant bound to an agent session."""

    scope_grant: dict[str, Any]
    bound_evidence_state: str | None = None
    bound_protocol_version: str | None = None
    created_at: str = ""
    invalidated: bool = False
    invalid_reason: str | None = None

    def expires_at(self) -> str | None:
        auth = self.scope_grant.get("authorization") or {}
        return (
            self.scope_grant.get("expires_at")
            or auth.get("expires_at")
            or (self.scope_grant.get("metadata") or {}).get("expires_at")
        )

    def is_expired(self) -> bool:
        exp = self.expires_at()
        return bool(exp and is_review_expired(exp))


@dataclass
class SessionGrantStore:
    """In-memory grant store with expiry and evidence downgrade invalidation."""

    grants: dict[str, SessionGrant] = field(default_factory=dict)

    def put(
        self,
        session_id: str,
        scope_grant: dict[str, Any],
        *,
        bound_evidence_state: str | None = None,
        bound_protocol_version: str | None = None,
    ) -> SessionGrant:
        entry = SessionGrant(
            scope_grant=dict(scope_grant),
            bound_evidence_state=bound_evidence_state,
            bound_protocol_version=bound_protocol_version,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self.grants[session_id] = entry
        return entry

    def get(self, session_id: str) -> SessionGrant | None:
        entry = self.grants.get(session_id)
        if entry is None:
            return None
        if entry.invalidated or entry.is_expired():
            entry.invalidated = True
            entry.invalid_reason = entry.invalid_reason or "SCOPE grant expired"
            return entry
        return entry

    def invalidate(self, session_id: str, reason: str) -> None:
        entry = self.grants.get(session_id)
        if entry:
            entry.invalidated = True
            entry.invalid_reason = reason

    def apply_to_context(
        self,
        session_id: str,
        context: dict[str, Any],
    ) -> tuple[dict[str, Any], SessionGrant | None]:
        """Return context with grant metadata; invalidate on evidence/protocol downgrade."""
        entry = self.get(session_id)
        if entry is None or entry.invalidated:
            return enforce_grant_expiry(context), entry

        ctx = enforce_grant_expiry(dict(context))
        current_evidence = ctx.get("evidence_state")
        current_protocol = ctx.get("protocol_version") or ctx.get("active_protocol_id")

        if entry.bound_evidence_state and current_evidence:
            from akta.review_loop import _evidence_rank

            if _evidence_rank(str(current_evidence)) < _evidence_rank(entry.bound_evidence_state):
                self.invalidate(session_id, "Evidence downgraded; grant invalidated")
                return ctx, self.get(session_id)

        if entry.bound_protocol_version and current_protocol:
            if str(entry.bound_protocol_version) != str(current_protocol):
                self.invalidate(session_id, "Protocol context changed; grant invalidated")
                return ctx, self.get(session_id)

        metadata = dict(ctx.get("metadata") or {})
        metadata["session_grant_active"] = True
        ctx["metadata"] = metadata
        return ctx, entry

    def clear(self, session_id: str) -> None:
        self.grants.pop(session_id, None)
