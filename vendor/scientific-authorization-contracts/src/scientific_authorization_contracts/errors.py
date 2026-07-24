"""Shared envelope validation / conflict errors."""

from __future__ import annotations

from typing import Any


class EnvelopeValidationError(ValueError):
    """Envelope failed schema or vocabulary validation."""

    def __init__(self, message: str, *, errors: list[str] | None = None) -> None:
        self.errors = list(errors or [message])
        super().__init__(message)


class EnvelopeConflictError(ValueError):
    """Envelopes cannot be safely intersected."""

    def __init__(self, message: str, *, conflict: dict[str, Any]) -> None:
        self.conflict = conflict
        super().__init__(message)
