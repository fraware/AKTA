"""Institutional wheel-install smoke path (AKTA 1.2 P0-13).

Run from a clean venv after installing scientific-authorization-contracts and the
AKTA wheel (no source checkout required beyond the contracts vendor install):

    python -m akta.wheel_smoke

Native SCOPE phase (steps 1–14) requires SCOPE installed / sibling checkout.
Set ``AKTA_REQUIRE_NATIVE_SCOPE=1`` to fail closed when siblings are absent
(release-gate). Unit CI may skip the native phase.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _ok(label: str) -> None:
    print(f"ok {label}")


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _require_native_scope() -> bool:
    return _env_truthy("AKTA_REQUIRE_NATIVE_SCOPE") or _env_truthy(
        "AKTA_RELEASE_GATE"
    )


def _resolve_scope_repo() -> Path | None:
    from akta.sibling_repos import discover_sibling

    return discover_sibling("SCOPE_REPO_PATH")


def run_native_scope_phase() -> dict[str, Any]:
    """Mandatory native SCOPE interop phase (plan P0-13 steps 1–14).

    Forbidden: inventing missing SCOPE source fields. Artifacts from SCOPE are
    passed unmodified into AKTA strict verification.
    """
    report: dict[str, Any] = {
        "phase": "native_scope",
        "steps": [],
        "passed": False,
        "skipped": False,
    }

    # Steps 1–3: contracts + SCOPE + AKTA must already be importable (wheels).
    try:
        import scientific_authorization_contracts as contracts
    except ImportError as exc:
        if _require_native_scope():
            raise RuntimeError(f"contracts wheel required for native phase: {exc}") from exc
        report["skipped"] = True
        report["skip_reason"] = f"contracts not importable: {exc}"
        return report

    report["steps"].append("install_contract_wheel")
    _ok("install_contract_wheel")

    scope_repo = _resolve_scope_repo()
    try:
        from scope import ScopeEngine
        from scope.scopes import envelope_for_scope
        from scope.signing import Ed25519Signer
        from scope.sqlite_ledger import SqliteScopeLedger
    except ImportError as exc:
        if _require_native_scope():
            raise RuntimeError(
                f"SCOPE wheel/package required for native phase: {exc}"
            ) from exc
        report["skipped"] = True
        report["skip_reason"] = f"SCOPE not importable: {exc}"
        return report

    report["steps"].append("install_scope_wheel")
    _ok("install_scope_wheel")

    import akta
    from akta.scope_interop import (
        reject_exhausted_use,
        strict_verify_grant,
        verify_action_containment,
        verify_evidence_independence,
        verify_status_attestation,
    )

    report["steps"].append("install_akta_wheel")
    _ok(f"install_akta_wheel ({akta.__version__})")

    policy_dir: Path | None = None
    examples_dir: Path | None = None
    if scope_repo is not None:
        policy_dir = scope_repo / "policy"
        examples_dir = scope_repo / "examples" / "protocol_change_review"
    if policy_dir is None or not policy_dir.is_dir():
        import scope as scope_pkg

        scope_root = Path(scope_pkg.__file__).resolve().parent.parent
        policy_dir = scope_root / "policy"
        examples_dir = scope_root / "examples" / "protocol_change_review"

    if not policy_dir.is_dir() or examples_dir is None or not examples_dir.is_dir():
        if _require_native_scope():
            raise RuntimeError(
                "SCOPE policy/ and examples/protocol_change_review required for native phase"
            )
        report["skipped"] = True
        report["skip_reason"] = "SCOPE policy/examples missing"
        return report

    with tempfile.TemporaryDirectory(
        prefix="akta-native-scope-", ignore_cleanup_errors=True
    ) as tmp:
        tmp_path = Path(tmp)

        # Step 4: Generate reviewer / issuer / status / manifest keys
        reviewer_key, reviewer_pub = tmp_path / "reviewer.pem", tmp_path / "reviewer.pub"
        issuer_key, issuer_pub = tmp_path / "issuer.pem", tmp_path / "issuer.pub"
        Ed25519Signer.generate_keypair(reviewer_key, reviewer_pub)
        Ed25519Signer.generate_keypair(issuer_key, issuer_pub)
        issuer = Ed25519Signer(issuer_key)
        report["steps"].append("generate_keys")
        _ok("generate_keys")

        ledger = SqliteScopeLedger(tmp_path / "ledger.sqlite", tenant_id="lab-a")
        engine = ScopeEngine.from_policy_dir(
            policy_dir,
            ledger=ledger,
            tenant_id="lab-a",
            require_manifest_signature=False,
            issuer_verifier=issuer,
            require_production_deps=False,
        )
        engine._issuer_signer = issuer  # type: ignore[attr-defined]

        # Step 5: Generate AKTA initial artifacts (use SCOPE example Record+Trigger)
        record_path = examples_dir / "akta_record.json"
        trigger_path = examples_dir / "review_trigger.json"
        report["steps"].append("generate_akta_artifacts")
        _ok("generate_akta_artifacts")

        # Step 6: Call real SCOPE packet + grant APIs
        packet = engine.create_packet(record_path, trigger_path)
        assert packet.get("packet_id") and packet.get("packet_hash")
        report["steps"].append("scope_packet_api")
        _ok("scope_packet_api")

        envelope = envelope_for_scope("protocol_draft", engine.policy).to_dict()
        # Bound uses so step 14 can verify exhaustion rejection.
        cardinality = dict(envelope.get("cardinality") or {})
        cardinality.update({"mode": "bounded", "maximum_uses": 2, "maximum_items": 1})
        envelope["cardinality"] = cardinality
        decision = engine.submit_decision(
            packet,
            {"reviewer_id": "r1", "role": "protocol_owner"},
            {
                "type": "approve_narrower_scope",
                "approved_scope": "protocol_draft",
                "approved_authorization_envelope": envelope,
                "rationale": "akta native wheel smoke",
            },
        )
        decision = engine.sign_decision(decision, Ed25519Signer(reviewer_key))
        grant = engine.issue_grant(packet, decision, issuer_signer=issuer)
        assert grant.get("grant_id") and grant.get("grant_hash")
        # Forbidden: inventing missing SCOPE source fields — use as issued.
        report["steps"].append("scope_grant_api")
        _ok("scope_grant_api")

        # Step 7: Obtain native signed manifest (from engine / grant provenance)
        manifest = getattr(engine, "authorization_manifest", None)
        if isinstance(manifest, dict) and manifest.get("manifest_hash"):
            report["steps"].append("native_signed_manifest")
            _ok("native_signed_manifest")
        else:
            prov = grant.get("provenance") or {}
            if prov.get("authorization_manifest_hash") or prov.get(
                "verified_policy_manifest_hash"
            ):
                report["steps"].append("native_signed_manifest")
                _ok("native_signed_manifest (provenance hash)")
            elif _require_native_scope():
                raise RuntimeError("native signed authorization manifest missing")
            else:
                report["steps"].append("native_signed_manifest_unavailable")
                _ok("native_signed_manifest_unavailable")

        # Step 8: Obtain native signed status
        attestation = engine.issue_grant_status_attestation(
            grant["grant_id"], signer=issuer, audience="akta"
        )
        assert attestation.get("grant_hash") == grant.get("grant_hash")
        report["steps"].append("native_signed_status")
        _ok("native_signed_status")

        # Step 9: Pass artifacts unmodified into AKTA strict verification
        assert strict_verify_grant(grant) is True
        assert verify_status_attestation(attestation, grant) is True
        report["steps"].append("akta_strict_verify")
        _ok("akta_strict_verify")

        # Step 10: Build requested action from AKTA context only
        sci = packet.get("scientific_context") or {}
        auth_env = (grant.get("authorization") or {}).get("authorization_envelope") or {}
        responsibility = (
            auth_env.get("responsibility_ceiling")
            or packet.get("responsibility_level")
            or (packet.get("review_request") or {}).get("responsibility_level")
        )
        if not responsibility:
            raise RuntimeError(
                "native phase missing responsibility_level on grant/packet "
                "(refusing to invent)"
            )
        action = {
            "requested_tool": "protocol_editor.draft_change",
            "family": "protocol",
            "operation": "draft",
            "protocol_version": sci.get("protocol_version"),
            "protocol_id": sci.get("protocol_id"),
            "evidence_state": sci.get("evidence_state") or "recorded",
            "responsibility_level": responsibility,
            "target": {
                "type": "protocol",
                "protocol_id": sci.get("protocol_id"),
                "protocol_version": sci.get("protocol_version"),
            },
            "environment": {
                "tenant_id": sci.get("tenant_id") or "lab-a",
                "project_id": sci.get("project_id"),
                "domain_overlay": sci.get("domain_overlay"),
            },
            "item_count": 1,
            "tenant_id": sci.get("tenant_id") or "lab-a",
            "project_id": sci.get("project_id"),
        }
        report["steps"].append("requested_action_from_akta")
        _ok("requested_action_from_akta")

        # Step 11: Evaluate containment
        assert verify_action_containment(grant, action) is True
        report["steps"].append("evaluate_containment")
        _ok("evaluate_containment")

        # Step 12: Re-run AKTA admissibility / evidence independence
        assert verify_evidence_independence(grant, packet, decision) is True
        report["steps"].append("admissibility_evidence_independence")
        _ok("admissibility_evidence_independence")

        # Step 13: Consume through SCOPE
        consumed = engine.authorize_and_consume(
            grant["grant_id"], action, "wheel-smoke-native-1"
        )
        if not getattr(consumed, "allowed", False):
            raise RuntimeError(f"SCOPE consume failed: {consumed}")
        report["steps"].append("consume_through_scope")
        _ok("consume_through_scope")

        # Step 14: Verify updated status through AKTA
        attestation2 = engine.issue_grant_status_attestation(
            grant["grant_id"], signer=issuer, audience="akta"
        )
        assert verify_status_attestation(attestation2, grant) is True
        status = engine.grant_status(grant["grant_id"])
        remaining = status.get("remaining_uses", status.get("cardinality_remaining"))
        n = 2
        while remaining is not None and int(remaining) > 0:
            r = engine.authorize_and_consume(
                grant["grant_id"], action, f"wheel-smoke-native-extra-{n}"
            )
            if not getattr(r, "allowed", False):
                break
            status = engine.grant_status(grant["grant_id"])
            remaining = status.get("remaining_uses", status.get("cardinality_remaining"))
            n += 1
        final_status = engine.grant_status(grant["grant_id"])
        assert reject_exhausted_use(grant, final_status, action) is True
        report["steps"].append("verify_updated_status")
        _ok("verify_updated_status")

        # Release SQLite handles before tempdir cleanup (Windows).
        close = getattr(ledger, "close", None)
        if callable(close):
            close()
        elif hasattr(ledger, "_conn"):
            try:
                ledger._conn.close()
            except Exception:
                pass

    report["passed"] = True
    report["contracts_version"] = getattr(contracts, "package_version", lambda: "?")()
    print(
        json.dumps(
            {
                "native_scope": {
                    "passed": True,
                    "steps": report["steps"],
                    "contracts_version": report.get("contracts_version"),
                }
            },
            indent=2,
        )
    )
    return report


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

        requested = build_requested_authorization_context(
            requested_tool="protocol_editor.draft_change",
            action_class="A5_protocol_modification",
            context={
                "protocol_version": "protocol-v3",
                "tenant_id": "tenant-a",
                "project_id": "project-123",
            },
            constraints_overrides={},
            target_overrides={"type": "protocol", "protocol_id": "protocol-v3"},
            environment_overrides={
                "tenant_id": "tenant-a",
                "project_id": "project-123",
            },
            responsibility_level="R3_recommendation",
            item_count=1,
            mode="unit",
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
            auth_prov = decision_dict.get("authorization_provenance") or {}
            if auth_prov.get("evidence_layer"):
                assert auth_prov["evidence_layer"].get("layer") == "evidence_layer"
            if auth_prov.get("final_composition"):
                assert auth_prov["final_composition"].get("layer") == "final_composition"
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
                "policy_version": "1.2.0",
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

    # Native SCOPE phase (P0-13); skip only when siblings absent and not required.
    native = run_native_scope_phase()
    report["native_scope"] = native
    if native.get("skipped"):
        report["steps"].append("native_scope_skipped")
        _ok(f"native_scope_skipped ({native.get('skip_reason')})")
    else:
        assert native.get("passed"), native
        report["steps"].extend(f"native:{s}" for s in native.get("steps") or [])

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
