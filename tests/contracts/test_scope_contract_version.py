"""SCOPE fixture contract version pinning (AKTA-3)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from akta.scope_contract import (
    AKTA_SCOPE_CONTRACT_VERSION,
    get_fixture_contract_version,
    load_scope_order,
    validate_scope_runtime_contract,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def test_fixtures_include_contract_version() -> None:
    for name in ("scope_scope_order.json", "scope_valid_narrowing.json"):
        data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
        assert data.get("contract_version") == AKTA_SCOPE_CONTRACT_VERSION


def test_get_fixture_contract_version_matches_constant() -> None:
    load_scope_order.cache_clear()
    assert get_fixture_contract_version() == AKTA_SCOPE_CONTRACT_VERSION


def test_strict_mode_rejects_mismatched_fixture_version(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bad_fixture = tmp_path / "tests" / "fixtures" / "scope_scope_order.json"
    bad_fixture.parent.mkdir(parents=True)
    bad_fixture.write_text(
        json.dumps({
            "contract_version": "akta-scope-contract-v0.0.0",
            "scope_order": ["protocol_draft"],
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("AKTA_STRICT_SCOPE_CONTRACT", "1")
    monkeypatch.setenv("SCOPE_REPO_PATH", str(tmp_path))

    load_scope_order.cache_clear()
    with pytest.raises(ValueError, match="contract_version"):
        load_scope_order()


def test_strict_mode_rejects_unknown_scope_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    scope_dir = tmp_path / "scope"
    scope_dir.mkdir()
    (scope_dir / "integration_versions.py").write_text(
        'SCOPE_CORE_VERSION = "scope-core-v99.0"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("AKTA_STRICT_SCOPE_CONTRACT", "1")
    monkeypatch.setenv("SCOPE_REPO_PATH", str(tmp_path))

    with pytest.raises(ValueError, match="Unknown SCOPE runtime version"):
        validate_scope_runtime_contract(strict=True)


def test_strict_mode_accepts_compatible_scope_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    scope_dir = tmp_path / "scope"
    scope_dir.mkdir()
    (scope_dir / "integration_versions.py").write_text(
        'SCOPE_CORE_VERSION = "scope-core-v1.0"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("AKTA_STRICT_SCOPE_CONTRACT", "1")
    monkeypatch.setenv("SCOPE_REPO_PATH", str(tmp_path))

    runtime = validate_scope_runtime_contract(strict=True)
    assert runtime == "scope-core-v1.0"
