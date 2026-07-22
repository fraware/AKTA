"""Tests for scripts/sync_scope_contract_fixtures.py."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from scripts.sync_scope_contract_fixtures import build_fixtures, sync_fixtures

ROOT = Path(__file__).resolve().parent.parent
SCOPE_REPO = Path(os.environ.get("SCOPE_REPO_PATH", str(ROOT.parent / "SCOPE")))
FIXTURES = ROOT / "tests" / "fixtures"


@pytest.mark.skipif(not SCOPE_REPO.is_dir(), reason="SCOPE sibling repo not available")
def test_build_fixtures_from_scope_repo() -> None:
    order_fixture, narrowing_fixture, contract_version = build_fixtures(scope_repo=SCOPE_REPO)
    assert contract_version.startswith("akta-scope-contract-v")
    assert len(order_fixture["scope_order"]) >= 5
    assert order_fixture["contract_version"] == contract_version
    assert narrowing_fixture["contract_version"] == contract_version
    for entry in narrowing_fixture["valid_narrowing_pairs"]:
        assert entry["requested_scope"] in order_fixture["scope_order"]
        assert entry["granted_scope"] in order_fixture["scope_order"]


@pytest.mark.skipif(not SCOPE_REPO.is_dir(), reason="SCOPE sibling repo not available")
def test_sync_fixtures_dry_run(tmp_path: Path) -> None:
    report = sync_fixtures(scope_repo=SCOPE_REPO, fixtures_dir=tmp_path, dry_run=True)
    assert report["contract_version"]
    assert "scope_scope_order.json" in report["updated"] + report["unchanged"]
    assert "scope_valid_narrowing.json" in report["updated"] + report["unchanged"]


def test_local_fixtures_have_contract_version() -> None:
    for name in ("scope_scope_order.json", "scope_valid_narrowing.json"):
        data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
        assert data.get("contract_version"), f"{name} missing contract_version"
