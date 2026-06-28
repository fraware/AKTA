"""Tests for policy integrity verification."""

from __future__ import annotations

from pathlib import Path

import pytest

from akta.errors import PolicyError
from akta.policy_integrity import verify_policy_integrity

ROOT = Path(__file__).resolve().parent.parent


def test_policy_manifest_verifies() -> None:
    assert verify_policy_integrity(ROOT / "policy") is True


def test_policy_manifest_detects_tampering(tmp_path: Path) -> None:
    import shutil
    import yaml

    shutil.copytree(ROOT / "policy", tmp_path / "policy")
    manifest_path = tmp_path / "policy" / "policy_manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    ontology = tmp_path / "policy" / "action_ontology.yaml"
    ontology.write_text(ontology.read_text(encoding="utf-8") + "\n# tamper\n", encoding="utf-8")
    with pytest.raises(PolicyError, match="hash mismatch"):
        verify_policy_integrity(tmp_path / "policy", required=True)
