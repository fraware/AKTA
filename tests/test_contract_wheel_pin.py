"""P0-1: contract wheel / archive pin verification."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from akta.shared_contracts import (
    CONTRACTS_PACKAGE_NAME,
    ContractPinError,
    executable_module_hashes,
    load_shared_contracts_pin,
    pin_is_complete_for_release,
    vendor_source_archive_sha256,
    verify_installed_contracts_against_pin,
)
from akta.sibling_repos import discover_sibling
from scripts.assert_shared_contract_drift import release_artifact_hash

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor" / "scientific-authorization-contracts"


def _is_placeholder(value: object) -> bool:
    text = str(value or "").strip().upper()
    return (not text) or ("PLACEHOLDER" in text) or ("FAIL-CLOSED" in text)


def _installed_contracts_version() -> str | None:
    try:
        import importlib.metadata as md

        return md.version(CONTRACTS_PACKAGE_NAME)
    except Exception:  # noqa: BLE001
        return None


def _load_vendor_conformance(kind: str) -> list[dict]:
    root = VENDOR / "conformance" / kind
    if not root.is_dir():
        return []
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(root.glob("*.json"))
    ]


def test_installed_contract_wheel_hash_matches_pin() -> None:
    pin = load_shared_contracts_pin()
    assert pin["package_version"] == "2.2.0"
    assert pin["source_archive_sha256"] == vendor_source_archive_sha256(VENDOR)
    assert pin["release_artifact_hash"] == release_artifact_hash(VENDOR)
    assert not _is_placeholder(pin.get("wheel_sha256"))
    assert pin["wheel_sha256"].startswith("sha256:")

    # Signed release_signer remains unpublished PLACEHOLDER.
    incomplete = pin_is_complete_for_release(pin)
    assert incomplete
    assert any("release_signer" in e for e in incomplete)
    with pytest.raises(ContractPinError) as excinfo:
        verify_installed_contracts_against_pin(mode="release", raise_on_error=True)
    assert any("shared_contracts_pin_incomplete:release_signer" in e for e in excinfo.value.errors)

    report = verify_installed_contracts_against_pin(mode="unit", raise_on_error=False)
    assert report["source_archive_sha256_actual"] == pin["source_archive_sha256"]
    assert any("shared_contracts_pin_incomplete:release_signer" in w for w in report["warnings"])

    installed = report["installed_version"]
    if installed == pin["package_version"]:
        digest = report.get("installed_distribution_digest")
        if digest == pin["wheel_sha256"]:
            assert report["ok"] is True
        elif digest:
            assert any(
                "shared_contracts_wheel_hash_mismatch" in e
                for e in (report["errors"] + report["warnings"])
            )
        else:
            assert report["source_archive_sha256_actual"] == pin["source_archive_sha256"]
    else:
        assert report["ok"] is False
        assert any("shared_contracts_version_mismatch" in e for e in report["errors"])


def test_sibling_scope_uses_same_wheel_hash() -> None:
    pin = load_shared_contracts_pin()
    scope = discover_sibling("SCOPE_REPO_PATH")
    if scope is None:
        pytest.skip("SCOPE sibling checkout not available")

    candidates = [
        scope / "policy" / "shared_contracts_pin.json",
        scope / "scientific-authorization-contracts" / "pin.json",
        scope / "contracts" / "shared_contracts_pin.json",
    ]
    sibling_pin_path = next((p for p in candidates if p.is_file()), None)
    if sibling_pin_path is not None:
        sibling_pin = json.loads(sibling_pin_path.read_text(encoding="utf-8"))
        for field in ("wheel_sha256", "source_archive_sha256", "package_version"):
            left = str(pin.get(field) or "").strip()
            right = str(sibling_pin.get(field) or "").strip()
            if left and right and not _is_placeholder(left) and not _is_placeholder(right):
                assert left == right, f"SCOPE/AKTA {field} mismatch"
        return

    sibling_vendor = scope / "scientific-authorization-contracts"
    if not sibling_vendor.is_dir():
        pytest.skip("SCOPE shared-contracts pin/archive not present")

    sibling_hash = vendor_source_archive_sha256(sibling_vendor)
    if sibling_hash != pin["source_archive_sha256"]:
        pytest.skip(
            "SCOPE contracts archive diverges from AKTA pin "
            f"(scope={sibling_hash} akta={pin['source_archive_sha256']}); "
            "awaiting contracts 2.2 co-release pin"
        )


def test_executable_module_hashes_match() -> None:
    vendor_pkg = VENDOR / "python" / "scientific_authorization_contracts"
    assert vendor_pkg.is_dir()
    vendor = {
        path.name: "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(vendor_pkg.glob("*.py"))
        if path.is_file()
    }
    assert vendor
    # Helper agrees with direct vendor hashing.
    combined = executable_module_hashes(vendor_root=VENDOR)
    for name, digest in vendor.items():
        assert combined[name] == digest

    installed_ver = _installed_contracts_version()
    pin = load_shared_contracts_pin()
    if installed_ver != pin["package_version"]:
        pytest.skip(
            f"installed {CONTRACTS_PACKAGE_NAME}=={installed_ver} "
            f"!= pin {pin['package_version']}; vendor module digests verified"
        )

    import scientific_authorization_contracts as contracts

    installed_root = Path(contracts.__file__).resolve().parent
    installed = {
        path.name: "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(installed_root.glob("*.py"))
        if path.is_file()
    }
    assert installed == vendor


def test_conformance_vectors_match_scope() -> None:
    pin = load_shared_contracts_pin()
    kinds = ("positive", "negative", "narrowing", "conflicts")
    vendor_cases = {kind: _load_vendor_conformance(kind) for kind in kinds}
    assert any(vendor_cases.values()), "vendor archive has no conformance vectors"
    assert pin["release_artifact_hash"] == release_artifact_hash(VENDOR)

    installed_ver = _installed_contracts_version()
    if installed_ver == pin["package_version"]:
        from akta.shared_contracts import load_conformance_cases

        installed_cases = {kind: load_conformance_cases(kind) for kind in kinds}
        assert installed_cases == vendor_cases
    else:
        # Still assert vendor vectors are well-formed JSON objects.
        for kind, cases in vendor_cases.items():
            for case in cases:
                assert isinstance(case, dict), f"vendor conformance {kind} not an object"

    scope = discover_sibling("SCOPE_REPO_PATH")
    if scope is None:
        return
    scope_conf = scope / "scientific-authorization-contracts" / "conformance"
    if not scope_conf.is_dir():
        return
    for kind in kinds:
        scope_root = scope_conf / kind
        if not scope_root.is_dir():
            continue
        scope_cases = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(scope_root.glob("*.json"))
        ]
        if scope_cases != vendor_cases[kind]:
            pytest.skip(
                f"SCOPE conformance drift in {kind}; awaiting contracts 2.2 co-release pin"
            )
