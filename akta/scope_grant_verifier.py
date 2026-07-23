"""Authoritative SCOPE grant authentication (P0-C / P0-E).

Runs BEFORE AKTA applies any grant metadata. Prefer shared hashing + schemas
from scientific-authorization-contracts. Strict modes require issuer signature,
grant hash, trust-root provenance, source binding, and ledger/status attestation.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable
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
from akta.shared_contracts import (
    ENVELOPE_VERSION,
    GRANT_STATUS_SCHEMA_NAME,
    _contracts,
    authorization_envelope_schema_hash,
    load_contract_schema,
)
from akta.trust_store import resolve_trust_store

STRICT_MODES = frozenset({"pilot", "release", "cross_repo", "production"})
UNIT_MODES = frozenset({"unit", "dev", "test"})

# Ordered authentication sequence (P0-C). Each check records its name in checks_run.
REQUIRED_GRANT_CHECKS: tuple[str, ...] = (
    "grant_id_present",
    "not_simulated_in_release_modes",
    "authorization_envelope_present",
    "envelope_schema_version",
    "envelope_schema_hash",
    "envelope_vocabulary",
    "grant_hash_valid",
    "issuer_present",
    "issuer_signature_valid",
    "issuer_key_not_revoked",
    "source_packet_binding",
    "source_akta_record_binding",
    "trust_root_present",
    "policy_manifest_fresh",
    "ledger_status_active",
    "single_use_remaining",
    "expiration_valid",
    "allowed_tools_field_present",
    "allowed_tools_not_fabricated",
    "blocked_tools_consistent",
    "bound_context_present",
    "schema_version_supported",
)


@dataclass
class GrantVerificationResult:
    """Outcome of SCOPE grant verification before AKTA applies grant metadata."""

    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    capability_envelope: dict[str, Any] | None = None
    mode: str = "unit"
    checks_run: list[str] = field(default_factory=list)
    ledger_status: dict[str, Any] | None = None


def resolve_grant_verification_mode(explicit: str | None = None) -> str:
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
    auth = scope_grant.get("authorization") or {}
    envelope = extract_capability_envelope(scope_grant)
    if envelope is not None and "allowed_tools" in envelope:
        return True, list(envelope.get("allowed_tools") or [])
    if "allowed_tools" in scope_grant:
        return True, list(scope_grant.get("allowed_tools") or [])
    if "allowed_tools" in auth:
        return True, list(auth.get("allowed_tools") or [])
    return False, None


def _parse_iso(value: str) -> datetime:
    expiry = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    return expiry


def _expiration_invalid(scope_grant: dict[str, Any]) -> str | None:
    auth = scope_grant.get("authorization") or {}
    exp = scope_grant.get("expiration") or auth.get("expiration") or {}
    expires_at = None
    if isinstance(exp, dict):
        expires_at = exp.get("absolute_expiration")
    expires_at = expires_at or scope_grant.get("expires_at") or auth.get("expires_at")
    if not expires_at:
        return None
    try:
        if _parse_iso(str(expires_at)) <= datetime.now(timezone.utc):
            return f"SCOPE grant expired at {expires_at}"
    except ValueError:
        return f"SCOPE grant expiration is not valid ISO-8601: {expires_at!r}"
    return None


def _verify_grant_hash(scope_grant: dict[str, Any]) -> str | None:
    if "grant_hash" not in scope_grant:
        return "grant_hash missing"
    if not _contracts().verify_hash(scope_grant, "grant_hash"):
        return "grant_hash mismatch (invalid or tampered grant payload)"
    return None


def _issuer_signature_error(
    scope_grant: dict[str, Any],
    *,
    trust_store: dict[str, Any] | None,
    require_crypto: bool,
) -> str | None:
    """Verify issuer signature; fail closed when crypto trust store is required."""
    sig = scope_grant.get("grant_signature")
    if not sig:
        return "unsigned grant: grant_signature missing"
    issuer = scope_grant.get("issuer") or {}
    key_id = issuer.get("issuer_key_id")
    if not key_id:
        return "issuer.issuer_key_id missing"
    signed_payload = scope_grant.get("signed_payload_hash")
    if signed_payload is not None and signed_payload != scope_grant.get("grant_hash"):
        return "signed_payload_hash must equal grant_hash"
    if trust_store is None:
        if require_crypto:
            return "trust store required for issuer signature verification"
        # Structural presence only when no cryptographic trust store configured.
        return None
    revoked = set(trust_store.get("revoked_key_ids") or [])
    if key_id in revoked:
        return f"revoked issuer key: {key_id}"
    keys = trust_store.get("keys") or {}
    if require_crypto and not keys:
        return "trust store has no approved issuer keys"
    entry = keys.get(key_id)
    if entry is None:
        return f"unknown issuer key: {key_id}"
    status = str(entry.get("status") or "active").lower()
    if status == "revoked":
        return f"revoked issuer key: {key_id}"
    verifier: Callable[[dict[str, Any], str, str], bool] | None = trust_store.get("verify")
    if callable(verifier):
        try:
            if not verifier(scope_grant, "grant_hash", str(sig)):
                return "issuer signature invalid"
        except Exception as exc:  # noqa: BLE001
            return f"issuer signature verification failed: {exc}"
    elif require_crypto:
        return "trust store missing verify callback"
    return None


def _attestation_signature_error(
    attestation: dict[str, Any],
    *,
    trust_store: dict[str, Any] | None,
    require_crypto: bool,
) -> str | None:
    sig = attestation.get("attestation_signature")
    if not sig:
        return "grant status attestation_signature missing"
    if trust_store is None:
        return "trust store required for grant status attestation verification" if require_crypto else None
    verifier: Callable[[dict[str, Any], str, str], bool] | None = trust_store.get("verify")
    if not callable(verifier):
        return "trust store missing verify callback" if require_crypto else None
    # Prefer explicit attestation hash; fall back to grant_hash binding field.
    hash_field = "attestation_hash" if "attestation_hash" in attestation else "grant_hash"
    if hash_field not in attestation:
        return f"grant status missing {hash_field} for attestation verification"
    try:
        if not verifier(attestation, hash_field, str(sig)):
            return "grant status attestation_signature invalid"
    except Exception as exc:  # noqa: BLE001
        return f"grant status attestation verification failed: {exc}"
    return None


def _fetch_grant_status_attestation(
    grant_id: str,
    *,
    endpoint: str | None = None,
) -> dict[str, Any] | None:
    """Fetch signed grant-status attestation from SCOPE /grant-status endpoint."""
    base = (endpoint or os.environ.get("SCOPE_GRANT_STATUS_URL") or "").strip()
    if not base:
        return None
    url = base.rstrip("/")
    if "{grant_id}" in url:
        url = url.format(grant_id=grant_id)
    elif not url.endswith(grant_id):
        url = f"{url}/{grant_id}"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:  # noqa: S310
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _ledger_status_errors(
    scope_grant: dict[str, Any],
    *,
    ledger_status: dict[str, Any] | None,
    strict: bool,
    trust_store: dict[str, Any] | None = None,
    require_crypto: bool = False,
) -> list[str]:
    errors: list[str] = []
    if ledger_status is None:
        if strict and os.environ.get("SCOPE_GRANT_STATUS_URL"):
            errors.append("grant ledger status attestation unavailable")
        return errors
    status = str(ledger_status.get("status") or "")
    if status in {"revoked", "consumed", "expired", "superseded", "invalid", "not_found", "used"}:
        errors.append(f"grant ledger status={status}")
    if ledger_status.get("revoked") is True:
        errors.append("grant revoked per attestation")
    remaining = ledger_status.get("single_use_remaining")
    if remaining is None:
        remaining = ledger_status.get("cardinality_remaining")
    constraints = scope_grant.get("constraints") or {}
    if constraints.get("single_use") and remaining is not None and int(remaining) <= 0:
        errors.append("single-use grant already consumed")
    # Attestation verification for remote / provided status payloads
    remote = bool(os.environ.get("SCOPE_GRANT_STATUS_URL"))
    if strict and (remote or ledger_status.get("attestation_signature") is not None):
        expected_hash = scope_grant.get("grant_hash")
        if expected_hash and ledger_status.get("grant_hash") not in (None, expected_hash):
            errors.append("grant status grant_hash does not match grant")
        trust = (scope_grant.get("provenance") or {}).get("scope_trust_root_hash")
        if trust and ledger_status.get("scope_trust_root_hash") not in (None, trust):
            errors.append("grant status trust-root mismatch")
        # Schema shape (shared contract)
        try:
            import jsonschema

            schema = load_contract_schema(GRANT_STATUS_SCHEMA_NAME)
            jsonschema.validate(instance=ledger_status, schema=schema)
        except ImportError:
            pass
        except Exception as exc:  # noqa: BLE001
            errors.append(f"grant status attestation schema invalid: {exc}")
        sig_err = _attestation_signature_error(
            ledger_status,
            trust_store=trust_store,
            require_crypto=require_crypto or remote,
        )
        if sig_err:
            errors.append(sig_err)
    return errors


def _source_binding_errors(
    scope_grant: dict[str, Any],
    *,
    record: dict[str, Any] | None,
    trigger: dict[str, Any] | None,
    expected_packet_id: str | None,
) -> list[str]:
    errors: list[str] = []
    source = scope_grant.get("source") or {}
    if not source.get("packet_id"):
        errors.append("source.packet_id missing")
    if not source.get("decision_id"):
        errors.append("source.decision_id missing")
    if not source.get("akta_record_id"):
        errors.append("source.akta_record_id missing")
    if record is not None:
        record_id = record.get("record_id")
        if record_id and source.get("akta_record_id") not in (None, record_id):
            errors.append(
                f"grant bound to wrong AKTA record "
                f"({source.get('akta_record_id')} != {record_id})"
            )
    if expected_packet_id and source.get("packet_id") not in (None, expected_packet_id):
        errors.append(
            f"grant bound to wrong packet "
            f"({source.get('packet_id')} != {expected_packet_id})"
        )
    if trigger is not None:
        packet_id = trigger.get("packet_id") or (trigger.get("source") or {}).get("packet_id")
        if packet_id and source.get("packet_id") not in (None, packet_id):
            errors.append("grant packet_id does not match review trigger/packet")
    return errors


def _bound_context_errors(
    scope_grant: dict[str, Any],
    *,
    context: dict[str, Any] | None,
    strict: bool,
) -> list[str]:
    """P0-E: missing consequential bound context → abstain (error in strict)."""
    constraints = scope_grant.get("constraints") or {}
    expiration = scope_grant.get("expiration") or {}
    expires_after = list(expiration.get("expires_after") or [])
    if isinstance(expiration.get("expires_on"), str):
        expires_after.append(expiration["expires_on"])

    consequential = {
        "protocol_version_change": "protocol_version",
        "evidence_state_change": "evidence_state",
        "validation_status_change": "validation_status",
        "policy_version_change": "policy_manifest_hash",
        "model_version_change": "model_version",
        "tool_registry_change": "tool_registry_hash",
        "domain_overlay_change": "domain_overlay_hash",
        "safety_incident": "safety_incident_state",
    }
    errors: list[str] = []
    ctx = context or {}
    metadata = dict(ctx.get("metadata") or {})

    required_keys = {
        "protocol_version",
        "evidence_state",
        "validation_status",
        "policy_manifest_hash",
        "domain_overlay_hash",
        "model_version",
        "tool_registry_hash",
        "grant_use_count",
        "safety_incident_state",
    }
    # Always require presence of keys listed in expires_after bindings.
    for event in expires_after:
        key = consequential.get(str(event))
        if key:
            required_keys.add(key)

    if not strict:
        return errors

    for key in sorted(required_keys):
        bound = (
            constraints.get(key)
            or metadata.get(f"bound_{key}")
            or metadata.get(key)
            or ctx.get(key)
        )
        # Do not infer missing == bound.
        if bound is None and key in {
            "protocol_version",
            "evidence_state",
            "policy_manifest_hash",
            "tool_registry_hash",
        }:
            # Soft-required core keys when grant declares them in constraints.
            if key in constraints or any(
                consequential.get(str(e)) == key for e in expires_after
            ):
                errors.append(
                    f"missing consequential grant context {key!r}; "
                    "abstain / renewed review required (never infer missing == bound)"
                )
    return errors


def _tools_fabricated_error(scope_grant: dict[str, Any], envelope: dict[str, Any]) -> str | None:
    auth = scope_grant.get("authorization") or {}
    if "allowed_tools" not in auth and "allowed_tools" not in envelope:
        return None
    auth_tools = list(auth.get("allowed_tools") or [])
    env_tools = list(envelope.get("allowed_tools") or [])
    if auth_tools and env_tools and set(auth_tools) != set(env_tools):
        # Fabrication: auth allowlist must match envelope allowlist when both set.
        if not set(auth_tools).issubset(set(env_tools)) and not set(env_tools).issubset(
            set(auth_tools)
        ):
            return "fabricated allowed_tools list (authorization vs envelope mismatch)"
    return None


def verify_scope_grant(
    scope_grant: dict[str, Any],
    *,
    mode: str | None = None,
    require_capability_envelope: bool | None = None,
    record: dict[str, Any] | None = None,
    trigger: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
    expected_packet_id: str | None = None,
    trust_store: dict[str, Any] | None = None,
    ledger_status: dict[str, Any] | None = None,
    raise_on_error: bool = False,
) -> GrantVerificationResult:
    """Authenticate a SCOPE grant before apply (full P0-C sequence)."""
    resolved_mode = resolve_grant_verification_mode(mode)
    strict = resolved_mode in STRICT_MODES
    require_crypto = resolved_mode == "production" or os.environ.get(
        "AKTA_REQUIRE_GRANT_CRYPTO", ""
    ).lower() in ("1", "true", "yes")
    require_envelope = (
        require_capability_envelope
        if require_capability_envelope is not None
        else (strict or require_capability_envelope_env())
    )

    errors: list[str] = []
    warnings: list[str] = []
    checks_run: list[str] = []

    def _fail(msg: str, *, as_warning: bool = False) -> None:
        if as_warning:
            warnings.append(msg)
        else:
            errors.append(msg)

    resolved_trust = trust_store
    if resolved_trust is None and (
        require_crypto
        or os.environ.get("AKTA_TRUST_STORE_PATH")
        or os.environ.get("AKTA_ISSUER_KEY_REGISTRY")
    ):
        resolved_trust = resolve_trust_store(require_keys=require_crypto)
    if require_crypto and (resolved_trust is None or not (resolved_trust.get("keys") or {})):
        _fail("production/institutional trust store required (empty or missing issuer registry)")
    if require_crypto and resolved_trust is not None:
        from akta.trust_store import institutional_registry_is_empty

        if institutional_registry_is_empty(resolved_trust):
            _fail("production/institutional trust store required (empty or missing issuer registry)")

    # 1. grant_id
    checks_run.append("grant_id_present")
    grant_id = scope_grant.get("grant_id") or scope_grant.get("scope_grant_id")
    if not grant_id:
        _fail("grant_id missing", as_warning=not strict)

    # 2. simulated rejection
    checks_run.append("not_simulated_in_release_modes")
    if strict and _is_simulated(scope_grant):
        _fail(f"simulated SCOPE grant rejected in mode={resolved_mode} (P1-A / P0-C)")

    # 3–6. authorization envelope required in strict modes
    checks_run.append("authorization_envelope_present")
    envelope: dict[str, Any] | None = None
    raw_envelope = extract_capability_envelope(scope_grant)
    if raw_envelope is None and require_envelope:
        _fail(
            "authorization_envelope required; legacy scalar-only grant rejected (P0-B)"
        )
    else:
        try:
            envelope = resolve_grant_envelope(
                scope_grant,
                require_envelope=require_envelope,
                allow_legacy_adapter=not require_envelope,
            )
            checks_run.append("envelope_schema_version")
            if envelope.get("envelope_version") != ENVELOPE_VERSION:
                _fail(
                    f"unknown envelope version {envelope.get('envelope_version')!r} "
                    f"(expected {ENVELOPE_VERSION!r})"
                )
            checks_run.append("envelope_schema_hash")
            declared_hash = (
                scope_grant.get("authorization_schema_hash")
                or (scope_grant.get("authorization") or {}).get("authorization_schema_hash")
            )
            expected_hash = authorization_envelope_schema_hash()
            if declared_hash and declared_hash != expected_hash:
                _fail(
                    f"stale/mismatched authorization_schema_hash "
                    f"({declared_hash} != {expected_hash})"
                )
            checks_run.append("envelope_vocabulary")
            env_errors = validate_capability_envelope(envelope)
            if env_errors:
                # Unknown family/operation are hard failures.
                for err in env_errors:
                    _fail(err)
        except GrantVerificationError as exc:
            for err in exc.errors or [str(exc)]:
                _fail(err)

    # 7. grant hash
    checks_run.append("grant_hash_valid")
    hash_err = _verify_grant_hash(scope_grant)
    if hash_err:
        _fail(hash_err, as_warning=not strict)

    # 8–10. issuer + signature
    checks_run.append("issuer_present")
    issuer = scope_grant.get("issuer") or {}
    if not issuer.get("issuer_identity"):
        _fail("issuer.issuer_identity missing", as_warning=not strict)
    checks_run.append("issuer_signature_valid")
    checks_run.append("issuer_key_not_revoked")
    sig_err = _issuer_signature_error(
        scope_grant,
        trust_store=resolved_trust,
        require_crypto=require_crypto,
    )
    if sig_err:
        _fail(sig_err, as_warning=not strict)

    # 11–12. source bindings
    checks_run.append("source_packet_binding")
    checks_run.append("source_akta_record_binding")
    for err in _source_binding_errors(
        scope_grant,
        record=record,
        trigger=trigger,
        expected_packet_id=expected_packet_id,
    ):
        _fail(err, as_warning=not strict)

    # 13. trust root
    checks_run.append("trust_root_present")
    provenance = scope_grant.get("provenance") or {}
    if not provenance.get("scope_trust_root_hash"):
        _fail("provenance.scope_trust_root_hash missing", as_warning=not strict)

    # 14. policy manifest freshness hint
    checks_run.append("policy_manifest_fresh")
    if context is not None:
        current_manifest = (context.get("metadata") or {}).get("policy_manifest_hash")
        grant_manifest = (
            provenance.get("akta_policy_hash")
            or provenance.get("policy_manifest_hash")
            or (scope_grant.get("constraints") or {}).get("policy_manifest_hash")
        )
        if current_manifest and grant_manifest and current_manifest != grant_manifest:
            _fail("stale policy manifest relative to grant binding")

    # 15–16. ledger / single-use
    checks_run.append("ledger_status_active")
    checks_run.append("single_use_remaining")
    status_payload = ledger_status
    if status_payload is None and grant_id:
        status_payload = _fetch_grant_status_attestation(str(grant_id))
    for err in _ledger_status_errors(
        scope_grant,
        ledger_status=status_payload,
        strict=strict,
        trust_store=resolved_trust,
        require_crypto=require_crypto,
    ):
        _fail(err)

    # 17. expiration
    checks_run.append("expiration_valid")
    exp_err = _expiration_invalid(scope_grant)
    if exp_err:
        _fail(exp_err, as_warning=not strict)

    # 18–19. allowed tools
    checks_run.append("allowed_tools_field_present")
    present, tools = _allowed_tools_presence(scope_grant)
    if not present:
        _fail(
            "allowed_tools field absent; invalid SCOPE grant for runtime use",
            as_warning=not strict,
        )
    elif tools is not None and any(not isinstance(t, str) or not t for t in tools):
        _fail("allowed_tools entries must be non-empty strings")

    checks_run.append("allowed_tools_not_fabricated")
    if envelope is not None:
        fab = _tools_fabricated_error(scope_grant, envelope)
        if fab:
            _fail(fab)

    checks_run.append("blocked_tools_consistent")
    if envelope is not None:
        auth = scope_grant.get("authorization") or {}
        if "blocked_tools" in auth:
            auth_blocked = set(auth.get("blocked_tools") or [])
            env_blocked = set(envelope.get("blocked_tools") or [])
            if not auth_blocked.issubset(env_blocked) and not env_blocked.issubset(
                auth_blocked
            ):
                # Prefer envelope as authority; warn/fail if disjoint fabrication.
                if auth_blocked - env_blocked:
                    _fail("blocked_tools fabrication vs envelope")

    # 20. bound context (P0-E)
    checks_run.append("bound_context_present")
    for err in _bound_context_errors(scope_grant, context=context, strict=strict):
        _fail(err)

    checks_run.append("schema_version_supported")
    schema_version = (
        scope_grant.get("grant_version")
        or scope_grant.get("schema_version")
        or scope_grant.get("grant_schema_version")
        or (scope_grant.get("authorization") or {}).get("schema_version")
    )
    supported = {
        "2.0.0",
        "2.0",
        "scope-grant-v2",
        "0.5",
        "0.6",
        "0.7",
        "0.8",
        "0.9",
        "1.0",
        "akta-scope-grant-v1.0",
    }
    if schema_version and str(schema_version) not in supported:
        warnings.append(f"unrecognized grant schema_version: {schema_version!r}")

    # Scalar narrowing rank comparison intentionally removed from production paths.
    # Envelope set-inclusion is the sole authorization comparator in strict modes.

    result = GrantVerificationResult(
        ok=not errors,
        errors=errors,
        warnings=warnings,
        capability_envelope=envelope,
        mode=resolved_mode,
        checks_run=checks_run,
        ledger_status=status_payload,
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
    context: dict[str, Any] | None = None,
    expected_packet_id: str | None = None,
    trust_store: dict[str, Any] | None = None,
    ledger_status: dict[str, Any] | None = None,
) -> GrantVerificationResult:
    return verify_scope_grant(
        scope_grant,
        mode=mode,
        require_capability_envelope=require_capability_envelope,
        record=record,
        trigger=trigger,
        context=context,
        expected_packet_id=expected_packet_id,
        trust_store=trust_store,
        ledger_status=ledger_status,
        raise_on_error=True,
    )
