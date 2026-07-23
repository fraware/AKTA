"""Runtime requested-authorization model shared by SCOPE issuers and AKTA consumers.

AKTA 1.1 Phase C (WS8) builds and compares this shape against granted envelopes.
The dataclass lives in the contracts package so both repos share one type.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class RequestedAuthorizationContext:
    """Concrete runtime request to be checked for grant containment."""

    family: str
    operation: str
    target: dict[str, Any] = field(default_factory=dict)
    requested_tool: str = ""
    environment: dict[str, Any] = field(default_factory=dict)
    responsibility_level: str = "R3_recommendation"
    item_count: int = 1
    constraints: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RequestedAuthorizationContext:
        return cls(
            family=str(data["family"]),
            operation=str(data["operation"]),
            target=dict(data.get("target") or {}),
            requested_tool=str(data.get("requested_tool") or ""),
            environment=dict(data.get("environment") or {}),
            responsibility_level=str(
                data.get("responsibility_level") or "R3_recommendation"
            ),
            item_count=int(data.get("item_count") or 1),
            constraints=dict(data.get("constraints") or {}),
        )

    def as_envelope_request(self) -> dict[str, Any]:
        """Project into envelope fields used by ``envelope_covers``."""
        return {
            "family": self.family,
            "operation": self.operation,
            "target": dict(self.target),
            "allowed_tools": [self.requested_tool] if self.requested_tool else [],
            "blocked_tools": [],
            "cardinality": {
                "mode": "bounded" if self.item_count > 1 else "single",
                "maximum_uses": self.item_count,
            },
            "environment": dict(self.environment),
            "responsibility_ceiling": self.responsibility_level,
            "constraints": dict(self.constraints),
            "expiration": {},
        }


__all__ = ["RequestedAuthorizationContext"]
