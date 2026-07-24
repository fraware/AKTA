"""AKTA 1.2 P0-13 native SCOPE acceptance scenario.

Native grant: protocol/draft, protocol-v3, tenant lab-a, project catalyst-7,
two uses, one item/action, recording + PF trace required.

Skips only when SCOPE sibling is absent in unit CI. Required on release-gate
(``AKTA_REQUIRE_NATIVE_SCOPE=1`` / ``AKTA_RELEASE_GATE=1``).
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

from akta.errors import InsufficientAuthorizationContext, UnsupportedProfileError
from akta.evidence_independence import check_evidence_independence
from akta.requested_authorization import build_requested_authorization_context
from akta.scope_interop import (
    reject_exhausted_use,
    strict_verify_grant,
    verify_action_containment,
    verify_evidence_independence,
    verify_status_attestation,
)
from akta.sibling_repos import discover_sibling

PROTOCOL_ID = "protocol-v3"
PROTOCOL_VERSION = "3"
TENANT_ID = "lab-a"
PROJECT_ID = "catalyst-7"
APPROVED_TOOL = "protocol_editor.draft_change"
CEILING = "R4_methodological_modification"
TOOL_REGISTRY_HASH = "sha256:" + ("ab" * 32)


def _require_native() -> bool:
    return os.environ.get("AKTA_REQUIRE_NATIVE_SCOPE", "").strip().lower() in {
        "1",
        "true",
        "yes",
    } or os.environ.get("AKTA_RELEASE_GATE", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _scope_available() -> bool:
    try:
        import scope  # noqa: F401
    except ImportError:
        return False
    repo = discover_sibling("SCOPE_REPO_PATH")
    if repo is None:
        return False
    return (repo / "policy").is_dir() and (
        repo / "examples" / "protocol_change_review"
    ).is_dir()


pytestmark = pytest.mark.integration


def _skip_unless_scope() -> None:
    if _scope_available():
        return
    if _require_native():
        pytest.fail(
            "SCOPE sibling required when AKTA_REQUIRE_NATIVE_SCOPE=1 / "
            "AKTA_RELEASE_GATE=1 (release-gate); discover via SCOPE_REPO_PATH "
            "or a sibling checkout named SCOPE"
        )
    pytest.skip(
        "SCOPE sibling absent (set SCOPE_REPO_PATH or clone SCOPE next to AKTA); "
        "native acceptance is skipped in unit CI and required on release-gate"
    )


def _control_evidence() -> dict[str, Any]:
    h = "sha256:" + ("cd" * 32)
    return {
        "requires_recording": {
            "satisfied": True,
            "artifact_id": "rec-1",
            "artifact_hash": h,
        },
        "requires_pf_core_trace": {
            "satisfied": True,
            "trace_id": "tr-1",
            "trace_hash": h,
        },
    }


def _scenario_envelope() -> dict[str, Any]:
    return {
        "family": "protocol",
        "operation": "draft",
        "target": {
            "type": "protocol",
            "protocol_id": PROTOCOL_ID,
            "protocol_version": PROTOCOL_VERSION,
        },
        "allowed_tools": [APPROVED_TOOL],
        "blocked_tools": [
            "protocol_editor.update_active_protocol",
            "robot_queue.submit",
            "lab_scheduler.prioritize",
        ],
        "cardinality": {
            "mode": "bounded",
            "maximum_uses": 2,
            "maximum_items": 1,
        },
        "environment": {
            "tenant_id": TENANT_ID,
            "project_id": PROJECT_ID,
            "domain_overlay": "materials_v0.1",
        },
        "responsibility_ceiling": CEILING,
        "constraints": {
            "requires_recording": True,
            "requires_pf_core_trace": True,
        },
        "expiration": {
            "absolute_expiration": None,
            "expires_after": [
                "protocol_version_change",
                "policy_version_change",
                "tool_registry_change",
            ],
        },
    }


def _write_org_rbac(policy_dir: Path, reviewer_id: str = "r1") -> None:
    org_rbac = {
        "version": "scope-core-v1.0",
        "org_units": {
            "genomics_lab": {
                "tenant_id": TENANT_ID,
                "members": {reviewer_id: {"roles": ["protocol_owner"]}},
            }
        },
        "delegations": [],
        "role_permissions": {
            "protocol_owner": {
                "can_submit_decisions": True,
                "can_vote_in_session": True,
            }
        },
    }
    (policy_dir / "org_rbac.yaml").write_text(yaml.safe_dump(org_rbac), encoding="utf-8")


def _issue_acceptance_grant(tmp_path: Path) -> tuple[Any, dict[str, Any], dict[str, Any], Any]:
    from scientific_authorization_contracts import AuthorizationEnvelope
    from scope import ScopeEngine
    from scope.signing import Ed25519Signer
    from scope.sqlite_ledger import SqliteScopeLedger

    scope_repo = discover_sibling("SCOPE_REPO_PATH")
    assert scope_repo is not None
    policy_src = scope_repo / "policy"
    examples = scope_repo / "examples" / "protocol_change_review"

    reviewer_key = tmp_path / "reviewer.pem"
    reviewer_pub = tmp_path / "reviewer.pub"
    Ed25519Signer.generate_keypair(reviewer_key, reviewer_pub)
    issuer_key = tmp_path / "issuer.pem"
    issuer_pub = tmp_path / "issuer.pub"
    Ed25519Signer.generate_keypair(issuer_key, issuer_pub)
    issuer = Ed25519Signer(issuer_key)

    policy_dir = tmp_path / "policy"
    shutil.copytree(policy_src, policy_dir)
    registry = {
        "version": "test-registry-v1",
        "reviewers": {
            "r1": {
                "public_key_ref": Ed25519Signer(reviewer_key).public_key_ref(),
                "public_key_file": str(reviewer_pub),
                "status": "active",
                "identity_assurance_floor": "IAL3",
                "tenant_id": TENANT_ID,
            }
        },
    }
    (policy_dir / "reviewer_key_registry.yaml").write_text(
        yaml.safe_dump(registry), encoding="utf-8"
    )
    _write_org_rbac(policy_dir)

    ledger = SqliteScopeLedger(tmp_path / "acceptance.sqlite", tenant_id=TENANT_ID)
    engine = ScopeEngine.from_policy_dir(
        policy_dir,
        tenant_id=TENANT_ID,
        ledger=ledger,
        issuer_verifier=issuer,
        require_production_deps=False,
        require_manifest_signature=False,
    )
    engine._issuer_signer = issuer  # type: ignore[attr-defined]

    record = json.loads((examples / "akta_record.json").read_text(encoding="utf-8"))
    trigger = json.loads((examples / "review_trigger.json").read_text(encoding="utf-8"))
    trigger = dict(trigger)
    trigger["scientific_context"] = {
        **dict(trigger.get("scientific_context") or {}),
        "protocol_id": PROTOCOL_ID,
        "protocol_version": "protocol-v3",
        "project_id": PROJECT_ID,
        "tenant_id": TENANT_ID,
        "tool_registry_version": TOOL_REGISTRY_HASH,
        "domain_overlay": "materials_v0.1",
        "evidence_state": "E2_preliminary_signal",
        "validation_status": "V1_literature_supported",
    }
    packet = engine.create_packet(record, trigger)
    requested = AuthorizationEnvelope.from_dict(
        {
            "family": "protocol",
            "operation": "update_active",
            "target": {
                "type": "protocol",
                "protocol_id": PROTOCOL_ID,
                "protocol_version": PROTOCOL_VERSION,
            },
            "allowed_tools": [
                APPROVED_TOOL,
                "protocol_editor.update_active_protocol",
            ],
            "blocked_tools": ["robot_queue.submit"],
            "environment": {
                "tenant_id": TENANT_ID,
                "project_id": PROJECT_ID,
                "domain_overlay": "materials_v0.1",
            },
            "responsibility_ceiling": CEILING,
        }
    ).to_dict()
    decision = engine.submit_decision(
        packet,
        {"reviewer_id": "r1", "role": "protocol_owner"},
        {
            "type": "approve_narrower_scope",
            "approved_scope": "protocol_draft",
            "requested_authorization_envelope": requested,
            "approved_authorization_envelope": _scenario_envelope(),
            "rationale": "AKTA 1.2 acceptance",
        },
    )
    decision = engine.sign_decision(decision, Ed25519Signer(reviewer_key))
    grant = engine.issue_grant(packet, decision, issuer_signer=issuer)
    return engine, packet, grant, issuer


def _action(
    grant: dict[str, Any],
    *,
    operation: str = "draft",
    protocol_id: str = PROTOCOL_ID,
    protocol_version: str = PROTOCOL_VERSION,
    tenant_id: str = TENANT_ID,
    project_id: str = PROJECT_ID,
    control_evidence: dict[str, Any] | None = None,
    tool: str = APPROVED_TOOL,
) -> dict[str, Any]:
    return {
        "requested_tool": tool,
        "family": "protocol",
        "operation": operation,
        "target": {
            "type": "protocol",
            "protocol_id": protocol_id,
            "protocol_version": protocol_version,
        },
        "environment": {
            "tenant_id": tenant_id,
            "project_id": project_id,
            "domain_overlay": "materials_v0.1",
        },
        "responsibility_level": CEILING,
        "item_count": 1,
        "protocol_id": protocol_id,
        "protocol_version": protocol_version,
        "evidence_state": "E2_preliminary_signal",
        "control_evidence": dict(
            control_evidence if control_evidence is not None else _control_evidence()
        ),
    }


@pytest.fixture
def acceptance(tmp_path: Path) -> tuple[Any, dict[str, Any], dict[str, Any], Any]:
    _skip_unless_scope()
    return _issue_acceptance_grant(tmp_path)


def test_positive_two_uses_then_exhausted(acceptance: tuple) -> None:
    engine, _packet, grant, issuer = acceptance
    assert strict_verify_grant(grant) is True
    action = _action(grant)
    assert verify_action_containment(grant, action) is True

    r1 = engine.authorize_and_consume(grant["grant_id"], action, "use-1")
    assert r1.allowed and r1.consumed
    r2 = engine.authorize_and_consume(grant["grant_id"], action, "use-2")
    assert r2.allowed and r2.consumed
    st = engine.grant_status(grant["grant_id"])
    assert st["status"] == "exhausted"
    assert reject_exhausted_use(grant, st, action) is True
    att = engine.issue_grant_status_attestation(
        grant["grant_id"], signer=issuer, audience="akta"
    )
    assert verify_status_attestation(att, grant) is True


def test_missing_protocol_tenant_no_invented_defaults() -> None:
    """Fail closed: missing protocol/tenant must not invent unspecified/default."""
    with pytest.raises(InsufficientAuthorizationContext) as exc:
        build_requested_authorization_context(
            requested_tool=APPROVED_TOOL,
            requested_action="draft",
            action_class="A5_protocol_modification",
            context={},  # missing protocol/tenant
            mode="release",
            allow_migration_fallbacks=False,
        )
    assert exc.value.missing


def test_unknown_tool_abstain(acceptance: tuple) -> None:
    _engine, _packet, grant, _issuer = acceptance
    action = _action(grant, tool="totally.unknown.mutating_tool")
    assert verify_action_containment(grant, action) is False


def test_active_update_fails(acceptance: tuple) -> None:
    engine, _packet, grant, _issuer = acceptance
    pre = engine.preflight_authorize(
        grant["grant_id"], _action(grant, operation="update_active")
    )
    assert not pre.allowed
    assert verify_action_containment(
        grant, _action(grant, operation="update_active")
    ) is False


def test_wrong_project_fails(acceptance: tuple) -> None:
    engine, _packet, grant, _issuer = acceptance
    denied = engine.preflight_authorize(
        grant["grant_id"], _action(grant, project_id="other-project")
    )
    assert not denied.allowed
    assert verify_action_containment(
        grant, _action(grant, project_id="other-project")
    ) is False


def test_wrong_tenant_fails(acceptance: tuple) -> None:
    engine, _packet, grant, _issuer = acceptance
    denied = engine.preflight_authorize(
        grant["grant_id"], _action(grant, tenant_id="lab-b")
    )
    assert not denied.allowed


def test_missing_recording_and_pf_trace_fail(acceptance: tuple) -> None:
    engine, _packet, grant, _issuer = acceptance
    missing_rec = _action(
        grant,
        control_evidence={
            "requires_pf_core_trace": {
                "satisfied": True,
                "trace_id": "tr-1",
                "trace_hash": "sha256:" + ("cd" * 32),
            }
        },
    )
    pre = engine.preflight_authorize(grant["grant_id"], missing_rec)
    assert not pre.allowed

    missing_pf = _action(
        grant,
        control_evidence={
            "requires_recording": {
                "satisfied": True,
                "artifact_id": "rec-1",
                "artifact_hash": "sha256:" + ("cd" * 32),
            }
        },
    )
    pre = engine.preflight_authorize(grant["grant_id"], missing_pf)
    assert not pre.allowed


def test_responsibility_cardinality_and_replay(acceptance: tuple) -> None:
    engine, _packet, grant, _issuer = acceptance
    action = _action(grant)
    first = engine.authorize_and_consume(grant["grant_id"], action, "idem-1")
    assert first.allowed
    replay = engine.authorize_and_consume(grant["grant_id"], action, "idem-1")
    assert replay.allowed and replay.idempotent_replay

    # Item count over grant maximum_items=1 must fail containment.
    over = dict(action)
    over["item_count"] = 5
    assert verify_action_containment(grant, over) is False


def test_revocation_fails(acceptance: tuple) -> None:
    engine, _packet, grant, _issuer = acceptance
    engine.revoke_grant(grant["grant_id"], reason="acceptance revoke")
    denied = engine.authorize_and_consume(
        grant["grant_id"], _action(grant), "after-revoke"
    )
    assert not denied.allowed
    st = engine.grant_status(grant["grant_id"])
    assert reject_exhausted_use(grant, st, _action(grant)) or st.get("status") == "revoked"


def test_wrong_manifest_source_rejected(acceptance: tuple) -> None:
    _engine, _packet, grant, _issuer = acceptance
    # Must not invent missing source hashes — strip and confirm fail-closed.
    broken = dict(grant)
    broken["source"] = dict(grant.get("source") or {})
    broken["source"].pop("packet_hash", None)
    assert strict_verify_grant(broken) is False


def test_evidence_and_profile_blocks_preserved(acceptance: tuple) -> None:
    _engine, _packet, grant, _issuer = acceptance
    assert verify_evidence_independence(grant) is True
    for kind, decision, reason in (
        ("evidence", "blocked", "weak evidence block"),
        ("deployment_profile", "blocked", "unsupported profile"),
        ("domain_overlay", "blocked", "domain overlay block"),
        ("unknown_consequential_tool", "blocked", "unknown consequential tool"),
        (
            "unsupported_autonomous_profile",
            "blocked",
            "P7 autonomous operator refusal",
        ),
    ):
        result = check_evidence_independence(
            scope_grant=grant,
            pre_layers={kind: {"decision": decision, "reason": reason}},
            post_decision="allowed",
        )
        assert not result.ok


def test_p7_refusal_not_cleared_by_grant() -> None:
    from akta import AKTAContext, AKTAGate

    root = Path(__file__).resolve().parent.parent
    gate = AKTAGate.from_policy_dir(root / "policy", overlays_dir=root / "overlays")
    with pytest.raises(UnsupportedProfileError):
        gate.evaluate(
            ai_output={"summary": "Operate lab autonomously."},
            requested_tool="robot_queue.submit",
            requested_action="submit_batch",
            context=AKTAContext.from_dict(
                {"evidence_state": "E6_independently_reproduced_evidence"}
            ),
            deployment_profile="P7_fully_autonomous_scientific_operator",
        )


def test_native_wheel_phase_entrypoint() -> None:
    """Wheel smoke native phase runs or skips cleanly."""
    _skip_unless_scope()
    from akta.wheel_smoke import run_native_scope_phase

    report = run_native_scope_phase()
    assert report.get("passed") is True
    assert not report.get("skipped")
    assert "akta_strict_verify" in (report.get("steps") or [])
