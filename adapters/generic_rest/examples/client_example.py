"""Example REST API client for AKTA generic REST server."""

from __future__ import annotations

import json
import urllib.error
import urllib.request


def post_evaluate(base_url: str = "http://127.0.0.1:8765") -> dict:
    payload = {
        "ai_output": {"summary": "Prioritize condition B based on preliminary signal."},
        "requested_tool": "lab_scheduler.prioritize",
        "requested_action": "prioritize_next_run",
        "deployment_profile": "P2_analysis_assistant",
        "domain_overlay": "generic_lab_v0",
        "context": {"evidence_state": "E2_preliminary_signal", "validation_status": "V0_unvalidated"},
    }
    req = urllib.request.Request(
        f"{base_url}/v0/evaluate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> None:
    try:
        result = post_evaluate()
        print(json.dumps(result, indent=2))
    except urllib.error.URLError as exc:
        print(f"Server not running: {exc}")
        print("Start with: python -m adapters.generic_rest.server")


if __name__ == "__main__":
    main()
