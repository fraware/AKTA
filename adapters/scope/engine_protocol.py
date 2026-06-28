"""Expected SCOPE engine interface for python-import adapter mode (v0.5).

When ``SCOPE_REPO_PATH`` is set, ``adapters.scope.client`` discovers ``ScopeEngine``
from the sibling SCOPE repository and invokes the v0.5 API below. There is no
simulated fallback when import or invocation fails.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ScopeEngineClassProtocol(Protocol):
    """SCOPE v0.5 engine factory consumed by AKTA's python-import adapter."""

    @classmethod
    def from_policy_dir(
        cls,
        policy_dir: str | Any | None = None,
        *,
        ledger_path: str | Any | None = None,
        session_store: Any | None = None,
    ) -> ScopeEngineProtocol:
        """Construct engine from SCOPE policy directory."""


@runtime_checkable
class ScopeEngineProtocol(Protocol):
    """Minimal SCOPE v0.5 engine surface consumed by AKTA's python-import adapter."""

    def create_packet(
        self,
        akta_record: str | Any | dict[str, Any] | None = None,
        akta_trigger: str | Any | dict[str, Any] | None = None,
        *,
        vsa_report: str | Any | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build a SCOPE review packet from AKTA record and/or review trigger."""

    def submit_decision(
        self,
        packet: dict[str, Any],
        reviewer: str | Any | dict[str, Any],
        decision: dict[str, Any],
    ) -> dict[str, Any]:
        """Record reviewer decision for a review packet."""

    def issue_grant(
        self,
        packet: dict[str, Any],
        decision: dict[str, Any],
        *,
        constraints: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Issue a scoped approval grant from packet and SCOPE decision."""
