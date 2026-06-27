"""Tests for policy bundle loading."""

from pathlib import Path

from akta.policy import PolicyBundle

ROOT = Path(__file__).resolve().parent.parent


def test_policy_bundle_loads() -> None:
    bundle = PolicyBundle.from_dir(ROOT / "policy")
    assert bundle.version == "akta-core-v0.2"
    assert bundle.policy_hash.startswith("sha256:")
    assert bundle.tool_registry_hash.startswith("sha256:")
    assert "tools" in bundle.tool_registry or "lab_scheduler.prioritize" in bundle.tool_registry.get("tools", {})


def test_admissibility_matrix_normalize() -> None:
    bundle = PolicyBundle.from_dir(ROOT / "policy")
    assert bundle.normalize_decision("allowed_log") == "allowed_with_logging"
    assert bundle.normalize_decision("blocked_or_review") == "review_required"


def test_p7_unsupported() -> None:
    bundle = PolicyBundle.from_dir(ROOT / "policy")
    profile = bundle.deployment_profiles["profiles"]["P7_fully_autonomous_scientific_operator"]
    assert profile["supported"] is False
