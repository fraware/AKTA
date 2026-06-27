"""Example LangGraph-style middleware gating."""

from __future__ import annotations

from pathlib import Path

from adapters.langgraph.middleware import AKTALangGraphMiddleware

ROOT = Path(__file__).resolve().parents[3]


def mock_lab_scheduler_prioritize(batch: str) -> str:
    return f"Prioritized {batch}"


def main() -> None:
    middleware = AKTALangGraphMiddleware(
        str(ROOT / "policy"),
        str(ROOT / "overlays"),
        deployment_profile="P2_analysis_assistant",
        domain_overlay="generic_lab_v0",
    )
    gated = middleware.wrap_tool(mock_lab_scheduler_prioritize, "lab_scheduler.prioritize")
    try:
        gated("batch_B", ai_output={"summary": "Prioritize batch B."}, context={"evidence_state": "E2_preliminary_signal"})
        print("ERROR: tool should have been blocked")
    except PermissionError as exc:
        print(f"Expected block: {exc}")


if __name__ == "__main__":
    main()
