"""Shared contract pin / AKTA↔SCOPE drift gates."""

from __future__ import annotations

import json
from pathlib import Path

from akta.shared_contracts import shared_contract_report
from scripts.assert_shared_contract_drift import assert_no_drift, release_artifact_hash

ROOT = Path(__file__).resolve().parent.parent
PIN = ROOT / "policy" / "shared_contracts_pin.json"
VENDOR = ROOT / "vendor" / "scientific-authorization-contracts"


def test_shared_contracts_pin_matches_vendor() -> None:
    report = assert_no_drift(require_sibling=False)
    assert report["ok"], report["errors"]


def test_shared_contract_report_matches_pin() -> None:
    pin = json.loads(PIN.read_text(encoding="utf-8"))
    report = shared_contract_report()
    assert report["package_version"] == pin["package_version"]
    assert report["envelope_schema_version"] == pin["envelope_schema_version"]
    assert report["envelope_schema_hash"] == pin["envelope_schema_hash"]
    assert report["grant_schema_version"] == pin["grant_schema_version"]
    assert report["grant_schema_hash"] == pin["grant_schema_hash"]
    assert report["family_vocabulary"] == pin["family_vocabulary"]
    assert report["operation_vocabulary"] == pin["operation_vocabulary"]
    assert report["release_artifact_hash"] == pin["release_artifact_hash"]


def test_release_artifact_hash_stable() -> None:
    pin = json.loads(PIN.read_text(encoding="utf-8"))
    assert release_artifact_hash(VENDOR) == pin["release_artifact_hash"]
