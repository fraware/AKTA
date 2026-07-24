"""Resolve and load the installed scientific-authorization-contracts package.

Runtime imports the installed distribution only. Install from the vendor tree
or the pinned wheel:

    pip install ./vendor/scientific-authorization-contracts
    # preferred once 2.2 publishes:
    # pip install scientific-authorization-contracts==<pinned> \\
    #   --require-hashes ...

Vendor/sibling ``sys.path`` injection is intentionally not used. The vendor
tree is retained only as a byte-identical offline archive of the pinned
``source_archive_sha256``.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from akta.errors import AKTAError

ENVELOPE_VERSION = "scientific-authorization-envelope-v2"
ENVELOPE_SCHEMA_NAME = "authorization_envelope.v2.schema.json"
GRANT_V2_SCHEMA_NAME = "scope_grant.v2.schema.json"
GRANT_STATUS_SCHEMA_NAME = "scope_grant_status.v1.schema.json"
CONTRACTS_PACKAGE_NAME = "scientific-authorization-contracts"
CONTRACTS_PACKAGE_VERSION = "2.2.0"
# Accept installed 2.2.0 as the pinned release; retain 2.1.0 only for
# migration diagnostics outside strict modes.
CONTRACTS_ACCEPTED_VERSIONS = frozenset({"2.1.0", "2.2.0"})

_AKTA_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PIN_PATH = _AKTA_ROOT / "policy" / "shared_contracts_pin.json"
DEFAULT_VENDOR_ROOT = _AKTA_ROOT / "vendor" / "scientific-authorization-contracts"

# Modes that reject version-only identity and incomplete wheel/manifest pins.
CONTRACT_PIN_STRICT_MODES = frozenset(
    {"release", "production", "institutional", "institutional_release"}
)

_PIN_HASH_FIELDS = (
    "wheel_sha256",
    "source_archive_sha256",
    "release_manifest_sha256",
)


class ContractPinError(AKTAError):
    """Installed contracts distribution failed pin verification."""

    def __init__(self, message: str, *, errors: list[str] | None = None) -> None:
        self.errors = list(errors or [])
        super().__init__(message)


def _is_placeholder_pin_value(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return True
    upper = text.upper()
    return (
        "PLACEHOLDER" in upper
        or "UNAVAILABLE" in upper
        or "FAIL-CLOSED" in upper
        or text == "0" * 64
    )


def load_shared_contracts_pin(path: str | Path | None = None) -> dict[str, Any]:
    pin_path = Path(path) if path else DEFAULT_PIN_PATH
    data = json.loads(pin_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ContractPinError(f"shared contracts pin is not an object: {pin_path}")
    return data


def vendor_source_archive_sha256(vendor_root: str | Path | None = None) -> str:
    """SHA-256 over the vendor archive tree (logical paths + file bytes).

    Used as the offline byte-identical archive digest asserted by CI against
    ``source_archive_sha256`` in the pin.
    """
    root = Path(vendor_root) if vendor_root else DEFAULT_VENDOR_ROOT
    if not root.is_dir():
        raise FileNotFoundError(f"vendor contracts archive missing: {root}")
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        rel = path.relative_to(root).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def executable_module_hashes(
    *,
    package_root: Path | None = None,
    vendor_root: Path | None = None,
) -> dict[str, str]:
    """Map ``scientific_authorization_contracts/*.py`` → sha256 digests.

    When both roots are provided, digests must agree (caller compares). The
    returned map is built from ``package_root`` if given, otherwise the
    installed package, otherwise the vendor tree.
    """
    root: Path | None = None
    if package_root is not None:
        root = package_root
    elif vendor_root is None:
        try:
            import scientific_authorization_contracts as contracts

            root = Path(contracts.__file__).resolve().parent
        except ImportError:
            root = None
    if root is None:
        vr = Path(vendor_root) if vendor_root is not None else DEFAULT_VENDOR_ROOT
        root = vr / "python" / "scientific_authorization_contracts"
    if not root.is_dir():
        return {}
    return {
        path.name: "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(p for p in root.glob("*.py") if p.is_file())
    }


def _installed_distribution_digest() -> str | None:
    """Best-effort digest of the installed distribution (not version alone).

    Preference order:
    1. ``direct_url.json`` archive_info hashes
    2. Aggregate of RECORD file digests
    3. Aggregate of installed package files
    """
    try:
        dist = importlib.metadata.distribution(CONTRACTS_PACKAGE_NAME)
    except importlib.metadata.PackageNotFoundError:
        return None

    # direct_url.json (PEP 610) — preferred when pip recorded a hash.
    try:
        direct = dist.read_text("direct_url.json")
    except (FileNotFoundError, OSError):
        direct = None
    if direct:
        try:
            payload = json.loads(direct)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            archive = payload.get("archive_info") or {}
            hashes = archive.get("hashes") if isinstance(archive, dict) else None
            if isinstance(hashes, dict):
                sha = hashes.get("sha256") or hashes.get("SHA256")
                if sha:
                    text = str(sha).strip()
                    return text if text.startswith("sha256:") else f"sha256:{text}"

    # RECORD digests
    try:
        record = dist.read_text("RECORD")
    except (FileNotFoundError, OSError):
        record = None
    if record:
        digest = hashlib.sha256()
        for line in sorted(record.splitlines()):
            digest.update(line.encode("utf-8"))
            digest.update(b"\0")
        return "sha256:" + digest.hexdigest()

    # Fallback: hash files listed by the distribution.
    files = list(dist.files or [])
    if not files:
        return None
    digest = hashlib.sha256()
    locate = dist.locate_file
    for entry in sorted(files, key=lambda e: str(e)):
        if str(entry).endswith(".pyc") or "__pycache__" in str(entry):
            continue
        try:
            data = Path(locate(entry)).read_bytes()
        except OSError:
            continue
        digest.update(str(entry).encode("utf-8"))
        digest.update(b"\0")
        digest.update(data)
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def resolve_contract_pin_mode(explicit: str | None = None) -> str:
    if explicit:
        return explicit.strip().lower()
    for env_key in ("AKTA_CONTRACT_PIN_MODE", "AKTA_GRANT_MODE"):
        raw = os.environ.get(env_key, "").strip().lower()
        if raw:
            return raw
    if os.environ.get("AKTA_PRODUCTION_MODE", "").lower() in ("1", "true", "yes"):
        return "production"
    if os.environ.get("AKTA_VERIFY_POLICY", "").lower() in ("1", "true", "yes"):
        return "production"
    profile = os.environ.get("AKTA_RELEASE_PROFILE", "").strip().lower()
    if profile in CONTRACT_PIN_STRICT_MODES:
        return profile
    return "unit"


def pin_is_complete_for_release(pin: dict[str, Any] | None = None) -> list[str]:
    """Return errors when wheel/manifest/signer pins are incomplete."""
    data = pin if pin is not None else load_shared_contracts_pin()
    errors: list[str] = []
    for field in _PIN_HASH_FIELDS:
        if _is_placeholder_pin_value(data.get(field)):
            errors.append(f"shared_contracts_pin_incomplete:{field}")
    if _is_placeholder_pin_value(data.get("release_signer")):
        errors.append("shared_contracts_pin_incomplete:release_signer")
    pkg = str(data.get("package_version") or "").strip()
    if not pkg:
        errors.append("shared_contracts_pin_incomplete:package_version")
    return errors


def verify_installed_contracts_against_pin(
    *,
    mode: str | None = None,
    pin: dict[str, Any] | None = None,
    vendor_root: str | Path | None = None,
    raise_on_error: bool = True,
) -> dict[str, Any]:
    """Verify the installed contracts distribution against the policy pin.

    Release/production/institutional modes fail closed on incomplete pins and
    reject version-only identity (wheel / archive / installed digest required).
    """
    resolved_mode = resolve_contract_pin_mode(mode)
    strict = resolved_mode in CONTRACT_PIN_STRICT_MODES
    data = pin if pin is not None else load_shared_contracts_pin()
    errors: list[str] = []
    warnings: list[str] = []

    expected_version = str(data.get("package_version") or CONTRACTS_PACKAGE_VERSION)
    try:
        installed_version = importlib.metadata.version(CONTRACTS_PACKAGE_NAME)
    except importlib.metadata.PackageNotFoundError:
        installed_version = None
        errors.append(
            f"shared_contracts_not_installed:{CONTRACTS_PACKAGE_NAME} "
            "(pip install pinned wheel or vendor archive)"
        )

    if installed_version is not None and installed_version != expected_version:
        errors.append(
            f"shared_contracts_version_mismatch: "
            f"installed={installed_version!r} pin={expected_version!r}"
        )

    incomplete = pin_is_complete_for_release(data)
    if incomplete and strict:
        errors.extend(incomplete)
    elif incomplete:
        warnings.extend(incomplete)

    # source_archive_sha256 — vendor tree must stay byte-identical to pin.
    pinned_archive = str(data.get("source_archive_sha256") or "").strip()
    archive_root = Path(vendor_root) if vendor_root else DEFAULT_VENDOR_ROOT
    archive_actual: str | None = None
    if archive_root.is_dir() and not _is_placeholder_pin_value(pinned_archive):
        try:
            archive_actual = vendor_source_archive_sha256(archive_root)
        except OSError as exc:
            errors.append(f"shared_contracts_source_archive_unreadable:{exc}")
        else:
            if archive_actual != pinned_archive:
                errors.append(
                    "shared_contracts_source_archive_mismatch: "
                    f"pin={pinned_archive!r} vendor={archive_actual!r}"
                )
    elif strict and archive_root.is_dir() and _is_placeholder_pin_value(pinned_archive):
        errors.append("shared_contracts_pin_incomplete:source_archive_sha256")

    # Installed distribution digest vs wheel pin (reject version-only in strict).
    pinned_wheel = str(data.get("wheel_sha256") or "").strip()
    installed_digest = _installed_distribution_digest()
    if not _is_placeholder_pin_value(pinned_wheel):
        if installed_digest is None:
            msg = "shared_contracts_wheel_digest_unavailable"
            (errors if strict else warnings).append(msg)
        elif installed_digest != pinned_wheel:
            # Editable/source installs may not match a published wheel digest;
            # in strict modes still fail closed (prefer pinned wheel install).
            msg = (
                "shared_contracts_wheel_hash_mismatch: "
                f"pin={pinned_wheel!r} installed={installed_digest!r}"
            )
            (errors if strict else warnings).append(msg)
    elif strict:
        errors.append("shared_contracts_pin_incomplete:wheel_sha256")

    # release_artifact_hash continuity (2.1 content identity).
    # Import the installed package directly — do not call _contracts() here
    # (that path re-enters verification in strict modes).
    pinned_artifact = str(data.get("release_artifact_hash") or "").strip()
    if pinned_artifact and installed_version is not None:
        try:
            import scientific_authorization_contracts as _installed_contracts

            if hasattr(_installed_contracts, "release_artifact_hash"):
                actual_artifact = str(_installed_contracts.release_artifact_hash())
            else:
                actual_artifact = ""
        except Exception as exc:  # noqa: BLE001
            (errors if strict else warnings).append(
                f"shared_contracts_release_artifact_unavailable:{exc}"
            )
        else:
            if actual_artifact and actual_artifact != pinned_artifact:
                errors.append(
                    "shared_contracts_release_hash_mismatch: "
                    f"pin={pinned_artifact!r} installed={actual_artifact!r}"
                )

    if strict and installed_version is not None and not installed_digest and not archive_actual:
        errors.append(
            "shared_contracts_version_only_identity_rejected: "
            "require wheel_sha256 or source_archive_sha256 verification"
        )

    report = {
        "ok": not errors,
        "mode": resolved_mode,
        "strict": strict,
        "package": CONTRACTS_PACKAGE_NAME,
        "package_version": expected_version,
        "installed_version": installed_version,
        "wheel_sha256_pin": pinned_wheel,
        "installed_distribution_digest": installed_digest,
        "source_archive_sha256_pin": pinned_archive,
        "source_archive_sha256_actual": archive_actual,
        "release_manifest_sha256": data.get("release_manifest_sha256"),
        "release_signer": data.get("release_signer"),
        "errors": errors,
        "warnings": warnings,
    }
    if raise_on_error and errors:
        raise ContractPinError(
            "; ".join(errors) or "shared contracts pin verification failed",
            errors=errors,
        )
    return report


@lru_cache(maxsize=1)
def _contracts():
    try:
        import scientific_authorization_contracts as contracts
    except ImportError as exc:
        raise ImportError(
            "scientific-authorization-contracts is not installed. "
            "Install from the vendor tree before using AKTA: "
            "pip install ./vendor/scientific-authorization-contracts"
        ) from exc
    version = getattr(contracts, "__version__", None) or getattr(
        contracts, "PACKAGE_VERSION", None
    )
    if version and str(version) not in CONTRACTS_ACCEPTED_VERSIONS:
        raise ImportError(
            f"scientific-authorization-contracts {version!r} loaded; "
            f"AKTA accepts {sorted(CONTRACTS_ACCEPTED_VERSIONS)}"
        )
    # Runtime pin check for release/production/institutional modes.
    mode = resolve_contract_pin_mode()
    if mode in CONTRACT_PIN_STRICT_MODES:
        verify_installed_contracts_against_pin(mode=mode, raise_on_error=True)
    return contracts


def contracts_package_version() -> str:
    return str(getattr(_contracts(), "__version__", CONTRACTS_PACKAGE_VERSION))


def release_artifact_hash() -> str:
    c = _contracts()
    if hasattr(c, "release_artifact_hash"):
        return str(c.release_artifact_hash())
    if hasattr(c, "contracts_package_content_hash"):
        return str(c.contracts_package_content_hash())
    # Older/sibling installs may omit the helper; fall back to package metadata hash.
    version = str(getattr(c, "__version__", None) or getattr(c, "PACKAGE_VERSION", "") or "")
    try:
        from akta.hash import hash_object

        return hash_object(
            {
                "package": CONTRACTS_PACKAGE_NAME,
                "package_version": version or CONTRACTS_PACKAGE_VERSION,
                "envelope_schema_hash": str(c.authorization_envelope_schema_hash()),
                "grant_schema_hash": str(c.grant_schema_hash()),
            }
        )
    except Exception as exc:  # noqa: BLE001
        raise AttributeError(
            "installed contracts package lacks release_artifact_hash()"
        ) from exc


def envelope_version() -> str:
    return str(_contracts().ENVELOPE_VERSION)


def authorization_envelope_schema_hash() -> str:
    return str(_contracts().authorization_envelope_schema_hash())


def authorization_schema_provenance() -> dict[str, str]:
    return dict(_contracts().authorization_schema_provenance())


def capability_families() -> frozenset[str]:
    return _contracts().capability_families()


def family_operations() -> dict[str, list[str]]:
    return _contracts().family_operations()


def responsibility_rank() -> dict[str, int]:
    return _contracts().responsibility_rank()


def legacy_scope_migration() -> dict[str, tuple[str, str]]:
    return _contracts().legacy_scope_migration()


def grant_schema_version() -> str:
    return str(_contracts().grant_schema_version())


def grant_schema_hash() -> str:
    return str(_contracts().grant_schema_hash())


def load_contract_schema(name: str) -> dict[str, Any]:
    return _contracts().load_schema(name)


def load_conformance_cases(kind: str) -> list[dict[str, Any]]:
    return list(_contracts().load_conformance_cases(kind))


def operation_vocabulary() -> str:
    return ",".join(sorted(family_operations().keys()))


def shared_contract_report() -> dict[str, str]:
    """Acceptance report fields for AKTA ↔ SCOPE schema identity."""
    c = _contracts()
    pin = load_shared_contracts_pin()
    report = {
        "package": CONTRACTS_PACKAGE_NAME,
        "package_version": contracts_package_version(),
        "envelope_schema_version": str(c.ENVELOPE_VERSION),
        "envelope_schema_hash": str(c.authorization_envelope_schema_hash()),
        "grant_schema_version": str(c.grant_schema_version()),
        "grant_schema_hash": str(c.grant_schema_hash()),
        "family_vocabulary": ",".join(sorted(c.capability_families())),
        "operation_vocabulary": ",".join(sorted(c.family_operations().keys())),
        "release_artifact_hash": release_artifact_hash(),
        "wheel_sha256": str(pin.get("wheel_sha256") or ""),
        "source_archive_sha256": str(pin.get("source_archive_sha256") or ""),
        "release_manifest_sha256": str(pin.get("release_manifest_sha256") or ""),
        "release_signer": str(pin.get("release_signer") or ""),
    }
    return report


__all__ = [
    "CONTRACTS_ACCEPTED_VERSIONS",
    "CONTRACTS_PACKAGE_NAME",
    "CONTRACTS_PACKAGE_VERSION",
    "CONTRACT_PIN_STRICT_MODES",
    "ContractPinError",
    "ENVELOPE_SCHEMA_NAME",
    "ENVELOPE_VERSION",
    "GRANT_STATUS_SCHEMA_NAME",
    "GRANT_V2_SCHEMA_NAME",
    "authorization_envelope_schema_hash",
    "authorization_schema_provenance",
    "capability_families",
    "contracts_package_version",
    "envelope_version",
    "executable_module_hashes",
    "family_operations",
    "grant_schema_hash",
    "grant_schema_version",
    "legacy_scope_migration",
    "load_conformance_cases",
    "load_contract_schema",
    "load_shared_contracts_pin",
    "operation_vocabulary",
    "pin_is_complete_for_release",
    "release_artifact_hash",
    "resolve_contract_pin_mode",
    "responsibility_rank",
    "shared_contract_report",
    "vendor_source_archive_sha256",
    "verify_installed_contracts_against_pin",
]
