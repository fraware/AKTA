"""Expected SCOPE engine interface for python-import adapter mode (v0.5).

When ``SCOPE_REPO_PATH`` is set, ``adapters.scope.client`` discovers a class from the
sibling SCOPE repository and invokes the methods below. Discovery order:

1. ``scope.ScopeEngine`` (preferred)
2. ``Scope``, ``ReviewEngine``, ``ScopeReviewEngine`` (compat aliases)

If a method is missing, the adapter falls back to AKTA contract simulation for that step.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ScopeEngineProtocol(Protocol):
    """Minimal SCOPE engine surface consumed by AKTA's python-import adapter."""

    def create_packet(
        self,
        trigger: dict[str, Any],
        record: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build a SCOPE review packet from an AKTA review trigger and optional record."""

    def submit_decision(
        self,
        packet: dict[str, Any],
        granted_scope: str,
        reviewer_id: str,
    ) -> dict[str, Any]:
        """Record reviewer decision for a review packet."""

    def issue_grant(
        self,
        decision: dict[str, Any],
        trigger: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Issue a scoped approval grant from a SCOPE decision."""


# Alternate method names accepted by ``adapters.scope.client`` (same semantics).
COMPAT_METHOD_ALIASES: dict[str, tuple[str, ...]] = {
    "create_packet": ("packet_create",),
    "submit_decision": ("decision_submit",),
    "issue_grant": ("grant_issue",),
}
