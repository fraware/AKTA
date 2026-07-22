"""P7 autonomous operator production refusal tests (v1.0)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from akta import AKTAGate, AKTAContext
from akta.errors import PolicyError, UnsupportedProfileError

ROOT = Path(__file__).resolve().parent.parent


def test_p7_profile_not_supported_in_deployment_profiles() -> None:
    profiles = yaml.safe_load((ROOT / "policy" / "deployment_profiles.yaml").read_text(encoding="utf-8"))
    p7 = profiles["profiles"]["P7_fully_autonomous_scientific_operator"]
    assert p7["supported"] is False
    assert "non-goal" in p7["disclaimer"].lower() or "does not support" in p7["disclaimer"].lower()


def test_p7_gate_refuses_production_evaluation() -> None:
    gate = AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")
    with pytest.raises(UnsupportedProfileError, match="P7|not supported"):
        gate.evaluate(
            ai_output={"summary": "Autonomously operate entire lab."},
            requested_tool="robot_queue.submit",
            requested_action="submit_batch",
            context=AKTAContext.from_dict({"evidence_state": "E6_independently_reproduced_evidence"}),
            deployment_profile="P7_fully_autonomous_scientific_operator",
        )


def test_p7_production_mode_rejects_dev_hmac(monkeypatch: pytest.MonkeyPatch) -> None:
    """Production mode refuses in-repo dev HMAC key (fail-closed baseline)."""
    from akta.policy_integrity import DEV_HMAC_KEY_LABEL

    monkeypatch.setenv("AKTA_PRODUCTION_MODE", "1")
    monkeypatch.setenv("AKTA_POLICY_HMAC_KEY", DEV_HMAC_KEY_LABEL)
    with pytest.raises(PolicyError, match="Production mode rejects"):
        AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")
