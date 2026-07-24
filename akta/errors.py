"""AKTA exception types."""


class AKTAError(Exception):
    """Base AKTA error."""


class PolicyError(AKTAError):
    """Policy bundle load or validation error."""


class SchemaValidationError(AKTAError):
    """JSON schema validation error."""


class UnsupportedProfileError(AKTAError):
    """Deployment profile not supported by AKTA.

    P7 (fully autonomous scientific operator) is a permanent non-goal in AKTA
    unless the Open Scientific Action Protocol explicitly adds runtime support.
    """

    def __init__(self, profile: str, reason: str = "") -> None:
        self.profile = profile
        msg = (
            f"Deployment profile {profile} is not supported by AKTA. "
            f"{reason or 'This profile is defined for taxonomy reference only.'} "
            "P7 fully autonomous scientific operation is a permanent non-goal "
            "unless the AKTA specification changes."
        )
        super().__init__(msg)


class AKTAReviewRequired(AKTAError):
    """Tool execution requires human review before proceeding."""

    def __init__(self, tool_name: str, trigger: dict | None = None, reason: str = "") -> None:
        self.tool_name = tool_name
        self.trigger = trigger or {}
        self.reason = reason
        super().__init__(reason or f"Review required before executing {tool_name}")


class ToolRegistryError(AKTAError):
    """Tool registry resolution error."""


class GrantVerificationError(AKTAError):
    """SCOPE grant failed pre-application verification (directive §4)."""

    def __init__(self, message: str, *, errors: list[str] | None = None) -> None:
        self.errors = list(errors or [])
        super().__init__(message)


class InsufficientAuthorizationContext(AKTAError):
    """Requested action is missing fields required for authorization evaluation.

    Raised in strict modes when ``required_request_fields(family, operation)``
    is not fully supplied. Callers must not invent defaults (``unspecified``,
    ``default``, tool-name heuristics).
    """

    def __init__(
        self,
        message: str = "",
        *,
        missing: frozenset[str] | set[str] | list[str] | None = None,
        family: str | None = None,
        operation: str | None = None,
    ) -> None:
        self.missing: frozenset[str] = frozenset(missing or ())
        self.family = family
        self.operation = operation
        parts = []
        if family or operation:
            parts.append(f"family={family!r} operation={operation!r}")
        if self.missing:
            parts.append(f"missing={sorted(self.missing)}")
        detail = "; ".join(parts)
        super().__init__(
            message
            or (
                f"InsufficientAuthorizationContext: {detail}"
                if detail
                else "InsufficientAuthorizationContext"
            )
        )
