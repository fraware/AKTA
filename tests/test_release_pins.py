"""P1-A institutional release pin and reject-gate tests."""

from __future__ import annotations

import re

from akta.release_pins import (
    INSTITUTIONAL_REJECTS,
    component_pin_errors,
    institutional_release_gate,
    load_release_pins,
    pins_for_release_report,
)

_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_VSA_PIN = "903d834f201535ac1525e3e8907254363209904f"


def test_release_pins_record_sibling_shas() -> None:
    pins = load_release_pins()
    components = pins["components"]
    assert components["SCOPE"]["commit"].startswith("41b0faf")
    assert components["PF-Core"]["commit"].startswith("629984c")
    assert components["PCS-Core"]["commit"].startswith("b4ae0c7")
    assert components["PCS-Bench"]["commit"].startswith("a3a080e")
    assert components["Scientific-Memory"]["commit"].startswith("784140b")
    assert components["VSA"]["status"] == "pinned"
    assert components["VSA"]["tag"] == "v0.7.2"
    assert components["VSA"]["commit"] == _VSA_PIN
    assert _SHA40.match(str(components["VSA"]["commit"]))
    shared = pins["shared_contracts"]
    assert shared["package_version"] == "2.1.0"
    assert shared["release_artifact_hash"].startswith("sha256:")


def test_institutional_gate_ok_without_checkouts_when_pins_real() -> None:
    result = institutional_release_gate(require_checkouts=False, flags={})
    assert result["ok"] is True
    assert not any("VSA" in e for e in result["errors"])
    assert result["beta"] is True
    assert result["components"]["VSA"]["status"] == "pinned"


def test_missing_vsa_checkout_fails_when_required(monkeypatch) -> None:
    from akta import release_pins as rp

    for key in (
        "VSA_REPO_PATH",
        "SCOPE_REPO_PATH",
        "PF_CORE_REPO_PATH",
        "PCS_CORE_REPO_PATH",
        "PCS_BENCH_REPO_PATH",
        "MEMORY_REPO_PATH",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(rp, "discover_sibling", lambda _env: None)
    errors = component_pin_errors(require_checkouts=True, require_sha_match=False)
    assert any("missing_required_sibling_checkout:VSA" in e for e in errors)


def test_vsa_sha_mismatch_flagged(tmp_path, monkeypatch) -> None:
    from akta import release_pins as rp

    fake_repo = tmp_path / "verified-science-agent"
    fake_repo.mkdir()
    (fake_repo / ".git").mkdir()
    monkeypatch.setenv("VSA_REPO_PATH", str(fake_repo))
    monkeypatch.setattr(rp, "git_rev_parse_head", lambda _p: "deadbeef" * 5)
    monkeypatch.setattr(rp, "checkout_matches_pin", lambda _p, _c: False)
    pins = load_release_pins()
    errors = component_pin_errors(pins, require_checkouts=True, require_sha_match=True)
    assert any("sibling_checkout_sha_mismatch:VSA" in e for e in errors)


def test_sibling_sha_mismatch_flagged(tmp_path, monkeypatch) -> None:
    from akta import release_pins as rp

    fake_repo = tmp_path / "SCOPE"
    fake_repo.mkdir()
    (fake_repo / ".git").mkdir()
    monkeypatch.setenv("SCOPE_REPO_PATH", str(fake_repo))
    monkeypatch.setattr(rp, "git_rev_parse_head", lambda _p: "deadbeef" * 5)
    pins = load_release_pins()
    errors = component_pin_errors(pins, require_checkouts=True, require_sha_match=True)
    assert any("sibling_checkout_sha_mismatch:SCOPE" in e for e in errors)


def test_synthetic_placeholder_commit_still_fail_closed() -> None:
    pins = load_release_pins()
    bad = dict(pins)
    components = dict(pins["components"])
    vsa = dict(components["VSA"])
    vsa["commit"] = "UNAVAILABLE-PLACEHOLDER-FAIL-CLOSED"
    vsa["status"] = "missing_placeholder"
    components["VSA"] = vsa
    bad["components"] = components
    errors = component_pin_errors(bad, require_checkouts=False)
    assert any("unpinned_or_placeholder_required_sibling:VSA" in e for e in errors)
    gated = institutional_release_gate(pins=bad, require_checkouts=False, flags={})
    assert not gated["ok"]


def test_institutional_rejects_simulated_and_mocks() -> None:
    for key in (
        "simulated_scope",
        "legacy_scalar_scope_grant",
        "mock_pf_validator",
        "mock_pcs_validator",
        "missing_pcs_bench",
        "synthetic_vsa_only_validation",
        "missing_scientific_memory_integration",
        "sibling_checkout_sha_mismatch",
        "shared_contracts_release_hash_mismatch",
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
    assert report["VSA"]["status"] == "pinned"
    assert report["VSA"]["commit"] == _VSA_PIN
    assert "shared_contracts" in report


def test_component_pin_errors_without_checkouts_accepts_real_pins() -> None:
    errors = component_pin_errors(require_checkouts=False)
    assert not any("VSA" in e for e in errors)
    assert not any("unpinned_or_placeholder" in e for e in errors)
