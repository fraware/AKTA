"""P1-A institutional release pin and reject-gate tests."""

from __future__ import annotations

from akta.release_pins import (
    INSTITUTIONAL_REJECTS,
    component_pin_errors,
    institutional_release_gate,
    load_release_pins,
    pins_for_release_report,
)


def test_release_pins_record_sibling_shas() -> None:
    pins = load_release_pins()
    components = pins["components"]
    assert components["SCOPE"]["commit"].startswith("41b0faf")
    assert components["PF-Core"]["commit"].startswith("629984c")
    assert components["PCS-Core"]["commit"].startswith("b4ae0c7")
    assert components["PCS-Bench"]["commit"].startswith("a3a080e")
    assert components["Scientific-Memory"]["commit"].startswith("784140b")
    assert components["VSA"]["status"] == "missing_placeholder"


def test_placeholder_vsa_fails_institutional_gate() -> None:
    result = institutional_release_gate(require_checkouts=False, flags={})
    assert not result["ok"]
    assert any("VSA" in e for e in result["errors"])
    assert result["beta"] is True


def test_institutional_rejects_simulated_and_mocks() -> None:
    for key in (
        "simulated_scope",
        "legacy_scalar_scope_grant",
        "mock_pf_validator",
        "mock_pcs_validator",
        "missing_pcs_bench",
        "synthetic_vsa_only_validation",
        "missing_scientific_memory_integration",
    ):
        assert key in INSTITUTIONAL_REJECTS
        gated = institutional_release_gate(
            require_checkouts=False,
            flags={key: True},
        )
        assert not gated["ok"]
        assert any(key in e for e in gated["errors"])


def test_pins_for_release_report_shape() -> None:
    report = pins_for_release_report()
    assert "SCOPE" in report
    assert "commit" in report["SCOPE"]


def test_component_pin_errors_without_checkouts_still_flags_placeholder() -> None:
    errors = component_pin_errors(require_checkouts=False)
    assert any("VSA" in e for e in errors)
