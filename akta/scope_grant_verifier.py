"""Authoritative SCOPE grant verifier (directive §4).

Runs BEFORE AKTA applies grant metadata. Prefer a shared SCOPE package /
grant-check API when available; offline fallback uses this embedded verifier
plus frozen fixtures under ``tests/contracts/``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from akta.capability_envelope import (
    extract_capability_envelope,
    resolve_grant_envelope,
    validate_capability_envelope,
)
from akta.errors import GrantVerificationError
from akta.policy_integrity import is_production_mode, require_signed_policy
from akta.scope_contract import (
    _scope_grant_approved_scope,
    _scope_grant_requested_scope,
    is_valid_narrowing_grant,
)

STRICT_MODES = frozenset({"pilot", "release", "cross_repo", "production"})
UNIT_MODES = frozenset({"unit", "dev", "test"})


@dataclass
class GrantVerificationResult:
    """Outcome of SCOPE grant verification before AKTA applies grant metadata."""

    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    capability_envelope: dict[str, Any] | None = None
    mode: str = "unit"
    checks_run: list[str] = field(default_factory=list)


REQUIRED_GRANT_CHECKS: tuple[str, ...] = (
    "schema_version_supported",
    "grant_id_present",
    "capability_envelope_present_or_legacy",
    "allowed_tools_field_present",
    "allowed_tools_exact_allowlist",
    "expiration_valid",
    "not_simulated_in_release_modes",
    "akta_may_only_narrow",
)


def resolve_grant_verification_mode(explicit: str | None = None) -> str:
    """Resolve grant verification mode from argument and environment.

    Priority: explicit arg > AKTA_GRANT_MODE > production/signed env > unit.
    """
    if explicit:
        return explicit.strip().lower()
    env_mode = os.environ.get("AKTA_GRANT_MODE", "").strip().lower()
    if env_mode:
        return env_mode
    if is_production_mode() or require_signed_policy():
        return "production"
    return "unit"


def require_capability_envelope_env() -> bool:
    return os.environ.get("AKTA_REQUIRE_CAPABILITY_ENVELOPE", "").lower() in (
        "1",
        "true",
        "yes",
    )


def _is_simulated(scope_grant: dict[str, Any]) -> bool:
    provenance = scope_grant.get("provenance") or {}
    adapter_mode = (
        provenance.get("adapter_mode")
        or scope_grant.get("adapter_mode")
        or ""
    )
    return adapter_mode == "simulated" or scope_grant.get("simulated") is True


def _allowed_tools_presence(scope_grant: dict[str, Any]) -> tuple[bool, list[str] | None]:
    """Return (field_present, tools_or_None)."""
    auth = scope_grant.get("authorization") or {}
    envelope = extract_capability_envelope(scope_grant)
    if envelope is not None and "allowed_tools" in envelope:
        return True, list(envelope.get("allowed_tools") or [])
    if "allowed_tools" in scope_grant:
        return True, list(scope_grant.get("allowed_tools") or [])
    if "allowed_tools" in auth:
        return True, list(auth.get("allowed_tools") or [])
    return False, None


def _expiration_invalid(scope_grant: dict[str, Any]) -> str | None:
    auth = scope_grant.get("authorization") or {}
    expires_at = scope_grant.get("expires_at") or auth.get("expires_at")
    if not expires_at:
        return None
    try:
        expiry = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if expiry <= datetime.now(timezone.utc):
            return f"SCOPE grant expired at {expires_at}"
    except ValueError:
        return f"SCOPE grant expires_at is not valid ISO-8601: {expires_at!r}"
    return None


def verify_scope_grant(
    scope_grant: dict[str, Any],
    *,
    mode: str | None = None,
    require_capability_envelope: bool | None = None,
    record: dict[str, Any] | None = None,
    trigger: dict[str, Any] | None = None,
    raise_on_error: bool = False,
) -> GrantVerificationResult:
    """Verify a SCOPE grant before apply.

    Fail-closed in pilot/release/cross_repo/production for:
    - missing ``allowed_tools`` field
    - simulated artifacts
    - verification errors
    - required capability envelope when configured
    """
    resolved_mode = resolve_grant_verification_mode(mode)
    strict = resolved_mode in STRICT_MODES
    require_envelope = (
        require_capability_envelope
        if require_capability_envelope is not None
        else require_capability_envelope_env()
    )

    errors: list[str] = []
    warnings: list[str] = []
    checks_run: list[str] = []

    # grant_id
    checks_run.append("grant_id_present")
    grant_id = scope_grant.get("grant_id") or scope_grant.get("scope_grant_id")
    if not grant_id:
        msg = "grant_id missing"
        if strict:
            errors.append(msg)
        else:
            warnings.append(msg)

    # simulated rejection
    checks_run.append("not_simulated_in_release_modes")
    if strict and _is_simulated(scope_grant):
        errors.append(
            f"simulated SCOPE grant rejected in mode={resolved_mode} (directive §2.4)"
        )

    # allowed_tools presence
    checks_run.append("allowed_tools_field_present")
    present, tools = _allowed_tools_presence(scope_grant)
    if not present:
        msg = (
            "allowed_tools field absent; invalid SCOPE grant for runtime use "
            "(directive §2.2)"
        )
        if strict:
            errors.append(msg)
        else:
            warnings.append(msg)
    else:
        checks_run.append("allowed_tools_exact_allowlist")
        # Empty list is valid (deny-all); non-empty is exact allowlist.
        if tools is not None and any(not isinstance(t, str) or not t for t in tools):
            errors.append("allowed_tools entries must be non-empty strings")

    # expiration
    checks_run.append("expiration_valid")
    exp_err = _expiration_invalid(scope_grant)
    if exp_err:
        if strict:
            errors.append(exp_err)
        else:
            warnings.append(exp_err)

    # capability envelope / legacy adapter
    checks_run.append("capability_envelope_present_or_legacy")
    envelope: dict[str, Any] | None = None
    try:
        envelope = resolve_grant_envelope(
            scope_grant,
            require_envelope=require_envelope,
            allow_legacy_adapter=not require_envelope,
        )
        env_errors = validate_capability_envelope(envelope)
        # legacy adapter always produces valid envelope; raw envelopes may not
        if extract_capability_envelope(scope_grant) is not None and env_errors:
            errors.extend(env_errors)
    except GrantVerificationError as exc:
        errors.extend(exc.errors or [str(exc)])

    # narrowing vs requested scope (legacy scalar bridge)
    checks_run.append("akta_may_only_narrow")
    granted = _scope_grant_approved_scope(scope_grant) or ""
    requested = _scope_grant_requested_scope(scope_grant, record, trigger) or ""
    if granted and requested:
        if granted != requested and not is_valid_narrowing_grant(
            granted_scope=granted, requested_scope=requested
        ):
            # Broadening grant is invalid for AKTA consumption
            from akta.scope_contract import scope_rank

            try:
                if scope_rank(granted) > scope_rank(requested):
                    errors.append(
                        f"SCOPE grant broadens requested scope "
                        f"({requested} -> {granted}); AKTA rejects broadening"
                    )
            except Exception:
                warnings.append(
                    f"could not compare scope ranks for {granted!r} vs {requested!r}"
                )

    # schema_version hint
    checks_run.append("schema_version_supported")
    schema_version = (
        scope_grant.get("schema_version")
        or scope_grant.get("grant_schema_version")
        or (scope_grant.get("authorization") or {}).get("schema_version")
    )
    if schema_version and str(schema_version) not in (
        "0.5",
        "0.6",
        "0.7",
        "0.8",
        "0.9",
        "1.0",
        "akta-scope-grant-v1.0",
    ):
        warnings.append(f"unrecognized grant schema_version: {schema_version!r}")

    result = GrantVerificationResult(
        ok=not errors,
        errors=errors,
        warnings=warnings,
        capability_envelope=envelope,
        mode=resolved_mode,
        checks_run=checks_run,
    )
    if raise_on_error and not result.ok:
        raise GrantVerificationError(
            "; ".join(result.errors) or "SCOPE grant verification failed",
            errors=result.errors,
        )
    return result


def verify_scope_grant_or_raise(
    scope_grant: dict[str, Any],
    *,
    mode: str | None = None,
    require_capability_envelope: bool | None = None,
    record: dict[str, Any] | None = None,
    trigger: dict[str, Any] | None = None,
) -> GrantVerificationResult:
    """Verify grant and raise GrantVerificationError on failure."""
    return verify_scope_grant(
        scope_grant,
        mode=mode,
        require_capability_envelope=require_capability_envelope,
        record=record,
        trigger=trigger,
        raise_on_error=True,
    )
