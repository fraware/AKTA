"""Shared contract pin / AKTA↔SCOPE drift gates."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from akta.shared_contracts import CONTRACTS_PACKAGE_NAME, shared_contract_report
from scripts.assert_shared_contract_drift import assert_no_drift, release_artifact_hash

ROOT = Path(__file__).resolve().parent.parent
PIN = ROOT / "policy" / "shared_contracts_pin.json"
VENDOR = ROOT / "vendor" / "scientific-authorization-contracts"


def _installed_version() -> str | None:
    try:
        import importlib.metadata as md

        return md.version(CONTRACTS_PACKAGE_NAME)
    except Exception:  # noqa: BLE001
        return None


def test_shared_contracts_pin_matches_vendor() -> None:
    """Vendor archive must stay byte-identical to the policy pin (offline archive)."""
    pin = json.loads(PIN.read_text(encoding="utf-8"))
    assert release_artifact_hash(VENDOR) == pin["release_artifact_hash"]

    report = assert_no_drift(require_sibling=False)
    pin_vendor_errors = [
        e
        for e in report["errors"]
        if e.startswith("pin mismatch ")
        or e.startswith("in-tree schema drift")
        or "vendor" in e.lower()
    ]
    # Installed-distribution mismatches are environmental until the pinned wheel
    # is the active install; they must not mask vendor↔pin archive identity.
    installed = _installed_version()
    if installed == pin.get("package_version"):
        assert report["ok"], report["errors"]
    else:
        assert not pin_vendor_errors, pin_vendor_errors


def test_shared_contract_report_matches_pin() -> None:
    pin = json.loads(PIN.read_text(encoding="utf-8"))
    installed = _installed_version()
    if installed != pin.get("package_version"):
        pytest.skip(
            f"installed {CONTRACTS_PACKAGE_NAME}=={installed} != pin "
            f"{pin.get('package_version')}; install vendor archive to exercise report"
        )
    report = shared_contract_report()
    assert report["package_version"] == pin["package_version"]
    assert report["envelope_schema_version"] == pin["envelope_schema_version"]
    assert report["envelope_schema_hash"] == pin["envelope_schema_hash"]
    assert report["grant_schema_version"] == pin["grant_schema_version"]
    assert report["grant_schema_hash"] == pin["grant_schema_hash"]
    assert report["family_vocabulary"] == pin["family_vocabulary"]
    assert report["operation_vocabulary"] == pin["operation_vocabulary"]
    assert report["release_artifact_hash"] == pin["release_artifact_hash"]
    assert report["wheel_sha256"] == pin["wheel_sha256"]
    assert report["source_archive_sha256"] == pin["source_archive_sha256"]


def test_release_artifact_hash_stable() -> None:
    pin = json.loads(PIN.read_text(encoding="utf-8"))
    assert release_artifact_hash(VENDOR) == pin["release_artifact_hash"]
