"""Policy bundle versioning tests (v0.5)."""

from __future__ import annotations

from pathlib import Path

from akta import AKTAGate, AKTAContext
from akta.policy import PolicyBundle

ROOT = Path(__file__).resolve().parent.parent


def test_policy_bundle_version_v05() -> None:
    bundle = PolicyBundle.from_dir(ROOT / "policy")
    assert bundle.version == "akta-core-v0.5"
    assert "action_ontology.yaml" in bundle.policy_file_versions
    assert bundle.policy_file_versions["action_ontology.yaml"] == "action_ontology-v0.5"
    assert bundle.policy_file_versions["evidence_to_action_rules.yaml"] == "evidence_to_action_rules-v0.5"


def test_decision_includes_policy_file_versions() -> None:
    gate = AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")
    decision = gate.evaluate(
        ai_output={"summary": "Explain concept."},
        requested_tool="literature_search.query",
        requested_action="search",
        context=AKTAContext(),
        deployment_profile="P1_literature_hypothesis_assistant",
    )
    d = decision.to_dict()
    assert d["policy_version"] == "akta-core-v0.5"
    assert isinstance(d.get("policy_file_versions"), dict)
    assert d["policy_file_versions"]["evidence_to_action_rules.yaml"] == "evidence_to_action_rules-v0.5"
