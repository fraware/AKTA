"""Immutable signed preregistration lock and amendment verification (P1-16).

The locked artifact at ``evals/empirical/preregistration.json`` is never rewritten
by harness or CI. Verification recomputes the content hash, checks the institutional
Ed25519 signature, and rejects unauthorized field mutation. Amendments must carry
parent hash, reason, changed fields, approval, signature, and a timestamp that
precedes observation start.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PREREG = ROOT / "evals" / "empirical" / "preregistration.json"
DEFAULT_AMENDMENT_SCHEMA = ROOT / "evals" / "empirical" / "amendment.schema.json"

# Envelope fields excluded from the content hash (attached after hashing).
HASH_EXCLUDED_FIELDS = frozenset(
    {
        "content_hash",
        "preregistration_hash",
        "signature",
    }
)

REQUIRED_LOCK_FIELDS = frozenset(
    {
        "preregistration_id",
        "preregistered_at",
        "content_hash",
        "preregistration_hash",
        "signature",
        "amendment_policy",
        "immutable_signed_artifact",
    }
)

REQUIRED_SIGNATURE_FIELDS = frozenset(
    {
        "algorithm",
        "key_id",
        "public_key",
        "public_verification_key",
        "value",
        "signed_over",
        "status",
    }
)

REQUIRED_AMENDMENT_FIELDS = frozenset(
    {
        "amendment_id",
        "parent_content_hash",
        "reason",
        "changed_fields",
        "approval",
        "signature",
        "amended_at",
    }
)

REQUIRED_APPROVAL_FIELDS = frozenset(
    {
        "approver_id",
        "approver_role",
        "approved_at",
        "decision",
    }
)


class PreregistrationLockError(ValueError):
    """Raised when a locked preregistration or amendment fails verification."""


@dataclass(frozen=True)
class VerificationResult:
    ok: bool
    path: str
    preregistration_id: str | None
    content_hash: str | None
    errors: tuple[str, ...]

    def raise_for_errors(self) -> None:
        if not self.ok:
            raise PreregistrationLockError("; ".join(self.errors))


def canonical_payload_bytes(body: dict[str, Any]) -> bytes:
    """Canonical JSON bytes for hashing (excludes signature envelope fields)."""
    payload = {k: v for k, v in body.items() if k not in HASH_EXCLUDED_FIELDS}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "utf-8"
    )


def compute_content_hash(body: dict[str, Any]) -> str:
    digest = hashlib.sha256(canonical_payload_bytes(body)).hexdigest()
    return f"sha256:{digest}"


def _parse_utc(ts: str) -> datetime:
    raw = ts.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _load_ed25519_public_key(public_key_b64: str):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    try:
        raw = base64.b64decode(public_key_b64, validate=True)
    except Exception as exc:  # noqa: BLE001 — surface as lock error
        raise PreregistrationLockError(f"invalid public key encoding: {exc}") from exc
    if len(raw) != 32:
        raise PreregistrationLockError("Ed25519 public key must be 32 raw bytes (base64)")
    return Ed25519PublicKey.from_public_bytes(raw)


def _verify_ed25519_over_digest(*, public_key_b64: str, digest_field: str, signature_b64: str) -> None:
    from cryptography.exceptions import InvalidSignature

    digest_hex = digest_field.removeprefix("sha256:")
    try:
        digest_bytes = bytes.fromhex(digest_hex)
    except ValueError as exc:
        raise PreregistrationLockError(f"invalid content hash hex: {exc}") from exc
    try:
        signature = base64.b64decode(signature_b64, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise PreregistrationLockError(f"invalid signature encoding: {exc}") from exc

    public_key = _load_ed25519_public_key(public_key_b64)
    try:
        public_key.verify(signature, digest_bytes)
    except InvalidSignature as exc:
        raise PreregistrationLockError("institutional Ed25519 signature verification failed") from exc


def sign_content_hash_ed25519(*, private_key_pem: bytes, content_hash: str) -> str:
    """Sign sha256 digest bytes; returns base64 signature (SCOPE-compatible)."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = serialization.load_pem_private_key(private_key_pem, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise PreregistrationLockError("private key must be Ed25519")
    digest = bytes.fromhex(content_hash.removeprefix("sha256:"))
    return base64.b64encode(key.sign(digest)).decode("ascii")


def public_key_b64_from_pem(public_key_pem: bytes | str) -> str:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    if isinstance(public_key_pem, str):
        public_key_pem = public_key_pem.encode("ascii")
    key = serialization.load_pem_public_key(public_key_pem)
    if not isinstance(key, Ed25519PublicKey):
        raise PreregistrationLockError("public key must be Ed25519")
    return base64.b64encode(key.public_bytes_raw()).decode("ascii")


def attach_institutional_signature(
    body: dict[str, Any],
    *,
    private_key_pem: bytes,
    key_id: str,
    public_key_b64: str | None = None,
    public_verification_key_pem: str | None = None,
) -> dict[str, Any]:
    """Attach content hash + institutional Ed25519 signature. Does not write disk."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    out = {k: v for k, v in body.items() if k not in HASH_EXCLUDED_FIELDS}
    content_hash = compute_content_hash(out)
    key = serialization.load_pem_private_key(private_key_pem, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise PreregistrationLockError("private key must be Ed25519")
    if public_key_b64 is None:
        public_key_b64 = base64.b64encode(key.public_key().public_bytes_raw()).decode("ascii")
    if public_verification_key_pem is None:
        public_verification_key_pem = key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("ascii")

    signature_value = sign_content_hash_ed25519(
        private_key_pem=private_key_pem, content_hash=content_hash
    )
    out["content_hash"] = content_hash
    out["preregistration_hash"] = content_hash
    out["signature"] = {
        "algorithm": "Ed25519",
        "key_id": key_id,
        "public_key": public_key_b64,
        "public_verification_key": public_verification_key_pem,
        "value": signature_value,
        "signed_over": "content_hash",
        "status": "institutional_signed",
    }
    return out


def default_amendment_policy() -> dict[str, Any]:
    return {
        "immutable_after_lock": True,
        "artifact_may_be_rewritten": False,
        "observations_started": False,
        "amendments_allowed_only_before_observations": True,
        "required_amendment_fields": sorted(REQUIRED_AMENDMENT_FIELDS),
        "required_approval_fields": sorted(REQUIRED_APPROVAL_FIELDS),
        "schema_path": "evals/empirical/amendment.schema.json",
        "process": (
            "Emit a signed amendment referencing parent_content_hash; "
            "do not mutate the locked preregistration.json bytes in place."
        ),
    }


def verify_preregistration_artifact(
    path: str | Path | None = None,
    *,
    expected: dict[str, Any] | None = None,
) -> VerificationResult:
    """Verify locked artifact hash, signature, and required lock fields.

    When ``expected`` is provided, every non-envelope field must match exactly
    (detects unauthorized field changes without rewriting the artifact).
    """
    target = Path(path) if path is not None else DEFAULT_PREREG
    errors: list[str] = []
    preregistration_id: str | None = None
    content_hash: str | None = None

    if not target.is_file():
        return VerificationResult(
            ok=False,
            path=str(target),
            preregistration_id=None,
            content_hash=None,
            errors=(f"preregistration artifact missing: {target}",),
        )

    try:
        body = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return VerificationResult(
            ok=False,
            path=str(target),
            preregistration_id=None,
            content_hash=None,
            errors=(f"failed to load preregistration: {exc}",),
        )

    if not isinstance(body, dict):
        return VerificationResult(
            ok=False,
            path=str(target),
            preregistration_id=None,
            content_hash=None,
            errors=("preregistration root must be an object",),
        )

    preregistration_id = body.get("preregistration_id")
    if not body.get("immutable_signed_artifact"):
        errors.append("immutable_signed_artifact must be true")

    missing_lock = sorted(REQUIRED_LOCK_FIELDS - set(body))
    if missing_lock:
        errors.append(f"missing lock fields: {missing_lock}")

    if not isinstance(body.get("preregistered_at"), str) or not body.get("preregistered_at"):
        errors.append("preregistered_at (fixed timestamp) required")

    sig = body.get("signature")
    if not isinstance(sig, dict):
        errors.append("signature block required")
        sig = {}
    else:
        missing_sig = sorted(REQUIRED_SIGNATURE_FIELDS - set(sig))
        if missing_sig:
            errors.append(f"missing signature fields: {missing_sig}")
        if sig.get("algorithm") != "Ed25519":
            errors.append("signature.algorithm must be Ed25519")
        if sig.get("status") != "institutional_signed":
            errors.append("signature.status must be institutional_signed")
        if sig.get("signed_over") != "content_hash":
            errors.append("signature.signed_over must be content_hash")

    policy = body.get("amendment_policy")
    if not isinstance(policy, dict):
        errors.append("amendment_policy required")
    else:
        if policy.get("artifact_may_be_rewritten") is not False:
            errors.append("amendment_policy.artifact_may_be_rewritten must be false")
        if policy.get("immutable_after_lock") is not True:
            errors.append("amendment_policy.immutable_after_lock must be true")
        if policy.get("amendments_allowed_only_before_observations") is not True:
            errors.append(
                "amendment_policy.amendments_allowed_only_before_observations must be true"
            )

    recomputed = compute_content_hash(body)
    content_hash = body.get("content_hash")
    if content_hash != recomputed:
        errors.append(
            f"content_hash mismatch: stored={content_hash!r} recomputed={recomputed!r}"
        )
    if body.get("preregistration_hash") != recomputed:
        errors.append("preregistration_hash must equal content_hash")

    if not errors and sig.get("public_key") and sig.get("value") and content_hash:
        try:
            _verify_ed25519_over_digest(
                public_key_b64=str(sig["public_key"]),
                digest_field=str(content_hash),
                signature_b64=str(sig["value"]),
            )
        except PreregistrationLockError as exc:
            errors.append(str(exc))

        pub_pem = sig.get("public_verification_key")
        if isinstance(pub_pem, str) and pub_pem.strip():
            try:
                derived = public_key_b64_from_pem(pub_pem)
                if derived != sig.get("public_key"):
                    errors.append(
                        "public_verification_key does not match signature.public_key"
                    )
            except PreregistrationLockError as exc:
                errors.append(str(exc))

    if expected is not None:
        expected_payload = {
            k: v for k, v in expected.items() if k not in HASH_EXCLUDED_FIELDS
        }
        actual_payload = {k: v for k, v in body.items() if k not in HASH_EXCLUDED_FIELDS}
        if actual_payload != expected_payload:
            # Field-level diff for actionable CI failure.
            all_keys = sorted(set(expected_payload) | set(actual_payload))
            changed = [
                k
                for k in all_keys
                if expected_payload.get(k) != actual_payload.get(k)
            ]
            errors.append(f"unauthorized field change vs expected lock body: {changed}")

    return VerificationResult(
        ok=not errors,
        path=str(target),
        preregistration_id=preregistration_id if isinstance(preregistration_id, str) else None,
        content_hash=recomputed if not errors else (content_hash if isinstance(content_hash, str) else None),
        errors=tuple(errors),
    )


def load_locked_preregistration(path: str | Path | None = None) -> dict[str, Any]:
    """Load the immutable artifact after verification. Never rewrites."""
    target = Path(path) if path is not None else DEFAULT_PREREG
    result = verify_preregistration_artifact(target)
    result.raise_for_errors()
    return json.loads(target.read_text(encoding="utf-8"))


def assert_not_rewriting_locked_artifact(path: Path) -> None:
    """Refuse writes that would replace the repository locked preregistration."""
    locked = DEFAULT_PREREG.resolve()
    if path.resolve() == locked:
        raise PreregistrationLockError(
            "refusing to rewrite locked preregistration artifact "
            f"{locked}; amendments must be separate signed documents"
        )


def validate_amendment(
    amendment: dict[str, Any],
    *,
    parent: dict[str, Any],
    observations_started: bool | None = None,
) -> None:
    """Validate amendment schema: parent hash, reason, fields, approval, sig, timing."""
    if not isinstance(amendment, dict):
        raise PreregistrationLockError("amendment must be an object")

    missing = sorted(REQUIRED_AMENDMENT_FIELDS - set(amendment))
    if missing:
        raise PreregistrationLockError(f"amendment missing required fields: {missing}")

    parent_hash = parent.get("content_hash") or parent.get("preregistration_hash")
    if not parent_hash:
        raise PreregistrationLockError("parent preregistration lacks content_hash")
    if amendment.get("parent_content_hash") != parent_hash:
        raise PreregistrationLockError(
            "amendment.parent_content_hash must equal parent content_hash"
        )

    reason = amendment.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise PreregistrationLockError("amendment.reason must be a non-empty string")

    changed = amendment.get("changed_fields")
    if not isinstance(changed, list) or not changed or not all(isinstance(x, str) for x in changed):
        raise PreregistrationLockError(
            "amendment.changed_fields must be a non-empty list of field names"
        )

    approval = amendment.get("approval")
    if not isinstance(approval, dict):
        raise PreregistrationLockError("amendment.approval must be an object")
    missing_approval = sorted(REQUIRED_APPROVAL_FIELDS - set(approval))
    if missing_approval:
        raise PreregistrationLockError(
            f"amendment.approval missing fields: {missing_approval}"
        )
    if approval.get("decision") != "approved":
        raise PreregistrationLockError("amendment.approval.decision must be 'approved'")

    sig = amendment.get("signature")
    if not isinstance(sig, dict):
        raise PreregistrationLockError("amendment.signature must be an object")
    for field in ("algorithm", "key_id", "public_key", "value", "signed_over"):
        if not sig.get(field):
            raise PreregistrationLockError(f"amendment.signature.{field} required")
    if sig.get("algorithm") != "Ed25519":
        raise PreregistrationLockError("amendment.signature.algorithm must be Ed25519")

    amended_at = amendment.get("amended_at")
    if not isinstance(amended_at, str) or not amended_at.strip():
        raise PreregistrationLockError("amendment.amended_at (timestamp) required")
    try:
        amended_dt = _parse_utc(amended_at)
    except ValueError as exc:
        raise PreregistrationLockError(f"invalid amended_at: {exc}") from exc

    policy = parent.get("amendment_policy") or {}
    obs_started = (
        observations_started
        if observations_started is not None
        else bool(policy.get("observations_started", False))
    )
    if obs_started:
        raise PreregistrationLockError(
            "amendments are forbidden after observations have started"
        )

    # Timestamp must precede any declared observation start when present.
    obs_start = policy.get("observations_start_at")
    if isinstance(obs_start, str) and obs_start.strip():
        try:
            obs_dt = _parse_utc(obs_start)
        except ValueError as exc:
            raise PreregistrationLockError(
                f"invalid amendment_policy.observations_start_at: {exc}"
            ) from exc
        if amended_dt >= obs_dt:
            raise PreregistrationLockError(
                "amendment.amended_at must be strictly before observations_start_at"
            )

    # Verify amendment signature over its own content hash (excluding signature).
    amd_hash = amendment.get("amendment_hash") or compute_content_hash(
        {k: v for k, v in amendment.items() if k not in {"signature", "amendment_hash"}}
    )
    stored = amendment.get("amendment_hash")
    if stored and stored != amd_hash:
        # Recompute excluding signature only.
        recomputed = "sha256:" + hashlib.sha256(
            json.dumps(
                {k: v for k, v in amendment.items() if k not in {"signature", "amendment_hash"}},
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("utf-8")
        ).hexdigest()
        if stored != recomputed:
            raise PreregistrationLockError("amendment_hash mismatch")
        amd_hash = recomputed

    try:
        _verify_ed25519_over_digest(
            public_key_b64=str(sig["public_key"]),
            digest_field=str(amd_hash),
            signature_b64=str(sig["value"]),
        )
    except PreregistrationLockError:
        # Also accept signature over parent content hash for thin amendments.
        try:
            _verify_ed25519_over_digest(
                public_key_b64=str(sig["public_key"]),
                digest_field=str(parent_hash),
                signature_b64=str(sig["value"]),
            )
        except PreregistrationLockError as exc:
            raise PreregistrationLockError(
                "amendment signature verification failed"
            ) from exc


def build_signed_amendment(
    *,
    parent: dict[str, Any],
    amendment_id: str,
    reason: str,
    changed_fields: list[str],
    approval: dict[str, Any],
    private_key_pem: bytes,
    key_id: str,
    amended_at: str,
    changes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Construct a schema-valid signed amendment (does not mutate the locked file)."""
    parent_hash = parent.get("content_hash") or parent.get("preregistration_hash")
    if not parent_hash:
        raise PreregistrationLockError("parent lacks content_hash")

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = serialization.load_pem_private_key(private_key_pem, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise PreregistrationLockError("private key must be Ed25519")
    public_key_b64 = base64.b64encode(key.public_key().public_bytes_raw()).decode("ascii")

    body: dict[str, Any] = {
        "amendment_id": amendment_id,
        "parent_content_hash": parent_hash,
        "parent_preregistration_id": parent.get("preregistration_id"),
        "reason": reason,
        "changed_fields": list(changed_fields),
        "changes": changes or {},
        "approval": approval,
        "amended_at": amended_at,
    }
    amd_hash = "sha256:" + hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()
    body["amendment_hash"] = amd_hash
    body["signature"] = {
        "algorithm": "Ed25519",
        "key_id": key_id,
        "public_key": public_key_b64,
        "public_verification_key": key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("ascii"),
        "value": sign_content_hash_ed25519(
            private_key_pem=private_key_pem, content_hash=amd_hash
        ),
        "signed_over": "amendment_hash",
        "status": "institutional_signed",
    }
    validate_amendment(body, parent=parent, observations_started=False)
    return body


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Verify the locked AKTA empirical preregistration artifact"
    )
    parser.add_argument(
        "--path",
        default=str(DEFAULT_PREREG),
        help="Path to preregistration.json (default: locked repo artifact)",
    )
    args = parser.parse_args(argv)
    result = verify_preregistration_artifact(args.path)
    print(
        json.dumps(
            {
                "ok": result.ok,
                "path": result.path,
                "preregistration_id": result.preregistration_id,
                "content_hash": result.content_hash,
                "errors": list(result.errors),
            },
            indent=2,
        )
    )
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())