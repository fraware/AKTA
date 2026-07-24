#!/usr/bin/env python3
"""Fail closed when scientific-authorization-contracts drift from the pinned release.

Compares the *installed* package (authoritative runtime) and the vendor tree
against ``policy/shared_contracts_pin.json``. Optionally checks sibling SCOPE
and in-tree ``schemas/`` copies.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor" / "scientific-authorization-contracts"
PIN_PATH = ROOT / "policy" / "shared_contracts_pin.json"
EXPECTED_PACKAGE = "scientific-authorization-contracts"
EXPECTED_VERSION = "2.2.0"
SCHEMA_FILES = (
    "authorization_envelope.v2.schema.json",
    "scope_grant.v2.schema.json",
    "scope_grant_status.v1.schema.json",
)
VOCAB_FILES = (
    "capability_families.json",
    "operations.json",
)


def _sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def release_artifact_hash(contracts_root: Path) -> str:
    """Stable hash matching ``contracts_package_content_hash`` (schemas + vocabularies).

    Prefers the package layout used by scientific-authorization-contracts 2.2
    (``src/`` or ``python/``). Falls back to top-level ``schemas/`` +
    ``vocabularies/`` for older vendor archives.
    """
    digest = hashlib.sha256()

    def _feed(logical: str, path: Path) -> None:
        digest.update(logical.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")

    package_roots = (
        contracts_root / "src" / "scientific_authorization_contracts",
        contracts_root / "python" / "scientific_authorization_contracts",
        contracts_root,
    )
    package_root = next(
        (
            root
            for root in package_roots
            if (root / "schemas").is_dir() and (root / "vocabularies").is_dir()
        ),
        None,
    )
    if package_root is None:
        return "sha256:" + ("0" * 64)

    for label in ("schemas", "vocabularies"):
        directory = package_root / label
        if not directory.is_dir():
            continue
        for path in sorted(p for p in directory.rglob("*") if p.is_file()):
            if "__pycache__" in path.parts:
                continue
            rel = path.relative_to(package_root).as_posix()
            _feed(rel, path)
    return "sha256:" + digest.hexdigest()

def _sibling_scope_contracts() -> Path | None:
    env = os.environ.get("SCOPE_REPO_PATH", "").strip()
    candidates: list[Path] = []
    if env:
        candidates.append(Path(env) / "scientific-authorization-contracts")
    candidates.append(ROOT.parent / "SCOPE" / "scientific-authorization-contracts")
    for path in candidates:
        if (path / "schemas" / SCHEMA_FILES[0]).is_file():
            return path.resolve()
    return None


def _load_pin() -> dict[str, Any]:
    return json.loads(PIN_PATH.read_text(encoding="utf-8"))


def _family_vocab_csv(contracts_root: Path) -> str:
    data = json.loads((contracts_root / "vocabularies" / "capability_families.json").read_text())
    return ",".join(sorted(data["families"]))


def _operation_vocab_csv(contracts_root: Path) -> str:
    data = json.loads((contracts_root / "vocabularies" / "operations.json").read_text())
    return ",".join(sorted(data["families"].keys()))


def _installed_contracts() -> Any:
    try:
        import scientific_authorization_contracts as contracts
    except ImportError as exc:
        raise ImportError(
            "scientific-authorization-contracts must be installed for drift checks: "
            "pip install ./vendor/scientific-authorization-contracts"
        ) from exc
    return contracts


def assert_no_drift(*, require_sibling: bool = False) -> dict[str, Any]:
    errors: list[str] = []
    if not VENDOR.is_dir():
        raise FileNotFoundError(f"Missing vendored contracts: {VENDOR}")
    pin = _load_pin()

    checks: dict[str, Any] = {
        "pin_path": str(PIN_PATH),
        "vendor_root": str(VENDOR.resolve()),
        "errors": errors,
    }

    # --- Installed package (authoritative runtime) ---
    try:
        dist = importlib.metadata.version(EXPECTED_PACKAGE)
    except importlib.metadata.PackageNotFoundError:
        errors.append(
            f"installed package {EXPECTED_PACKAGE!r} not found; "
            f"pip install ./vendor/scientific-authorization-contracts"
        )
        dist = None
    else:
        checks["installed_version"] = dist
        if dist != EXPECTED_VERSION:
            errors.append(
                f"installed package version {dist!r} != expected {EXPECTED_VERSION!r}"
            )
        pinned_version = pin.get("package_version") or pin.get("version")
        if pinned_version and pinned_version != dist:
            errors.append(
                f"pin package_version {pinned_version!r} != installed {dist!r}"
            )

    contracts = None
    try:
        contracts = _installed_contracts()
    except ImportError as exc:
        errors.append(str(exc))

    if contracts is not None:
        installed_hashes = {
            "envelope_schema_hash": str(contracts.authorization_envelope_schema_hash()),
            "grant_schema_hash": str(contracts.grant_schema_hash()),
            "grant_status_schema_hash": str(
                getattr(contracts, "grant_status_schema_hash", lambda: "")()
            ),
        }
        if hasattr(contracts, "release_artifact_hash"):
            installed_hashes["release_artifact_hash"] = str(contracts.release_artifact_hash())
        checks["installed_hashes"] = installed_hashes
        for key, value in installed_hashes.items():
            if not value:
                continue
            pinned = pin.get(key)
            if pinned != value:
                errors.append(
                    f"installed package mismatch {key}: pin={pinned!r} installed={value!r}"
                )
        pkg_ver = getattr(contracts, "__version__", None)
        if pkg_ver and str(pkg_ver) != EXPECTED_VERSION:
            errors.append(
                f"contracts.__version__ {pkg_ver!r} != {EXPECTED_VERSION!r}"
            )

    # --- Vendor tree vs pin ---
    envelope_hash = _sha256_file(VENDOR / "schemas" / SCHEMA_FILES[0])
    grant_hash = _sha256_file(VENDOR / "schemas" / SCHEMA_FILES[1])
    status_hash = _sha256_file(VENDOR / "schemas" / SCHEMA_FILES[2])
    family_hash = _sha256_file(VENDOR / "vocabularies" / VOCAB_FILES[0])
    ops_hash = _sha256_file(VENDOR / "vocabularies" / VOCAB_FILES[1])
    artifact = release_artifact_hash(VENDOR)
    family_csv = _family_vocab_csv(VENDOR)
    ops_csv = _operation_vocab_csv(VENDOR)

    expected = {
        "package": EXPECTED_PACKAGE,
        "package_version": EXPECTED_VERSION,
        "envelope_schema_version": "scientific-authorization-envelope-v2",
        "envelope_schema_hash": envelope_hash,
        "grant_schema_version": "scope-grant-v2",
        "grant_schema_hash": grant_hash,
        "grant_status_schema_hash": status_hash,
        "family_vocabulary": family_csv,
        "operation_vocabulary": ops_csv,
        "family_vocabulary_hash": family_hash,
        "operation_vocabulary_hash": ops_hash,
        "release_artifact_hash": artifact,
    }
    for key, value in expected.items():
        pinned = pin.get(key)
        if pinned != value:
            errors.append(f"pin mismatch {key}: pin={pinned!r} vendor={value!r}")

    # In-tree schemas/ must match vendor byte-for-byte.
    for name in SCHEMA_FILES:
        vendor_path = VENDOR / "schemas" / name
        local_path = ROOT / "schemas" / name
        if not local_path.is_file():
            errors.append(f"missing in-tree schema copy: schemas/{name}")
            continue
        if vendor_path.read_bytes() != local_path.read_bytes():
            errors.append(f"schemas/{name} diverges from vendor copy")

    sibling = _sibling_scope_contracts()
    checks["sibling_root"] = str(sibling) if sibling else None
    if sibling is None:
        if require_sibling:
            errors.append("SCOPE sibling scientific-authorization-contracts required but missing")
    else:
        for name in SCHEMA_FILES:
            v_bytes = (VENDOR / "schemas" / name).read_bytes()
            s_path = sibling / "schemas" / name
            if not s_path.is_file():
                errors.append(f"sibling missing schemas/{name}")
            elif s_path.read_bytes() != v_bytes:
                errors.append(f"sibling schemas/{name} diverges from AKTA vendor")
        for name in VOCAB_FILES:
            v_bytes = (VENDOR / "vocabularies" / name).read_bytes()
            s_path = sibling / "vocabularies" / name
            if not s_path.is_file():
                errors.append(f"sibling missing vocabularies/{name}")
            elif s_path.read_bytes() != v_bytes:
                errors.append(f"sibling vocabularies/{name} diverges from AKTA vendor")
        sib_envelope = _sha256_file(sibling / "schemas" / SCHEMA_FILES[0])
        if sib_envelope != pin["envelope_schema_hash"]:
            errors.append(
                f"sibling envelope_schema_hash {sib_envelope} != pin {pin['envelope_schema_hash']}"
            )
        sib_grant = _sha256_file(sibling / "schemas" / SCHEMA_FILES[1])
        if sib_grant != pin["grant_schema_hash"]:
            errors.append(
                f"sibling grant_schema_hash {sib_grant} != pin {pin['grant_schema_hash']}"
            )
        if _family_vocab_csv(sibling) != pin["family_vocabulary"]:
            errors.append("sibling family vocabulary diverges from pin")
        if _operation_vocab_csv(sibling) != pin["operation_vocabulary"]:
            errors.append("sibling operation vocabulary diverges from pin")

    checks["expected"] = expected
    checks["ok"] = not errors
    return checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--require-sibling",
        action="store_true",
        help="Fail when sibling SCOPE contracts are unavailable",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON report")
    args = parser.parse_args(argv)
    report = assert_no_drift(require_sibling=args.require_sibling)
    if args.json:
        print(json.dumps(report, indent=2))
    if not report["ok"]:
        for err in report["errors"]:
            print(f"FAIL: {err}", file=sys.stderr)
        return 1
    print("OK: shared scientific-authorization-contracts pin holds")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
