"""Shared envelope conformance vectors (P0-A / P0-D)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from akta.shared_contracts import (
    ENVELOPE_VERSION,
    _contracts,
    authorization_envelope_schema_hash,
    load_conformance_cases,
    shared_contract_report,
)

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor" / "scientific-authorization-contracts"


def test_positive_envelopes_validate() -> None:
    api = _contracts()
    for case in load_conformance_cases("positive"):
        errors = api.validate_envelope_dict(case["envelope"], raise_on_error=False)
        assert errors == [], case["name"]


def test_negative_envelopes_invalid() -> None:
    api = _contracts()
    for case in load_conformance_cases("negative"):
        errors = api.validate_envelope_dict(case["envelope"], raise_on_error=False)
        assert errors, case["name"]


def test_narrowing_conformance_byte_stable() -> None:
    api = _contracts()
    for case in load_conformance_cases("narrowing"):
        decision = api.compare_envelopes(case["inner"], case["outer"])
        assert decision["decision"] == case["expect"], (case["name"], decision)


def test_conflict_cross_family() -> None:
    api = _contracts()
    for case in load_conformance_cases("conflicts"):
        decision = api.compare_envelopes(case["left"], case["right"])
        assert decision["decision"] == "not_narrower"
        assert decision["same_family"] is False


def test_schema_hash_stable() -> None:
    digest = authorization_envelope_schema_hash()
    path = VENDOR / "schemas" / "authorization_envelope.v2.schema.json"
    import hashlib

    expected = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    assert digest == expected
    report = shared_contract_report()
    assert report["envelope_schema_version"] == ENVELOPE_VERSION
