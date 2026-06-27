"""Example MCP wrapper usage."""

from __future__ import annotations

import json
from pathlib import Path

from adapters.mcp.wrapper import AKTAMCPWrapper

ROOT = Path(__file__).resolve().parents[3]


def main() -> None:
    wrapper = AKTAMCPWrapper(str(ROOT / "policy"), str(ROOT / "overlays"))
    print(json.dumps(wrapper.tool_spec(), indent=2))
    result = wrapper.call({
        "ai_output": {"summary": "Prioritize batch 1."},
        "requested_tool": "lab_scheduler.prioritize",
        "requested_action": "prioritize_batch",
        "deployment_profile": "P2_analysis_assistant",
        "domain_overlay": "generic_lab_v0",
        "context": {"evidence_state": "E2_preliminary_signal"},
    })
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
