"""Oracle-independent scenario tests (hand-written expected labels)."""

from __future__ import annotations

import json
from pathlib import Path

from akta import AKTAGate, AKTAContext
from evals.run_oracle_independent import ORACLE_EXPECTED, run_oracle_eval

ROOT = Path(__file__).resolve().parent.parent


def test_oracle_independent_scenarios() -> None:
    gate = AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")
    path = ROOT / "scenarios" / "oracle_independent.jsonl"

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        scenario = json.loads(line)
        sid = scenario["scenario_id"]
        decision = gate.evaluate(
            ai_output=scenario.get("ai_output", ""),
            requested_tool=scenario["requested_tool"],
            requested_action=scenario.get("requested_action", scenario["requested_tool"]),
            context=AKTAContext.from_dict(scenario.get("context", {})),
            deployment_profile=scenario["deployment_profile"],
            domain_overlay=scenario.get("domain_overlay"),
        )
        expected = ORACLE_EXPECTED[sid]
        assert decision.admissibility == expected, f"{sid}: got {decision.admissibility}"
        d = decision.to_dict()
        assert d.get("policy_hash", "").startswith("sha256:")


def test_oracle_eval_runner_cli_report() -> None:
    report = run_oracle_eval(
        ROOT / "scenarios" / "oracle_independent.jsonl",
        policy_dir=ROOT / "policy",
        overlays_dir=ROOT / "overlays",
    )
    assert report["total"] == len(ORACLE_EXPECTED)
    assert report["passed"] is True


def test_f8_policy_hash_mismatch_detectable(tmp_path) -> None:
    from akta.errors import PolicyError
    from akta.policy_integrity import verify_policy_integrity
    import shutil

    shutil.copytree(ROOT / "policy", tmp_path / "policy")
    ontology = tmp_path / "policy" / "action_ontology.yaml"
    ontology.write_text(ontology.read_text(encoding="utf-8") + "\n# tampered\n", encoding="utf-8")
    try:
        verify_policy_integrity(tmp_path / "policy", required=True)
        raise AssertionError("expected PolicyError")
    except PolicyError as exc:
        assert "hash mismatch" in str(exc).lower() or "mismatch" in str(exc).lower()


def test_f8_public_scenario_policy_hash_present() -> None:
    """F8 integrity: every public scenario decision carries policy_hash."""
    from evals.run_scenarios import run_scenario_eval

    report = run_scenario_eval(
        ROOT / "scenarios" / "public_100.jsonl",
        ROOT / "scenarios" / "expected_decisions.jsonl",
        ROOT / "policy",
        ROOT / "overlays",
    )
    assert report["passed"] is True
    for result in report["results"]:
        ph = result.get("actual", {}).get("policy_hash", "")
        assert ph.startswith("sha256:"), result["scenario_id"]
