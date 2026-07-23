"""P1-C / WS13 institutional REST mode, OIDC, and store tests."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path

import pytest

from adapters.generic_rest.identity import (
    INSTITUTIONAL_SERVICE,
    PILOT_SERVICE,
    authenticate_oidc_request,
    authenticate_request,
    institutional_startup_errors,
    resolve_service_mode,
)
from adapters.generic_rest.persistence import (
    FileArtifactStore,
    SqliteArtifactStore,
    verify_artifact_integrity,
)
from adapters.generic_rest.server import create_server

ROOT = Path(__file__).resolve().parent.parent


def _sha(token: str) -> str:
    return "sha256:" + hashlib.sha256(token.encode("utf-8")).hexdigest()


def test_static_registry_aliases_to_pilot_service() -> None:
    assert resolve_service_mode("static-registry") == PILOT_SERVICE
    assert resolve_service_mode("pilot-service") == PILOT_SERVICE


def test_static_bearer_rejected_as_institutional_identity() -> None:
    identity = authenticate_request(
        mode=INSTITUTIONAL_SERVICE,
        bearer_or_key="shared-static-token",
        api_key="shared-static-token",
        service_tokens=frozenset(),
        identity_registry={"identities": {}},
        tenant_header="tenant-a",
    )
    assert identity is None


def test_institutional_startup_requires_oidc_and_postgres() -> None:
    errors = institutional_startup_errors(
        mode=INSTITUTIONAL_SERVICE,
        identity_registry={"identities": {}},
        artifact_store_kind="file",
        audit_ledger_kind="file",
        trusted_proxy=False,
        policy_manifest_verified=False,
        oidc_configured=False,
    )
    assert any("OIDC" in e for e in errors)
    assert any("PostgreSQL artifact" in e for e in errors)
    assert any("PostgreSQL audit" in e for e in errors)
    assert any("trusted proxy" in e for e in errors)
    assert any("policy manifest" in e for e in errors)


def test_pilot_startup_requires_registry_and_file_store() -> None:
    errors = institutional_startup_errors(
        mode=PILOT_SERVICE,
        identity_registry={"identities": {}},
        artifact_store_kind="memory",
        audit_ledger_kind="memory",
        trusted_proxy=False,
        policy_manifest_verified=False,
    )
    assert any("identity registry" in e for e in errors)
    assert any("artifact store" in e for e in errors)


def test_file_artifact_store_tenant_binding(tmp_path: Path) -> None:
    store = FileArtifactStore(tmp_path / "artifacts")
    aid = store.put("decision", {"ok": True}, tenant_id="t1", caller_id="c1")
    assert store.get(aid, tenant_id="t2", caller_id="c1", role="evaluator") is None
    assert store.get(aid, tenant_id="t1", caller_id="c2", role="evaluator") is None
    got = store.get(aid, tenant_id="t1", caller_id="c1", role="evaluator")
    assert got is not None
    assert got["data"]["ok"] is True
    assert got["artifact_hash"].startswith("sha256:")
    assert verify_artifact_integrity(got) == []
    assert store.get(aid, tenant_id="t1", caller_id="c2", role="auditor") is not None


def test_sqlite_fallback_store(tmp_path: Path) -> None:
    store = SqliteArtifactStore(tmp_path / "artifacts.sqlite")
    aid = store.put(
        "decision",
        {"policy": {"effective_policy_hash": "sha256:abc"}},
        tenant_id="t1",
        caller_id="c1",
        source_artifact_id=None,
    )
    got = store.get(aid, tenant_id="t1", caller_id="c1", role="evaluator")
    assert got is not None
    assert got["schema_version"]


def test_institutional_create_server_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="startup rejected|DATABASE_URL|PostgreSQL"):
        create_server(
            "127.0.0.1",
            0,
            ROOT / "policy",
            ROOT / "overlays",
            service_mode=INSTITUTIONAL_SERVICE,
            data_dir=tmp_path,
        )


def test_oidc_identity_from_claims() -> None:
    identity = authenticate_oidc_request(
        bearer_token=None,
        tenant_header="lab-a",
        oidc_claims={
            "sub": "user-1",
            "tenant_id": "lab-a",
            "role": "recorder",
            "iss": "https://issuer.example",
            "aud": "akta-rest",
            "exp": time.time() + 3600,
        },
    )
    assert identity is not None
    assert identity.verified
    assert identity.auth_method == "oidc"
    assert identity.tenant_id == "lab-a"
    assert "records" in identity.permissions


def test_pilot_server_with_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import urllib.error
    import urllib.request

    token = "pilot-caller-secret"
    registry = {
        "version": "akta-rest-identity-v1",
        "identities": {
            "svc-evaluator-1": {
                "tenant_id": "lab-a",
                "role": "evaluator",
                "status": "active",
                "credential_sha256": _sha(token),
                "permissions": [
                    "evaluate",
                    "export",
                    "read_own_artifacts",
                    "policy",
                ],
            }
        },
    }
    reg_path = tmp_path / "identities.json"
    reg_path.write_text(json.dumps(registry), encoding="utf-8")

    server = create_server(
        "127.0.0.1",
        0,
        ROOT / "policy",
        ROOT / "overlays",
        service_mode=PILOT_SERVICE,
        data_dir=tmp_path / "data",
        identity_registry_path=reg_path,
    )
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://{host}:{port}"
    try:
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(f"{url}/v0/health")
        assert exc.value.code == 401

        req = urllib.request.Request(
            f"{url}/v0/health",
            headers={
                "Authorization": f"Bearer {token}",
                "X-AKTA-Tenant": "lab-a",
            },
        )
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        assert data["service_mode"] == PILOT_SERVICE
        assert data["beta"] is True
    finally:
        server.shutdown()


def test_institutional_server_rejects_inline_decision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Institutional /records must not accept arbitrary decision bodies."""
    import urllib.error
    import urllib.request

    from adapters.generic_rest import persistence as persistence_mod
    from adapters.generic_rest.persistence import InMemoryArtifactStore, InMemoryAuditLedger

    monkeypatch.setenv("AKTA_OIDC_ISSUER", "https://issuer.example")
    monkeypatch.setenv("AKTA_OIDC_AUDIENCE", "akta-rest")
    monkeypatch.setenv("AKTA_REST_DATABASE_URL", "postgresql://ci:ci@localhost:5432/akta_test")
    monkeypatch.setattr(
        "adapters.generic_rest.server._verify_policy_manifest",
        lambda _p: True,
    )

    mem_artifacts = InMemoryArtifactStore()
    mem_audit = InMemoryAuditLedger()

    def _fake_stores(mode, *, data_dir, database_url=None):
        return mem_artifacts, mem_audit, "postgresql", "postgresql"

    monkeypatch.setattr(persistence_mod, "build_stores_for_mode", _fake_stores)
    monkeypatch.setattr(
        "adapters.generic_rest.server.build_stores_for_mode",
        _fake_stores,
    )
    monkeypatch.setattr(
        "adapters.generic_rest.identity.authenticate_oidc_request",
        lambda **kwargs: authenticate_oidc_request(
            bearer_token=None,
            tenant_header=kwargs.get("tenant_header"),
            oidc_claims={
                "sub": "oidc-user",
                "tenant_id": "lab-a",
                "role": "admin",
                "iss": "https://issuer.example",
                "aud": "akta-rest",
            },
        ),
    )

    server = create_server(
        "127.0.0.1",
        0,
        ROOT / "policy",
        ROOT / "overlays",
        service_mode=INSTITUTIONAL_SERVICE,
        trusted_proxy=True,
        data_dir=tmp_path / "data",
    )
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://{host}:{port}"
    try:
        req = urllib.request.Request(
            f"{url}/v0/records",
            data=json.dumps({"decision": {"admissibility": "allowed"}}).encode("utf-8"),
            headers={
                "Authorization": "Bearer fake-oidc",
                "X-AKTA-Tenant": "lab-a",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req)
        assert exc.value.code == 400
        body = json.loads(exc.value.read().decode("utf-8"))
        assert "institutional_mode_rejects_inline_decision" in (body.get("detail") or "")
    finally:
        server.shutdown()
