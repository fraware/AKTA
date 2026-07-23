#!/usr/bin/env python3
"""Fail closed when scientific-authorization-contracts drift from the pinned release.

Compares:
1. Vendored package vs ``policy/shared_contracts_pin.json``
2. In-tree ``schemas/`` copies vs vendor
3. Sibling SCOPE contracts (when present) vs vendor / pin
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor" / "scientific-authorization-contracts"
PIN_PATH = ROOT / "policy" / "shared_contracts_pin.json"
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
    """Stable hash over schemas, vocabularies, conformance, and python helpers."""
    digest = hashlib.sha256()
    for rel_dir in ("schemas", "vocabularies", "conformance", "python", "."):
        base = contracts_root if rel_dir == "." else contracts_root / rel_dir
        if not base.exists():
            continue
        if rel_dir == ".":
            paths = [p for p in base.glob("*.md") if p.is_file()]
        else:
            paths = sorted(p for p in base.rglob("*") if p.is_file())
        for path in paths:
            if "__pycache__" in path.parts or path.suffix not in {".json", ".md", ".py"}:
                continue
            rel = path.relative_to(contracts_root).as_posix()
            digest.update(rel.encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
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

    envelope_hash = _sha256_file(VENDOR / "schemas" / SCHEMA_FILES[0])
    grant_hash = _sha256_file(VENDOR / "schemas" / SCHEMA_FILES[1])
    status_hash = _sha256_file(VENDOR / "schemas" / SCHEMA_FILES[2])
    family_hash = _sha256_file(VENDOR / "vocabularies" / VOCAB_FILES[0])
    ops_hash = _sha256_file(VENDOR / "vocabularies" / VOCAB_FILES[1])
    artifact = release_artifact_hash(VENDOR)
    family_csv = _family_vocab_csv(VENDOR)
    ops_csv = _operation_vocab_csv(VENDOR)

    expected = {
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
        # Identity fields vs pin (SCOPE may lag python helpers; schemas/vocabs are authoritative)
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
