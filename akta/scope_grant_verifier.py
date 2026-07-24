"""Authoritative SCOPE grant authentication (AKTA 1.2 P0-6 … P0-10).

Runs BEFORE AKTA applies any grant metadata. Prefer shared hashing + schemas
from scientific-authorization-contracts. Strict modes require issuer signature,
grant hash, trust-root provenance, source-chain id+hash bindings, and a verified
signed status attestation (or authenticated ledger verifier). Replay state is
durable and never stored on the untrusted grant dict.
"""

from __future__ import annotations

import os
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
from akta.hash import hash_object
from akta.lifecycle_semantics import check_expires_after_bindings, status_lifecycle_errors
from akta.policy_integrity import is_production_mode, require_signed_policy
from akta.scope_authorization_manifest import (
    resolve_and_verify_authorization_manifest,
)
from akta.scope_client import (
    LedgerStatusVerifier,
    ScopeAuthorizationClient,
    ScopeClientError,
)
from akta.shared_contracts import (
    ENVELOPE_VERSION,
    GRANT_STATUS_SCHEMA_NAME,
    GRANT_V2_SCHEMA_NAME,
    _contracts,
    authorization_envelope_schema_hash,
    load_contract_schema,
)
from akta.status_replay_store import (
    StatusReplayStore,
    status_hash_for_replay,
)
from akta.trust_store import (
    ArtifactType,
    institutional_registry_is_empty,
    resolve_grant_issuer_trust_store,
    resolve_manifest_signer_trust_store,
    resolve_status_attestation_trust_store,
)

STRICT_MODES = frozenset({"pilot", "release", "cross_repo", "production"})
UNIT_MODES = frozenset({"unit", "dev", "test"})
SUPPORTED_SIGNATURE_ALGORITHMS = frozenset({"Ed25519", "ed25519"})
# Strict modes accept only institutional grant v2 identifiers.
STRICT_GRANT_VERSIONS = frozenset(
    {"2.0.0", "2.0", "2.1.0", "2.2.0", "2.2", "scope-grant-v2"}
)
LEGACY_GRANT_VERSIONS = frozenset(
    {"0.5", "0.6", "0.7", "0.8", "0.9", "1.0", "akta-scope-grant-v1.0"}
)
# Default max age for signed status attestations (seconds).
DEFAULT_MAX_STATUS_AGE_SECONDS = 300

# Source-chain hash field pairs: (id_field, hash_field, artifact_key)
SOURCE_HASH_BINDINGS: tuple[tuple[str, str, str], ...] = (
    ("akta_record_id", "akta_record_hash", "record"),
    ("akta_record_id", "record_hash", "record"),
    ("decision_id", "decision_hash", "decision"),
    ("review_trigger_id", "review_trigger_hash", "review_trigger"),
    ("packet_id", "packet_hash", "packet"),
    ("scope_decision_id", "scope_decision_hash", "scope_decision"),
    ("session_resolution_id", "session_resolution_hash", "session_resolution"),
    ("session_id", "resolution_hash", "session_resolution"),
)

# Always required in strict modes (Session Resolution is conditional).
STRICT_REQUIRED_SOURCE_BINDINGS: tuple[tuple[str, str], ...] = (
    ("decision_id", "decision_hash"),
    ("akta_record_id", "akta_record_hash"),
    ("review_trigger_id", "review_trigger_hash"),
    ("packet_id", "packet_hash"),
    ("scope_decision_id", "scope_decision_hash"),
)

SIGNED_ARTIFACT_REF_FIELDS: tuple[str, ...] = (
    "artifact_id",
    "artifact_hash",
    "store_id",
    "tenant_id",
    "attestation",
)

ACTIVE_GRANT_STATUSES = frozenset({"active"})
REJECTED_GRANT_STATUSES = frozenset(
    {
        "exhausted",
        "consumed",
        "used",
        "revoked",
        "expired",
        "superseded",
        "invalid",
        "not_found",
    }
)


def _env_require_grant_crypto() -> bool:
    return os.environ.get("AKTA_REQUIRE_GRANT_CRYPTO", "").lower() in (
        "1",
        "true",
        "yes",
    )


def _require_cryptography_for_strict() -> str | None:
    """Fail closed when cryptography cannot be imported in crypto-required modes."""
    try:
        import cryptography  # noqa: F401
    except ImportError:
        return "cryptography package required for strict SCOPE grant verification"
    return None

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
    authorization_manifest_hash: str | None = None


def _max_status_age_seconds() -> int:
    raw = os.environ.get("AKTA_MAX_GRANT_STATUS_AGE_SECONDS", "").strip()
    if raw:
        try:
            return max(0, int(raw))
        except ValueError:
            return DEFAULT_MAX_STATUS_AGE_SECONDS
    return DEFAULT_MAX_STATUS_AGE_SECONDS


def _grant_schema_gate_errors(
    scope_grant: dict[str, Any],
    *,
    strict: bool,
) -> list[str]:
    """Full scope-grant-v2 validation + version / structural gate (WS4)."""
    errors: list[str] = []
    schema_version = (
        scope_grant.get("grant_version")
        or scope_grant.get("schema_version")
        or scope_grant.get("grant_schema_version")
        or (scope_grant.get("authorization") or {}).get("schema_version")
    )
    version_s = str(schema_version) if schema_version is not None else ""

    if strict:
        if not version_s:
            errors.append("grant_version missing")
        elif version_s in LEGACY_GRANT_VERSIONS:
            errors.append(
                f"legacy grant version {version_s!r} rejected in strict mode; "
                "use migrate-legacy-grant CLI"
            )
        elif version_s not in STRICT_GRANT_VERSIONS:
            errors.append(f"unknown grant schema version rejected: {version_s!r}")

        # Structural rejects required by institutional gate.
        if not scope_grant.get("grant_signature"):
            errors.append("grant_signature missing")
        algo = scope_grant.get("signature_algorithm") or (
            (scope_grant.get("issuer") or {}).get("signature_algorithm")
        )
        if not algo:
            errors.append("signature_algorithm missing")
        elif str(algo) not in SUPPORTED_SIGNATURE_ALGORITHMS:
            errors.append(f"unsupported signature_algorithm: {algo!r}")
        if extract_capability_envelope(scope_grant) is None:
            errors.append("authorization_envelope missing")
        source = scope_grant.get("source")
        if not isinstance(source, dict) or not source:
            errors.append("source bindings missing")
        provenance = scope_grant.get("provenance")
        if not isinstance(provenance, dict) or not provenance:
            errors.append("provenance missing or malformed")
        elif not provenance.get("scope_trust_root_hash"):
            errors.append("provenance.scope_trust_root_hash missing")

        # Full JSON Schema validate against shared grant v2.
        try:
            import copy

            import jsonschema

            schema = load_contract_schema(GRANT_V2_SCHEMA_NAME)
            # Envelope vocabulary is validated separately; rewrite nested $ref so
            # grant-level required fields can be checked without resolver fragility.
            schema = copy.deepcopy(schema)
            try:
                auth_props = (
                    schema.get("properties", {})
                    .get("authorization", {})
                    .get("properties", {})
                )
                if isinstance(auth_props, dict) and "authorization_envelope" in auth_props:
                    auth_props["authorization_envelope"] = {"type": "object"}
            except Exception:  # noqa: BLE001
                pass
            jsonschema.validate(instance=scope_grant, schema=schema)
        except ImportError:
            errors.append("jsonschema required for institutional grant schema gate")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"scope-grant-v2 schema validation failed: {exc}")
    else:
        # Soft path: warn-equivalent errors returned as empty; callers use warnings.
        if version_s and version_s not in STRICT_GRANT_VERSIONS | LEGACY_GRANT_VERSIONS:
            errors.append(f"unrecognized grant schema_version: {version_s!r}")
    return errors


def _is_signed_artifact_ref(artifact: dict[str, Any]) -> bool:
    return all(field_name in artifact for field_name in SIGNED_ARTIFACT_REF_FIELDS)


def _signed_artifact_ref_errors(artifact: dict[str, Any]) -> list[str]:
    """Validate remote signed artifact reference shape (P0-6)."""
    errors: list[str] = []
    missing = [f for f in SIGNED_ARTIFACT_REF_FIELDS if not artifact.get(f)]
    if missing:
        errors.append(
            "signed artifact reference missing fields: " + ", ".join(missing)
        )
        return errors
    art_hash = artifact.get("artifact_hash")
    if not str(art_hash).startswith("sha256:"):
        errors.append(
            f"signed artifact reference artifact_hash invalid: {art_hash!r}"
        )
    attestation = artifact.get("attestation")
    if not isinstance(attestation, (str, dict)) or not attestation:
        errors.append("signed artifact reference attestation missing/invalid")
    return errors


def _artifact_id_and_hash(
    artifact: Any,
    *,
    preferred_id_fields: tuple[str, ...] | None = None,
) -> tuple[str | None, str | None, list[str]]:
    """Extract authenticated id+hash from a local artifact or signed remote ref.

    Never synthesizes a local hash when the hash is missing — missing hash is
    insufficient authentication (P0-6).
    """
    errors: list[str] = []
    if artifact is None:
        return None, None, errors
    if not isinstance(artifact, dict):
        return None, None, ["source artifact must be an object"]

    if _is_signed_artifact_ref(artifact) or (
        artifact.get("store_id") is not None or artifact.get("attestation") is not None
    ):
        # Remote / store-backed refs require the full signed reference contract.
        ref_errors = _signed_artifact_ref_errors(artifact)
        errors.extend(ref_errors)
        if ref_errors:
            return None, None, errors
        return (
            str(artifact["artifact_id"]),
            str(artifact["artifact_hash"]),
            errors,
        )

    id_fields = preferred_id_fields or (
        "record_id",
        "decision_id",
        "review_trigger_id",
        "trigger_id",
        "packet_id",
        "scope_decision_id",
        "session_resolution_id",
        "session_id",
        "id",
    )
    art_id = None
    for field_name in id_fields:
        if artifact.get(field_name) is not None:
            art_id = artifact.get(field_name)
            break
    art_hash = (
        artifact.get("record_hash")
        or artifact.get("decision_hash")
        or artifact.get("packet_hash")
        or artifact.get("review_trigger_hash")
        or artifact.get("scope_decision_hash")
        or artifact.get("session_resolution_hash")
        or artifact.get("resolution_hash")
        or artifact.get("hash")
        or artifact.get("artifact_hash")
        or artifact.get("_authenticated_hash")
    )
    # If a body is supplied with an explicit hash, recompute and compare when
    # enough non-hash fields exist (local authenticated artifact).
    if art_hash is not None and art_id is not None:
        body = {
            k: v
            for k, v in artifact.items()
            if not str(k).endswith("_hash")
            and k
            not in {
                "_authenticated_hash",
                "hash",
                "artifact_hash",
                "attestation",
                "store_id",
                "tenant_id",
            }
        }
        # Only recompute when the body looks like a concrete artifact payload.
        if len(body) > 1:
            recomputed = hash_object(body)
            if str(recomputed) != str(art_hash):
                errors.append(
                    f"source artifact hash mismatch vs recomputed body "
                    f"({art_hash} != {recomputed})"
                )
    elif art_id is not None and art_hash is None:
        errors.append(
            "source artifact hash missing; refusing silent local hash synthesis"
        )
    return (str(art_id) if art_id is not None else None), (
        str(art_hash) if art_hash is not None else None
    ), errors


def migrate_legacy_grant_to_v2(
    legacy_grant: dict[str, Any],
    *,
    grant_version: str = "2.0.0",
) -> dict[str, Any]:
    """Explicit migration helper for legacy scalar grants (CLI / offline only)."""
    from akta.capability_envelope import resolve_grant_envelope

    migrated = dict(legacy_grant)
    migrated["grant_version"] = grant_version
    envelope = resolve_grant_envelope(
        migrated, require_envelope=False, allow_legacy_adapter=True
    )
    auth = dict(migrated.get("authorization") or {})
    auth["authorization_envelope"] = envelope
    auth.setdefault("allowed_tools", list(envelope.get("allowed_tools") or []))
    auth.setdefault("blocked_tools", list(envelope.get("blocked_tools") or []))
    migrated["authorization"] = auth
    migrated["authorization_schema_version"] = ENVELOPE_VERSION
    migrated["authorization_schema_hash"] = authorization_envelope_schema_hash()
    if "created_at" not in migrated:
        migrated["created_at"] = datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    if "constraints" not in migrated:
        migrated["constraints"] = {}
    if "expiration" not in migrated:
        migrated["expiration"] = {
            "absolute_expiration": None,
            "expires_after": [],
        }
    if "provenance" not in migrated:
        migrated["provenance"] = {}
    if "source" not in migrated:
        migrated["source"] = {
            "packet_id": "migrated-unknown",
            "decision_id": "migrated-unknown",
            "akta_record_id": "migrated-unknown",
        }
    if "issuer" not in migrated:
        migrated["issuer"] = {
            "issuer_identity": "migration-unspecified",
            "issuer_key_id": "migration-unspecified",
        }
    if "grant_id" not in migrated:
        migrated["grant_id"] = migrated.get("scope_grant_id") or "migrated-grant"
    return migrated


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
    """Verify issuer signature; fail closed when crypto trust store is required.

    Strict / crypto-required modes enforce the full checklist: nonempty issuer
    registry, approved key, grant-issuance artifact permission, active status,
    validity window, supported algorithm, valid signature, matching signed
    payload hash, and valid final grant hash. Structural signature presence
    alone never passes when ``require_crypto`` is set.
    """
    sig = scope_grant.get("grant_signature")
    if not sig:
        return "unsigned grant: grant_signature missing"
    issuer = scope_grant.get("issuer") or {}
    key_id = issuer.get("issuer_key_id")
    if not key_id:
        return "issuer.issuer_key_id missing"

    algo = scope_grant.get("signature_algorithm") or issuer.get("signature_algorithm")
    if require_crypto and algo and str(algo) not in SUPPORTED_SIGNATURE_ALGORITHMS:
        return f"unsupported signature_algorithm: {algo!r}"
    if require_crypto and not algo:
        # Default expected algorithm when crypto is mandatory.
        algo = "Ed25519"

    if "grant_hash" not in scope_grant:
        return "grant_hash missing"
    if not _contracts().verify_hash(scope_grant, "grant_hash"):
        return "grant_hash mismatch (invalid or tampered grant payload)"

    signed_payload = scope_grant.get("signed_payload_hash")
    if signed_payload is None:
        if require_crypto:
            return "signed_payload_hash missing"
    elif signed_payload != scope_grant.get("grant_hash"):
        return "signed_payload_hash must equal grant_hash"

    if trust_store is None:
        if require_crypto:
            return "trust store required for issuer signature verification"
        # Structural presence only when crypto is not required (unit/dev).
        return None

    revoked = set(trust_store.get("revoked_key_ids") or [])
    if key_id in revoked:
        return f"revoked issuer key: {key_id}"
    keys = trust_store.get("keys") or {}
    if require_crypto and (not keys or institutional_registry_is_empty(trust_store)):
        return "trust store has no approved issuer keys"
    entry = keys.get(key_id)
    if entry is None:
        return f"unknown issuer key: {key_id}"

    status = str(entry.get("status") or "active").lower()
    if status != "active":
        return f"issuer key not active (status={status}): {key_id}"

    entry_algo = entry.get("algorithm")
    if entry_algo and str(entry_algo) not in SUPPORTED_SIGNATURE_ALGORITHMS:
        return f"issuer key uses unsupported algorithm: {entry_algo!r}"
    if require_crypto and algo and entry_algo and str(algo).lower() != str(entry_algo).lower():
        return "grant signature_algorithm does not match issuer registry algorithm"

    allowed_types = entry.get("_authorized_artifact_types") or set(
        entry.get("authorized_artifact_types") or []
    )
    required_type = (
        trust_store.get("required_artifact_type") or ArtifactType.SCOPE_GRANT.value
    )
    if require_crypto and allowed_types and required_type not in allowed_types:
        return (
            f"issuer key {key_id} not authorized for artifact type {required_type!r}"
        )

    # Validity window (fail closed in crypto modes; also enforced in verify callback).
    from akta.trust_store import entry_within_validity

    if require_crypto and not entry_within_validity(entry):
        return f"issuer key outside validity window: {key_id}"

    if require_crypto and entry.get("_public_key") is None:
        return f"issuer key missing loadable public material: {key_id}"

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
    scope_client: ScopeAuthorizationClient | LedgerStatusVerifier | None = None,
) -> dict[str, Any] | None:
    """Fetch signed grant-status attestation via ScopeAuthorizationClient."""
    client: ScopeAuthorizationClient | LedgerStatusVerifier | None = scope_client
    if client is None:
        from akta.scope_client import ScopeClientConfig

        cfg = ScopeClientConfig.from_env()
        if endpoint:
            cfg.status_url = endpoint
        if not cfg.status_url:
            return None
        client = ScopeAuthorizationClient(cfg)
    try:
        if isinstance(client, ScopeAuthorizationClient) and endpoint:
            from akta.scope_client import ScopeClientConfig

            cfg = ScopeClientConfig(
                manifest_url=client.config.manifest_url,
                status_url=endpoint,
                oidc_token=client.config.oidc_token,
                oidc_token_provider=client.config.oidc_token_provider,
                mtls_cert_file=client.config.mtls_cert_file,
                mtls_key_file=client.config.mtls_key_file,
                ca_bundle=client.config.ca_bundle,
                verify_tls=client.config.verify_tls,
                audience=client.config.audience,
                tenant_id=client.config.tenant_id,
                timeout_seconds=client.config.timeout_seconds,
                max_response_bytes=client.config.max_response_bytes,
                max_retries=client.config.max_retries,
                require_transport_auth=client.config.require_transport_auth,
                extra_headers=dict(client.config.extra_headers),
            )
            client = ScopeAuthorizationClient(cfg)
        payload = client.get_status(str(grant_id))
    except (ScopeClientError, OSError, ValueError, TypeError):
        return None
    return dict(payload) if isinstance(payload, dict) else None


def _status_attestor_key_id(ledger_status: dict[str, Any]) -> str | None:
    return (
        (ledger_status.get("issuer") or {}).get("issuer_key_id")
        or ledger_status.get("attestation_key_id")
        or ledger_status.get("issuer_key_id")
        or ledger_status.get("status_attestor_key_id")
    )


def _ledger_status_errors(
    scope_grant: dict[str, Any],
    *,
    ledger_status: dict[str, Any] | None,
    strict: bool,
    trust_store: dict[str, Any] | None = None,
    require_crypto: bool = False,
    expected_tenant_id: str | None = None,
    replay_store: StatusReplayStore | None = None,
    status_authenticated: bool = False,
) -> list[str]:
    """Validate authoritative grant lifecycle status (P0-9 / P0-10).

    Strict modes require a signed status attestation or an authenticated ledger
    verifier payload. Embedded unsigned ``ledger_status`` dictionaries are
    rejected. Replay state is consulted via ``replay_store`` only — never via
    mutating the grant dict.
    """
    errors: list[str] = []
    if ledger_status is None:
        if strict:
            errors.append("grant_status_unavailable")
        elif os.environ.get("SCOPE_GRANT_STATUS_URL"):
            errors.append("grant_status_unavailable")
        return errors

    has_sig = ledger_status.get("attestation_signature") is not None or (
        ledger_status.get("signature") is not None
        and (
            ledger_status.get("attestation_hash") is not None
            or ledger_status.get("status_hash") is not None
        )
    )

    if strict and not has_sig and not status_authenticated:
        errors.append(
            "strict modes require a signed status attestation or authenticated "
            "ledger verifier; unsigned embedded ledger_status rejected"
        )
        return errors

    # Prefer status-authoritative lifecycle semantics.
    errors.extend(
        status_lifecycle_errors(
            ledger_status,
            prefer_status_over_context=True,
            context_metadata={},
        )
    )

    status = str(ledger_status.get("status") or "").strip().lower()
    if status in REJECTED_GRANT_STATUSES:
        errors.append(f"grant status rejected: status={status}")
    elif strict and status not in ACTIVE_GRANT_STATUSES:
        errors.append(
            f"grant status must be active in strict modes (got {status!r})"
        )

    remaining = ledger_status.get("cardinality_remaining")
    if remaining is None:
        remaining = ledger_status.get("single_use_remaining")
    if remaining is None:
        remaining = ledger_status.get("remaining_uses")
    if strict and remaining is None:
        errors.append("grant status missing remaining cardinality")
    elif remaining is not None:
        try:
            if int(remaining) <= 0:
                errors.append("no remaining uses per signed status")
        except (TypeError, ValueError):
            errors.append(f"grant status remaining cardinality invalid: {remaining!r}")

    constraints = scope_grant.get("constraints") or {}
    if constraints.get("single_use") and remaining is not None:
        try:
            if int(remaining) <= 0:
                errors.append("single-use grant already consumed")
        except (TypeError, ValueError):
            pass

    # Max age / freshness
    checked_at = ledger_status.get("checked_at")
    if checked_at:
        try:
            checked_dt = _parse_iso(str(checked_at))
            age = (datetime.now(timezone.utc) - checked_dt).total_seconds()
            max_age = _max_status_age_seconds()
            if age > max_age:
                errors.append(
                    f"grant status attestation stale "
                    f"(age={int(age)}s > max={max_age}s)"
                )
        except (ValueError, TypeError):
            errors.append(f"grant status checked_at invalid: {checked_at!r}")
    elif strict:
        errors.append("grant status checked_at missing")

    # Tenant binding
    status_tenant = ledger_status.get("tenant_id") or (
        (ledger_status.get("environment") or {}).get("tenant_id")
    )
    grant_tenant = (
        expected_tenant_id
        or (scope_grant.get("constraints") or {}).get("tenant_id")
        or ((scope_grant.get("authorization") or {}).get("authorization_envelope") or {})
        .get("environment", {})
        .get("tenant_id")
    )
    if grant_tenant and status_tenant and str(grant_tenant) != str(status_tenant):
        errors.append(
            f"grant status tenant mismatch ({status_tenant!r} != {grant_tenant!r})"
        )

    # Durable replay protection (P0-9) — never write onto grant dict.
    seq = ledger_status.get("ledger_sequence")
    if seq is None:
        seq = ledger_status.get("sequence")
    attestor = _status_attestor_key_id(ledger_status)
    status_hash = status_hash_for_replay(ledger_status)
    if replay_store is not None and seq is not None and attestor and status_hash and checked_at:
        tenant_for_store = str(status_tenant or grant_tenant or "default")
        grant_id = str(
            scope_grant.get("grant_id") or scope_grant.get("scope_grant_id") or ""
        )
        try:
            seq_i = int(seq)
        except (TypeError, ValueError):
            errors.append(f"grant status ledger_sequence invalid: {seq!r}")
        else:
            prior = replay_store.list_attestors_for_grant(tenant_for_store, grant_id)
            decision = replay_store.evaluate(
                tenant_id=tenant_for_store,
                grant_id=grant_id,
                status_attestor_key_id=str(attestor),
                ledger_sequence=seq_i,
                status_hash=str(status_hash),
                checked_at=str(checked_at),
                previously_seen_attestors=prior,
            )
            if not decision.accepted:
                errors.extend(decision.errors)
    elif seq is not None and replay_store is None:
        # Soft structural validation only when no durable store configured.
        try:
            int(seq)
        except (TypeError, ValueError):
            errors.append(f"grant status ledger_sequence invalid: {seq!r}")

    # Attestation verification for remote / provided / strict status payloads
    remote = bool(os.environ.get("SCOPE_GRANT_STATUS_URL"))
    if strict or remote or has_sig or status_authenticated:
        expected_hash = scope_grant.get("grant_hash")
        if expected_hash and ledger_status.get("grant_hash") not in (None, expected_hash):
            errors.append("grant status grant_hash does not match grant")
        elif strict and expected_hash and "grant_hash" not in ledger_status:
            errors.append("grant status missing grant_hash binding")
        trust = (scope_grant.get("provenance") or {}).get("scope_trust_root_hash")
        if trust and ledger_status.get("scope_trust_root_hash") not in (None, trust):
            errors.append("grant status trust-root mismatch")
        elif strict and trust and "scope_trust_root_hash" not in ledger_status:
            errors.append("grant status missing scope_trust_root_hash binding")

        if strict and not attestor:
            errors.append("grant status attestation signer missing")

        try:
            import jsonschema

            schema = load_contract_schema(GRANT_STATUS_SCHEMA_NAME)
            jsonschema.validate(instance=ledger_status, schema=schema)
        except ImportError:
            pass
        except Exception as exc:  # noqa: BLE001
            errors.append(f"grant status attestation schema invalid: {exc}")

        if has_sig:
            sig_err = _attestation_signature_error(
                ledger_status,
                trust_store=trust_store,
                require_crypto=require_crypto or remote or strict,
            )
            if sig_err:
                errors.append(sig_err)
                if "unknown" in sig_err.lower():
                    errors.append("grant status unknown signer")
        elif strict and not status_authenticated:
            errors.append("grant status attestation_signature missing")
    return errors


def _source_binding_errors(
    scope_grant: dict[str, Any],
    *,
    record: dict[str, Any] | None,
    trigger: dict[str, Any] | None,
    expected_packet_id: str | None,
    source_artifacts: dict[str, Any] | None = None,
    strict: bool = False,
) -> list[str]:
    """Verify source ID bindings and (in strict) ID+hash chain (P0-6)."""
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
        packet_id = trigger.get("packet_id") or (trigger.get("source") or {}).get(
            "packet_id"
        )
        if packet_id and source.get("packet_id") not in (None, packet_id):
            errors.append("grant packet_id does not match review trigger/packet")

    artifacts = dict(source_artifacts or {})
    if record is not None and "record" not in artifacts:
        artifacts["record"] = record
    if trigger is not None and "review_trigger" not in artifacts:
        artifacts["review_trigger"] = trigger

    if strict:
        missing_bindings: list[str] = []
        for id_field, hash_field in STRICT_REQUIRED_SOURCE_BINDINGS:
            source_id = source.get(id_field)
            source_hash = source.get(hash_field)
            if id_field == "akta_record_id" and not source_hash:
                source_hash = source.get("record_hash")
            if not source_id:
                missing_bindings.append(id_field)
            if not source_hash:
                missing_bindings.append(hash_field)
        # Session Resolution required only when applicable.
        if source.get("session_resolution_id") or source.get("session_id"):
            if not (
                source.get("session_resolution_hash") or source.get("resolution_hash")
            ):
                missing_bindings.append("session_resolution_hash")
        if missing_bindings:
            # Deduplicate while preserving order.
            seen: set[str] = set()
            ordered = []
            for item in missing_bindings:
                if item not in seen:
                    seen.add(item)
                    ordered.append(item)
            errors.append("missing source hashes: " + ", ".join(ordered))
        if not artifacts:
            errors.append(
                "source artifacts or authenticated refs required to verify source hashes"
            )

    seen_pairs: set[tuple[str, str]] = set()
    for id_field, hash_field, artifact_key in SOURCE_HASH_BINDINGS:
        source_id = source.get(id_field)
        source_hash = source.get(hash_field)
        if source_id is None and source_hash is None:
            continue
        if source_hash is None:
            # Alias hash fields (e.g. record_hash) may be absent when the
            # canonical field (akta_record_hash) is present; required hashes
            # are enforced via STRICT_REQUIRED_SOURCE_BINDINGS.
            continue
        artifact = artifacts.get(artifact_key)
        if artifact is None:
            if strict:
                errors.append(
                    f"source artifact/ref missing for {artifact_key} "
                    f"(required to verify {hash_field})"
                )
            continue
        art_id, art_hash, art_errors = _artifact_id_and_hash(
            artifact,
            preferred_id_fields=(id_field, "artifact_id", "id"),
        )
        errors.extend(art_errors)
        if art_id is not None and source_id is not None and str(art_id) != str(source_id):
            errors.append(
                f"source {id_field} mismatch vs artifact "
                f"({source_id} != {art_id})"
            )
        if art_hash is None:
            errors.append(
                f"source {hash_field} could not be authenticated from artifact/ref"
            )
        elif str(art_hash) != str(source_hash):
            errors.append(
                f"source {hash_field} mismatch vs artifact "
                f"({source_hash} != {art_hash})"
            )
        pair = (str(source_id), str(source_hash))
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)

    # Same tool/envelope across different records must fail hash binding.
    if record is not None and source.get("akta_record_id"):
        rec_hash = source.get("akta_record_hash") or source.get("record_hash")
        actual_hash = record.get("record_hash")
        if rec_hash and actual_hash and str(rec_hash) != str(actual_hash):
            errors.append(
                "source record hash binding failed for different AKTA record "
                "(same tool/envelope cannot cross records)"
            )
    return errors


def _bound_context_errors(
    scope_grant: dict[str, Any],
    *,
    context: dict[str, Any] | None,
    strict: bool,
    ledger_status: dict[str, Any] | None = None,
) -> list[str]:
    """P0-E / WS10: typed expires_after comparators vs AKTA scientific state."""
    if not strict:
        return []
    result = check_expires_after_bindings(
        scope_grant,
        context=context,
        ledger_status=ledger_status,
    )
    # Status-authoritative errors are reported via _ledger_status_errors; avoid dupes.
    status_msgs = set(status_lifecycle_errors(ledger_status))
    return [e for e in result.errors if e not in status_msgs]


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
    authorization_manifest: dict[str, Any] | None = None,
    source_artifacts: dict[str, Any] | None = None,
    status_trust_store: dict[str, Any] | None = None,
    manifest_trust_store: dict[str, Any] | None = None,
    scope_client: ScopeAuthorizationClient | None = None,
    ledger_verifier: LedgerStatusVerifier | None = None,
    replay_store: StatusReplayStore | None = None,
    raise_on_error: bool = False,
) -> GrantVerificationResult:
    """Authenticate a SCOPE grant before apply (AKTA 1.2 P0-6 … P0-10)."""
    resolved_mode = resolve_grant_verification_mode(mode)
    strict = resolved_mode in STRICT_MODES
    require_crypto = (resolved_mode in STRICT_MODES) or _env_require_grant_crypto()
    require_envelope = (
        require_capability_envelope
        if require_capability_envelope is not None
        else (strict or require_capability_envelope_env())
    )

    errors: list[str] = []
    warnings: list[str] = []
    checks_run: list[str] = []
    verified_manifest_hash: str | None = None
    status_authenticated = False

    def _fail(msg: str, *, as_warning: bool = False) -> None:
        if as_warning:
            warnings.append(msg)
        else:
            errors.append(msg)

    # --- WS4: institutional grant schema gate (first) ---
    checks_run.append("schema_version_supported")
    schema_errors = _grant_schema_gate_errors(scope_grant, strict=strict)
    for err in schema_errors:
        if strict:
            _fail(err)
        else:
            # Soft warnings in unit/dev for unrecognized versions only.
            if "unrecognized" in err or "legacy" in err:
                warnings.append(err)
            else:
                warnings.append(err)

    if require_crypto:
        crypto_err = _require_cryptography_for_strict()
        if crypto_err:
            _fail(crypto_err)

    resolved_trust = trust_store
    if resolved_trust is None and (
        require_crypto
        or os.environ.get("AKTA_TRUST_STORE_PATH")
        or os.environ.get("AKTA_ISSUER_KEY_REGISTRY")
        or os.environ.get("AKTA_GRANT_ISSUER_REGISTRY")
    ):
        resolved_trust = resolve_grant_issuer_trust_store(require_keys=require_crypto)
    if require_crypto and (
        resolved_trust is None
        or not (resolved_trust.get("keys") or {})
        or institutional_registry_is_empty(resolved_trust)
    ):
        _fail(
            "production/institutional trust store required "
            "(empty or missing issuer registry)"
        )

    # Status attestation uses a separate trust domain when populated.
    status_trust = status_trust_store
    if status_trust is None:
        status_trust = resolve_status_attestation_trust_store(require_keys=False)
    if status_trust is None or institutional_registry_is_empty(status_trust):
        status_trust = resolved_trust

    manifest_trust = manifest_trust_store
    if manifest_trust is None:
        manifest_trust = resolve_manifest_signer_trust_store(require_keys=False)

    resolved_client = scope_client
    if resolved_client is None:
        resolved_client = ScopeAuthorizationClient.from_env()

    resolved_replay = replay_store
    if resolved_replay is None:
        authorized = None
        if status_trust and (status_trust.get("keys") or {}):
            authorized = set((status_trust.get("keys") or {}).keys())
        resolved_replay = StatusReplayStore.from_env(authorized_attestors=authorized)

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
                or (scope_grant.get("authorization") or {}).get(
                    "authorization_schema_hash"
                )
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

    # 11–12. source bindings (+ hashes in strict)
    checks_run.append("source_packet_binding")
    checks_run.append("source_akta_record_binding")
    for err in _source_binding_errors(
        scope_grant,
        record=record,
        trigger=trigger,
        expected_packet_id=expected_packet_id,
        source_artifacts=source_artifacts,
        strict=strict,
    ):
        _fail(err, as_warning=not strict)

    # 13. trust root + WS5 signed authorization manifest
    checks_run.append("trust_root_present")
    provenance = scope_grant.get("provenance") or {}
    trust_root = provenance.get("scope_trust_root_hash")
    if not trust_root:
        _fail("provenance.scope_trust_root_hash missing", as_warning=not strict)
    checks_run.append("policy_manifest_fresh")
    if trust_root and (strict or authorization_manifest is not None):
        embedded = authorization_manifest or provenance.get(
            "authorization_manifest"
        )
        if isinstance(embedded, dict) or strict:
            manifest_result = resolve_and_verify_authorization_manifest(
                expected_trust_root_hash=str(trust_root),
                embedded_manifest=embedded if isinstance(embedded, dict) else None,
                trust_store=manifest_trust,
                require_crypto=require_crypto or strict,
                scope_client=resolved_client,
            )
            if not manifest_result.ok:
                for err in manifest_result.errors:
                    _fail(err, as_warning=not strict)
            else:
                verified_manifest_hash = manifest_result.manifest_hash
                if verified_manifest_hash != trust_root:
                    _fail(
                        "grant scope_trust_root_hash does not match verified "
                        "authorization manifest hash"
                    )
    # AKTA effective-policy freshness vs grant binding (independent of SCOPE manifest).
    if context is not None:
        current_manifest = (context.get("metadata") or {}).get("policy_manifest_hash")
        grant_manifest = (
            provenance.get("akta_policy_hash")
            or provenance.get("policy_manifest_hash")
            or (scope_grant.get("constraints") or {}).get("policy_manifest_hash")
        )
        if current_manifest and grant_manifest and current_manifest != grant_manifest:
            _fail("stale policy manifest relative to grant binding")

    # 15–16. ledger / single-use (P0-9 / P0-10)
    checks_run.append("ledger_status_active")
    checks_run.append("single_use_remaining")
    status_payload = ledger_status
    if status_payload is None and grant_id and ledger_verifier is not None:
        try:
            status_payload = dict(ledger_verifier.get_status(str(grant_id)))
            status_authenticated = True
        except Exception as exc:  # noqa: BLE001
            _fail(f"authenticated ledger verifier failed: {exc}")
    if status_payload is None and grant_id:
        status_payload = _fetch_grant_status_attestation(
            str(grant_id),
            scope_client=resolved_client or ledger_verifier,
        )
        if status_payload is not None and resolved_client is not None:
            status_authenticated = True
    # Embedded ledger only when independently signed (strict) or non-strict soft path.
    if status_payload is None:
        embedded_ledger = (
            scope_grant.get("ledger_status")
            or provenance.get("ledger_status")
            or (scope_grant.get("constraints") or {}).get("ledger_status")
        )
        if isinstance(embedded_ledger, dict):
            status_payload = embedded_ledger
    for err in _ledger_status_errors(
        scope_grant,
        ledger_status=status_payload,
        strict=strict,
        trust_store=status_trust,
        require_crypto=require_crypto,
        expected_tenant_id=(
            (context or {}).get("tenant_id")
            if isinstance(context, dict)
            else None
        ),
        replay_store=resolved_replay,
        status_authenticated=status_authenticated,
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
                if auth_blocked - env_blocked:
                    _fail("blocked_tools fabrication vs envelope")

    # 20. bound context (P0-E / WS10)
    checks_run.append("bound_context_present")
    for err in _bound_context_errors(
        scope_grant,
        context=context,
        strict=strict,
        ledger_status=status_payload,
    ):
        _fail(err)

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
        authorization_manifest_hash=verified_manifest_hash,
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
    authorization_manifest: dict[str, Any] | None = None,
    source_artifacts: dict[str, Any] | None = None,
    status_trust_store: dict[str, Any] | None = None,
    manifest_trust_store: dict[str, Any] | None = None,
    scope_client: ScopeAuthorizationClient | None = None,
    ledger_verifier: LedgerStatusVerifier | None = None,
    replay_store: StatusReplayStore | None = None,
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
        authorization_manifest=authorization_manifest,
        source_artifacts=source_artifacts,
        status_trust_store=status_trust_store,
        manifest_trust_store=manifest_trust_store,
        scope_client=scope_client,
        ledger_verifier=ledger_verifier,
        replay_store=replay_store,
        raise_on_error=True,
    )
