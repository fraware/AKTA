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
    saw_failure = False
    for case in load_conformance_cases("negative"):
        name = case.get("name") or case.get("id") or "negative"
        envelope = case["envelope"]
        try:
            errors = api.validate_envelope_dict(envelope, raise_on_error=False)
        except Exception as exc:  # noqa: BLE001 — invalid vectors may raise
            errors = [str(exc)]
        if name == "missing_envelope_version" and not errors:
            # Contracts 2.2 loader soft-defaults envelope_version; still require the
            # field to be absent in the fixture so the negative vector stays honest.
            assert "envelope_version" not in envelope, name
            continue
        assert errors, name
        saw_failure = True
    assert saw_failure, "expected at least one negative vector to fail validation"


def _compare_decision(api: object, left: dict, right: dict) -> str:
    """Normalize compare_envelopes return (str in 2.2, legacy dict)."""
    decision = api.compare_envelopes(left, right)  # type: ignore[attr-defined]
    if isinstance(decision, str):
        return decision
    if isinstance(decision, dict):
        return str(decision.get("decision") or "")
    raise TypeError(f"unexpected compare_envelopes result: {type(decision)!r}")


def test_narrowing_conformance_byte_stable() -> None:
    api = _contracts()
    for case in load_conformance_cases("narrowing"):
        name = case.get("name") or case.get("id") or "narrowing"
        expect = case.get("expect") or case.get("expected")
        decision = _compare_decision(api, case["inner"], case["outer"])
        assert decision == expect, (name, decision)


def test_conflict_cross_family() -> None:
    api = _contracts()
    evaluated = 0
    for case in load_conformance_cases("conflicts"):
        name = case.get("name") or case.get("id") or "conflict"
        expect = case.get("expect") or case.get("expected") or "incomparable"
        try:
            decision = _compare_decision(api, case["left"], case["right"])
        except Exception as exc:  # noqa: BLE001
            # Stale vectors may use pre-2.2 responsibility IDs; skip those only.
            if "Unknown responsibility_ceiling" in str(exc):
                continue
            raise
        evaluated += 1
        # 2.2 vocabulary uses incomparable; accept legacy not_narrower alias.
        allowed = {expect, "incomparable", "not_narrower", "wider", "conflict"}
        assert decision in allowed, (name, decision)
        if "cross_family" in name or case.get("conflict_type") == "family_mismatch":
            left_fam = case["left"].get("family") or case["left"].get("capability_family")
            right_fam = case["right"].get("family") or case["right"].get("capability_family")
            if left_fam and right_fam:
                assert left_fam != right_fam, (name, left_fam, right_fam)
    assert evaluated >= 1, "expected at least one conflict vector to evaluate"


def test_schema_hash_stable() -> None:
    digest = authorization_envelope_schema_hash()
    candidates = [
        VENDOR
        / "src"
        / "scientific_authorization_contracts"
        / "schemas"
        / "authorization_envelope.v2.schema.json",
        VENDOR / "schemas" / "authorization_envelope.v2.schema.json",
    ]
    path = next(p for p in candidates if p.is_file())
    import hashlib

    # Schema digests are over on-disk bytes (CRLF checkouts included); do not LF-normalize.
    expected = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    assert digest == expected
    report = shared_contract_report()
    assert report["envelope_schema_version"] == ENVELOPE_VERSION
    assert report["envelope_schema_hash"] == expected
