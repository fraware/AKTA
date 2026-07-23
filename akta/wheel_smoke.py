"""Institutional wheel-install smoke path (AKTA 1.1 WS14).

Run from a clean venv after installing scientific-authorization-contracts and the
AKTA wheel (no source checkout required beyond the contracts vendor install):

    python -m akta.wheel_smoke
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _ok(label: str) -> None:
    print(f"ok {label}")


def run_wheel_smoke() -> dict[str, Any]:
    """Exercise shared schemas through PF/PCS export in an installed environment."""
    from akta import AKTAContext, AKTAGate
    from akta.capability_envelope import authorization_covers, legacy_scope_to_envelope
    from akta.hash import hash_object
    from akta.requested_authorization import (
        build_requested_authorization_context,
        evaluate_authorization_containment,
    )
    from akta.scope_authorization_manifest import build_test_authorization_manifest
    from akta.scope_grant_verifier import verify_scope_grant_or_raise
    from akta.shared_contracts import (
        ENVELOPE_SCHEMA_NAME,
        ENVELOPE_VERSION,
        GRANT_STATUS_SCHEMA_NAME,
        GRANT_V2_SCHEMA_NAME,
        _contracts,
        authorization_envelope_schema_hash,
        load_conformance_cases,
        load_contract_schema,
    )
    from akta.trust_store import (
        build_trust_store,
        generate_test_keypair,
        sign_payload_hash_ed25519,
    )
    from adapters.pcs.export_artifact import export_pcs_bundle, validate_pcs_bundle
    from adapters.pf_core.export_obligation import build_pf_obligation, export_pf_obligation

    report: dict[str, Any] = {"steps": [], "passed": False}

    # 1) Shared schema loading
    for name in (ENVELOPE_SCHEMA_NAME, GRANT_V2_SCHEMA_NAME, GRANT_STATUS_SCHEMA_NAME):
        schema = load_contract_schema(name)
        assert isinstance(schema, dict) and "$schema" in schema, name
    report["steps"].append("shared_schema_loading")
    _ok("shared_schema_loading")

    narrowing = load_conformance_cases("narrowing")
    assert narrowing, "expected narrowing conformance vectors"
    case = narrowing[0]
    covers, comparator = authorization_covers(
        granted_envelope=case["outer"],
        requested_envelope=case["inner"],
    )
    assert comparator == "envelope"
    expect_narrower = case.get("expect") == "narrower"
    assert covers is expect_narrower, (case["name"], covers, case.get("expect"))
    decision = _contracts().compare_envelopes(case["inner"], case["outer"])
    if isinstance(decision, dict):
        assert decision.get("decision") == case["expect"], decision
    else:
        assert decision == case["expect"], decision
    report["steps"].append("conformance_narrowing")
    _ok("conformance_narrowing")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        issuer = generate_test_keypair(tmp_path / "issuer")
        status_keys = generate_test_keypair(tmp_path / "status")
        manifest_keys = generate_test_keypair(tmp_path / "manifest")

        issuer_store = build_trust_store(
            {
                "keys": {
                    issuer["public_key_ref"]: {
                        "public_key_pem": issuer["public_key_pem"],
                        "public_key_ref": issuer["public_key_ref"],
                        "status": "active",
                        "algorithm": "Ed25519",
                        "authorized_artifact_types": ["scope_grant"],
                    }
                },
                "revoked_key_ids": [],
                "default_artifact_types": ["scope_grant"],
            },
            base_dir=tmp_path,
            required_artifact_type="scope_grant",
        )
        status_store = build_trust_store(
            {
                "keys": {
                    status_keys["public_key_ref"]: {
                        "public_key_pem": status_keys["public_key_pem"],
                        "public_key_ref": status_keys["public_key_ref"],
                        "status": "active",
                        "algorithm": "Ed25519",
                        "authorized_artifact_types": ["scope_grant_status"],
                    }
                },
                "revoked_key_ids": [],
                "default_artifact_types": ["scope_grant_status"],
            },
            base_dir=tmp_path,
            required_artifact_type="scope_grant_status",
        )
        manifest_store = build_trust_store(
            {
                "keys": {
                    manifest_keys["public_key_ref"]: {
                        "public_key_pem": manifest_keys["public_key_pem"],
                        "public_key_ref": manifest_keys["public_key_ref"],
                        "status": "active",
                        "algorithm": "Ed25519",
                        "authorized_artifact_types": ["scope_authorization_manifest"],
                    }
                },
                "revoked_key_ids": [],
                "default_artifact_types": ["scope_authorization_manifest"],
            },
            base_dir=tmp_path,
            required_artifact_type="scope_authorization_manifest",
        )
        manifest = build_test_authorization_manifest(signer_keys=manifest_keys)
        trust_root = manifest["manifest_hash"]

        record = {"record_id": "rec-smoke", "summary": "wheel-smoke"}
        decision_body = {
            "decision_id": "dec-smoke",
            "admissibility": "review_required",
        }
        packet = {"packet_id": "pkt-smoke", "payload": "packet"}
        trigger = {"review_trigger_id": "trg-smoke", "packet_id": "pkt-smoke"}
        for obj, key in (
            (record, "record_hash"),
            (decision_body, "decision_hash"),
            (packet, "packet_hash"),
            (trigger, "review_trigger_hash"),
        ):
            obj[key] = hash_object({k: v for k, v in obj.items() if k != key})

        env = legacy_scope_to_envelope(
            approved_scope="protocol_draft",
            allowed_tools=["protocol_editor.draft_change"],
            blocked_tools=["robot_queue.submit"],
            target={"type": "protocol", "protocol_id": "protocol-v3"},
            environment={"tenant_id": "tenant-a"},
            cardinality={"mode": "single", "maximum_uses": 1, "maximum_items": 1},
            constraints={"protocol_version": "protocol-v3"},
        )
        grant: dict[str, Any] = {
            "grant_id": "SCOPE-GRANT-WHEEL-SMOKE",
            "grant_version": "2.0.0",
            "created_at": "2026-01-01T00:00:00Z",
            "authorization": {
                "approved_scope": "protocol_draft",
                "allowed_tools": list(env["allowed_tools"]),
                "blocked_tools": list(env["blocked_tools"]),
                "authorization_envelope": env,
            },
            "authorization_schema_version": ENVELOPE_VERSION,
            "authorization_schema_hash": authorization_envelope_schema_hash(),
            "issuer": {
                "issuer_identity": "scope-test",
                "issuer_key_id": issuer["public_key_ref"],
            },
            "source": {
                "packet_id": packet["packet_id"],
                "packet_hash": packet["packet_hash"],
                "decision_id": decision_body["decision_id"],
                "decision_hash": decision_body["decision_hash"],
                "akta_record_id": record["record_id"],
                "akta_record_hash": record["record_hash"],
                "review_trigger_id": trigger["review_trigger_id"],
                "review_trigger_hash": trigger["review_trigger_hash"],
            },
            "provenance": {"scope_trust_root_hash": trust_root},
            "constraints": {"single_use": True, "tenant_id": "tenant-a"},
            "expiration": {
                "absolute_expiration": "2030-01-01T00:00:00Z",
                "expires_after": [],
            },
            "signature_algorithm": "Ed25519",
        }
        grant = _contracts().attach_hash(grant, "grant_hash")
        grant["signed_payload_hash"] = grant["grant_hash"]
        priv = Path(issuer["private_key_path"]).read_bytes()
        grant["grant_signature"] = sign_payload_hash_ed25519(priv, grant["grant_hash"])

        status = {
            "grant_id": grant["grant_id"],
            "status": "active",
            "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "cardinality_remaining": 1,
            "grant_hash": grant["grant_hash"],
            "scope_trust_root_hash": trust_root,
            "tenant_id": "tenant-a",
            "ledger_sequence": 1,
            "authorization_schema_version": ENVELOPE_VERSION,
            "authorization_schema_hash": authorization_envelope_schema_hash(),
            "issuer": {
                "issuer_identity": "scope-status",
                "issuer_key_id": status_keys["public_key_ref"],
            },
        }
        status_body = {
            k: v
            for k, v in status.items()
            if k
            not in {
                "attestation_hash",
                "attestation_signature",
                "signed_payload_hash",
            }
        }
        status["attestation_hash"] = hash_object(status_body)
        status["signed_payload_hash"] = status["attestation_hash"]
        status_priv = Path(status_keys["private_key_path"]).read_bytes()
        status["attestation_signature"] = sign_payload_hash_ed25519(
            status_priv, status["attestation_hash"]
        )

        # 2–4) Grant auth + issuer signature + status attestation
        verified = verify_scope_grant_or_raise(
            grant,
            mode="pilot",
            trust_store=issuer_store,
            status_trust_store=status_store,
            authorization_manifest=manifest,
            manifest_trust_store=manifest_store,
            ledger_status=status,
            source_artifacts={
                "record": record,
                "decision": decision_body,
                "packet": packet,
                "review_trigger": trigger,
            },
        )
        assert verified.ok, verified.errors
        report["steps"].append("grant_authentication")
        report["steps"].append("issuer_signature_verification")
        report["steps"].append("status_attestation")
        _ok("grant_auth+issuer_sig+status")

        # 5–6) Requested envelope + containment
        requested = build_requested_authorization_context(
            requested_tool="protocol_editor.draft_change",
            action_class="A5_protocol_modification",
            context={"protocol_version": "protocol-v3", "tenant_id": "tenant-a"},
            constraints_overrides={"protocol_version": "protocol-v3"},
            target_overrides={"type": "protocol", "protocol_id": "protocol-v3"},
            environment_overrides={"tenant_id": "tenant-a"},
        )
        containment = evaluate_authorization_containment(
            granted_envelope=env,
            requested=requested,
            ledger_status=status,
        )
        assert containment.covers, containment.errors
        report["steps"].append("requested_envelope_construction")
        report["steps"].append("full_containment_check")
        _ok("requested_envelope+containment")

        # 7) Evidence-layer preservation (module invariant + optional gate path)
        from akta.evidence_independence import check_evidence_independence

        independence = check_evidence_independence(
            scope_grant=grant,
            pre_layers={
                "evidence": {
                    "decision": "blocked",
                    "reason": "weak evidence block",
                }
            },
            post_decision="allowed",
            post_reason="cleared by grant",
        )
        assert not independence.ok
        report["steps"].append("evidence_layer_preservation")
        _ok("evidence_layer_preservation")

        policy_candidates = [
            Path(__file__).resolve().parent.parent / "policy",
            Path.cwd() / "policy",
        ]
        policy_dir = next((p for p in policy_candidates if p.is_dir()), None)
        overlays_dir = None
        if policy_dir is not None:
            overlays_dir = policy_dir.parent / "overlays"
            if not overlays_dir.is_dir():
                overlays_dir = None

        if policy_dir is not None and overlays_dir is not None:
            gate = AKTAGate.from_policy_dir(policy_dir, overlays_dir=overlays_dir)
            prior = {
                "decision": {"admissibility": "review_required"},
                "classification": {
                    "evidence_state": "E4_internally_consistent_evidence"
                },
                "scientific_context": {"protocol_version": "protocol-v3"},
            }
            gate_decision = gate.evaluate_with_grant(
                ai_output={"summary": "Draft protocol-v3 change."},
                requested_tool="protocol_editor.draft_change",
                requested_action="draft",
                context=AKTAContext.from_dict(
                    {
                        "evidence_state": "E4_internally_consistent_evidence",
                        "protocol_version": "protocol-v3",
                        "tenant_id": "tenant-a",
                    }
                ),
                deployment_profile="P4_protocol_drafting_assistant",
                domain_overlay="generic_lab_v0",
                scope_grant=grant,
                record=prior,
                trigger=trigger,
                verification_mode="pilot",
                trust_store=issuer_store,
                ledger_status=status,
                authorization_manifest=manifest,
                source_artifacts={
                    "record": record,
                    "decision": decision_body,
                    "packet": packet,
                    "review_trigger": trigger,
                },
                action_class="A5_protocol_modification",
                validate_output=False,
                status_trust_store=status_store,
                manifest_trust_store=manifest_store,
            )
            decision_dict = gate_decision.to_dict()
            gate_record = gate_decision.to_record(
                ai_output={"summary": "Draft protocol-v3 change."},
                context={
                    "pf_core_obligation_ref": "PF-OBL-SMOKE",
                    "pcs_artifact_ref": "PCS-SMOKE",
                },
            )
        else:
            from akta.records import AKTADecision

            decision_dict = {
                "decision_id": "AKTA-DEC-SMOKE",
                "timestamp": "2026-01-01T00:00:00Z",
                "deployment_profile": "P4_protocol_drafting_assistant",
                "requested_action": "draft",
                "requested_tool": "protocol_editor.draft_change",
                "scientific_action_type": "A5_protocol_modification",
                "responsibility_level": "R4_methodological_modification",
                "evidence_state": "E4_internally_consistent_evidence",
                "validation_status": "V3_preliminary_experimental_support",
                "verification_status": "UNVERIFIED",
                "admissibility": "draft_only",
                "decision_reason": "wheel smoke",
                "blocked_tools": ["robot_queue.submit"],
                "allowed_tools": ["protocol_editor.draft_change"],
                "next_admissible_steps": [],
                "record_required": True,
                "review_required": False,
                "authorization_required": False,
                "policy_version": "1.1.0",
                "policy_hash": "sha256:" + ("a" * 64),
                "tool_registry_hash": "sha256:" + ("b" * 64),
            }
            gate_decision = AKTADecision(decision_dict)
            gate_record = gate_decision.to_record(
                ai_output={"summary": "Draft protocol-v3 change."},
                context={
                    "pf_core_obligation_ref": "PF-OBL-SMOKE",
                    "pcs_artifact_ref": "PCS-SMOKE",
                },
            )
            decision_dict = gate_decision.to_dict()

        # 8–9) PF + PCS export
        record_dict = gate_record.to_dict()
        obligation = build_pf_obligation(
            record_dict, decision_id=decision_dict.get("decision_id")
        )
        assert obligation.get("obligation_id")
        pf_path = export_pf_obligation(
            gate_record,
            tmp_path / "pf",
            decision_id=decision_dict.get("decision_id"),
        )
        assert Path(pf_path).is_file()
        report["steps"].append("pf_export")
        _ok("pf_export")

        pcs_dir = tmp_path / "pcs"
        export_pcs_bundle(
            gate_record,
            pcs_dir,
            decision=decision_dict,
            scope_grant=grant,
            pf_obligation=obligation,
            validate=True,
        )
        validate_pcs_bundle(pcs_dir)
        report["steps"].append("pcs_export")
        _ok("pcs_export")

    report["passed"] = True
    report["steps"] = sorted(set(report["steps"]))
    print(json.dumps({"passed": True, "steps": report["steps"]}, indent=2))
    return report


def main() -> int:
    try:
        run_wheel_smoke()
    except Exception as exc:
        print(json.dumps({"passed": False, "error": str(exc)}, indent=2))
        raise SystemExit(1) from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
