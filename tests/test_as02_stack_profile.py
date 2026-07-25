"""AS-02 stack profile validation tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from akta.stack_profile import StackProfileError, validate_stack_profile, validate_stack_profile_or_raise

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "as02"


def test_aligned_stack_profile_ok() -> None:
    result = validate_stack_profile(FIX / "stack_profile_aligned_valid.json")
    assert result["ok"] is True
    assert result["errors"] == []


def test_unsupported_stack_profile() -> None:
    result = validate_stack_profile(FIX / "stack_profile_unsupported.json")
    assert result["ok"] is False
    assert any("pin_mismatch:akta_version" in e for e in result["errors"])


def test_missing_components() -> None:
    result = validate_stack_profile(FIX / "stack_profile_missing_components.json")
    assert result["ok"] is False
    assert any("missing_component:VSA" in e for e in result["errors"])


def test_institutional_placeholder_signer_fail_closed() -> None:
    result = validate_stack_profile(FIX / "stack_profile_institutional_valid.json")
    assert result["ok"] is False
    assert any("shared_contracts_pin_incomplete" in e or "PLACEHOLDER" in e.upper() or "release_signer" in e for e in result["errors"])


def test_validate_or_raise() -> None:
    with pytest.raises(StackProfileError):
        validate_stack_profile_or_raise(FIX / "stack_profile_unsupported.json")


def test_cli_validate_stack_profile(tmp_path: Path) -> None:
    from akta.cli import main

    rc = main(["validate-stack-profile", str(FIX / "stack_profile_aligned_valid.json")])
    assert rc == 0
    rc_bad = main(["validate-stack-profile", str(FIX / "stack_profile_unsupported.json")])
    assert rc_bad != 0
