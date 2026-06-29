"""Tests for generic REST API server."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from adapters.generic_rest.server import create_server

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def server_url() -> str:
    import urllib.request

    server = create_server("127.0.0.1", 0, ROOT / "policy", ROOT / "overlays")
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://{host}:{port}"
    server.shutdown()


def _post(url: str, path: str, payload: dict) -> dict:
    import urllib.request

    req = urllib.request.Request(
        f"{url}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get(url: str, path: str) -> dict:
    import urllib.request

    with urllib.request.urlopen(f"{url}{path}") as resp:
        return json.loads(resp.read().decode("utf-8"))


def test_health(server_url: str) -> None:
    data = _get(server_url, "/v0/health")
    assert data["status"] == "ok"
    assert data["api_version"] == "v0.6"
    assert data["version"] == "0.8.1"


def test_policy(server_url: str) -> None:
    data = _get(server_url, "/v0/policy")
    assert data["policy_hash"].startswith("sha256:")
    assert "P7_fully_autonomous_scientific_operator" not in data["supported_profiles"]


def test_evaluate_blocked(server_url: str) -> None:
    data = _post(
        server_url,
        "/v0/evaluate",
        {
            "ai_output": {"summary": "Prioritize B."},
            "requested_tool": "lab_scheduler.prioritize",
            "requested_action": "prioritize_next_run",
            "deployment_profile": "P2_analysis_assistant",
            "domain_overlay": "generic_lab_v0",
            "context": {"evidence_state": "E2_preliminary_signal"},
        },
    )
    assert data["admissibility"] == "blocked"
    assert len(data["next_admissible_steps"]) > 0


def test_card_validate(server_url: str) -> None:
    card = json.loads((ROOT / "examples" / "akta_card.json").read_text(encoding="utf-8"))
    data = _post(server_url, "/v0/cards/validate", {"card": card})
    assert data["valid"] is True


def test_records_from_decision(server_url: str) -> None:
    decision = _post(
        server_url,
        "/v0/evaluate",
        {
            "ai_output": "Search literature.",
            "requested_tool": "literature_search.query",
            "requested_action": "search",
            "deployment_profile": "P1_literature_hypothesis_assistant",
            "context": {},
        },
    )
    record = _post(server_url, "/v0/records", {"decision": decision})
    assert record["record_type"] == "scientific_action_record"
    assert record["record_hash"].startswith("sha256:")


def test_export_pf_and_pcs(server_url: str) -> None:
    decision = _post(
        server_url,
        "/v0/evaluate",
        {
            "ai_output": {"summary": "Prioritize B."},
            "requested_tool": "lab_scheduler.prioritize",
            "requested_action": "prioritize_next_run",
            "deployment_profile": "P2_analysis_assistant",
            "domain_overlay": "generic_lab_v0",
            "context": {"evidence_state": "E2_preliminary_signal"},
        },
    )
    record = _post(server_url, "/v0/records", {"decision": decision})
    pf = _post(server_url, "/v0/export/pf", {"record": record})
    pcs = _post(server_url, "/v0/export/pcs", {"record": record})
    assert pf["exported"] is True
    assert pf["obligation"]["source"] == "AKTA"
    assert pcs["exported"] is True
    assert pcs["manifest"]["artifact_type"] == "akta_scientific_action_record"


def test_api_key_required_when_configured() -> None:
    import urllib.error
    import urllib.request

    server = create_server(
        "127.0.0.1",
        0,
        ROOT / "policy",
        ROOT / "overlays",
        api_key="secret-test-key",
    )
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://{host}:{port}"

    try:
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            _get(url, "/v0/health")
        assert exc_info.value.code == 401

        req = urllib.request.Request(
            f"{url}/v0/health",
            headers={"X-API-Key": "secret-test-key"},
        )
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        assert data["status"] == "ok"
    finally:
        server.shutdown()


def test_rate_limit_returns_429() -> None:
    import urllib.error

    server = create_server(
        "127.0.0.1",
        0,
        ROOT / "policy",
        ROOT / "overlays",
        rate_limit=2,
    )
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://{host}:{port}"

    try:
        _get(url, "/v0/health")
        _get(url, "/v0/health")
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            _get(url, "/v0/health")
        assert exc_info.value.code == 429
    finally:
        server.shutdown()
