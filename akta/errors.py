"""AKTA exception types."""


class AKTAError(Exception):
    """Base AKTA error."""


class PolicyError(AKTAError):
    """Policy bundle load or validation error."""


class SchemaValidationError(AKTAError):
    """JSON schema validation error."""


class UnsupportedProfileError(AKTAError):
    """Deployment profile not supported in v0.1."""


class ToolRegistryError(AKTAError):
    """Tool registry resolution error."""
