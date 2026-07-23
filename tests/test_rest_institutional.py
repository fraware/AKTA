"""P1-C institutional REST mode and tenant-bound artifact tests."""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

import pytest

from adapters.generic_rest.identity import (
    INSTITUTIONAL_SERVICE,
    authenticate_request,
    institutional_startup_errors,
)
from adapters.generic_rest.persistence import FileArtifactStore
from adapters.generic_rest.server import create_server

ROOT = Path(__file__).resolve().parent.parent


def _sha(token: str) -> str:
    return "sha256:" + hashlib.sha256(token.encode("utf-8")).hexdigest()


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


def test_institutional_startup_requires_controls() -> None:
    errors = institutional_startup_errors(
        mode=INSTITUTIONAL_SERVICE,
        identity_registry={"identities": {}},
        artifact_store_kind="memory",
        audit_ledger_kind="memory",
        trusted_proxy=False,
        policy_manifest_verified=False,
    )
    assert any("identity registry" in e for e in errors)
    assert any("artifact store" in e for e in errors)
    assert any("audit ledger" in e for e in errors)
    assert any("trusted proxy" in e for e in errors)
    assert any("policy manifest" in e for e in errors)


def test_file_artifact_store_tenant_binding(tmp_path: Path) -> None:
    store = FileArtifactStore(tmp_path / "artifacts")
    aid = store.put("decision", {"ok": True}, tenant_id="t1", caller_id="c1")
    assert store.get(aid, tenant_id="t2", caller_id="c1", role="evaluator") is None
    assert store.get(aid, tenant_id="t1", caller_id="c2", role="evaluator") is None
    got = store.get(aid, tenant_id="t1", caller_id="c1", role="evaluator")
    assert got is not None
    assert got["data"]["ok"] is True
    assert store.get(aid, tenant_id="t1", caller_id="c2", role="auditor") is not None


def test_institutional_create_server_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="institutional-service startup rejected"):
        create_server(
            "127.0.0.1",
            0,
            ROOT / "policy",
            ROOT / "overlays",
            service_mode=INSTITUTIONAL_SERVICE,
            data_dir=tmp_path,
        )


def test_institutional_server_with_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import urllib.error
    import urllib.request

    token = "institutional-caller-secret"
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

    # Bypass real policy crypto for unit test by stubbing verifier.
    monkeypatch.setattr(
        "adapters.generic_rest.server._verify_policy_manifest",
        lambda _p: True,
    )

    server = create_server(
        "127.0.0.1",
        0,
        ROOT / "policy",
        ROOT / "overlays",
        service_mode=INSTITUTIONAL_SERVICE,
        trusted_proxy=True,
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

        # Static API key equality must not authenticate institutional callers.
        req_bad = urllib.request.Request(
            f"{url}/v0/health",
            headers={"Authorization": "Bearer anything", "X-AKTA-Tenant": "lab-a"},
        )
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(req_bad)

        req = urllib.request.Request(
            f"{url}/v0/health",
            headers={
                "Authorization": f"Bearer {token}",
                "X-AKTA-Tenant": "lab-a",
            },
        )
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        assert data["service_mode"] == INSTITUTIONAL_SERVICE
        assert data["beta"] is True
    finally:
        server.shutdown()
