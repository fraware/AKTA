"""Stdio MCP server exposing AKTA gate tools."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from akta.context import AKTAContext
from akta.gate import AKTAGate
from adapters.pcs.export_artifact import export_pcs_bundle
from adapters.pf_core.export_obligation import build_pf_obligation


TOOLS = {
    "akta_evaluate": {
        "description": "Evaluate scientific action admissibility through AKTA gate",
        "inputSchema": {
            "type": "object",
            "required": ["requested_tool"],
            "properties": {
                "requested_tool": {"type": "string"},
                "requested_action": {"type": "string"},
                "ai_output": {},
                "context": {"type": "object"},
                "deployment_profile": {"type": "string"},
                "domain_overlay": {"type": "string"},
            },
        },
    },
    "akta_evaluate_with_grant": {
        "description": "Re-gate with SCOPE grant or review decision (v0.6 closed-loop)",
        "inputSchema": {
            "type": "object",
            "required": ["requested_tool"],
            "properties": {
                "requested_tool": {"type": "string"},
                "requested_action": {"type": "string"},
                "ai_output": {},
                "context": {"type": "object"},
                "deployment_profile": {"type": "string"},
                "domain_overlay": {"type": "string"},
                "scope_grant": {"type": "object"},
                "review_decision": {"type": "object"},
            },
        },
    },
    "akta_export": {
        "description": "Export PF obligation and PCS bundle from AKTA decision/record",
        "inputSchema": {
            "type": "object",
            "required": ["decision"],
            "properties": {
                "decision": {"type": "object"},
                "record": {"type": "object"},
                "out_dir": {"type": "string"},
            },
        },
    },
}


class AKTAMCPServer:
    """Minimal JSON-RPC MCP server over stdio."""

    def __init__(self, policy_dir: str | Path = "policy", overlays_dir: str | Path = "overlays") -> None:
        self.gate = AKTAGate.from_policy_dir(policy_dir, overlays_dir=overlays_dir)

    def handle(self, message: dict[str, Any]) -> dict[str, Any]:
        method = message.get("method", "")
        req_id = message.get("id")
        if method == "initialize":
            return self._reply(req_id, {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}})
        if method == "tools/list":
            tool_list = [{"name": k, **v} for k, v in TOOLS.items()]
            return self._reply(req_id, {"tools": tool_list})
        if method == "tools/call":
            return self._call_tool(req_id, message.get("params", {}))
        return self._error(req_id, -32601, f"Method not found: {method}")

    def _tool_error(self, req_id: Any, code: str, message: str, *, detail: dict[str, Any] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": code, "message": message}
        if detail:
            payload["detail"] = detail
        return self._error(req_id, -32000, json.dumps(payload))

    def _call_tool(self, req_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name", "")
        args = params.get("arguments", {})
        try:
            if name == "akta_evaluate":
                if "requested_tool" not in args:
                    return self._tool_error(req_id, "missing_field", "requested_tool is required")
                decision = self.gate.evaluate(
                    ai_output=args.get("ai_output", ""),
                    requested_tool=args["requested_tool"],
                    requested_action=args.get("requested_action", args["requested_tool"]),
                    context=AKTAContext.from_dict(args.get("context", {})),
                    deployment_profile=args.get("deployment_profile", "P2_analysis_assistant"),
                    domain_overlay=args.get("domain_overlay"),
                )
                return self._reply(req_id, {"content": [{"type": "text", "text": json.dumps(decision.to_dict())}]})
            if name == "akta_evaluate_with_grant":
                if "requested_tool" not in args:
                    return self._tool_error(req_id, "missing_field", "requested_tool is required")
                decision = self.gate.evaluate_with_grant(
                    ai_output=args.get("ai_output", ""),
                    requested_tool=args["requested_tool"],
                    requested_action=args.get("requested_action", args["requested_tool"]),
                    context=AKTAContext.from_dict(args.get("context", {})),
                    deployment_profile=args.get("deployment_profile", "P2_analysis_assistant"),
                    domain_overlay=args.get("domain_overlay"),
                    scope_grant=args.get("scope_grant"),
                    review_decision=args.get("review_decision"),
                )
                return self._reply(req_id, {"content": [{"type": "text", "text": json.dumps(decision.to_dict())}]})
            if name == "akta_export":
                decision = args["decision"]
                record = args.get("record") or decision
                pf = build_pf_obligation(
                    record if "decision" in record else {
                        "decision": decision,
                        "record_id": decision.get("decision_id"),
                    }
                )
                return self._reply(req_id, {"content": [{"type": "text", "text": json.dumps({"pf_obligation": pf})}]})
            return self._tool_error(req_id, "unknown_tool", f"Unknown tool: {name}")
        except KeyError as exc:
            return self._tool_error(req_id, "missing_field", str(exc))
        except Exception as exc:
            return self._tool_error(req_id, "akta_error", str(exc), detail={"tool": name})

    def _reply(self, req_id: Any, result: dict[str, Any]) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    def _error(self, req_id: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message, "request_id": str(req_id)}}

    def serve_stdio(self) -> None:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            msg = json.loads(line)
            resp = self.handle(msg)
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


def main() -> int:
    server = AKTAMCPServer()
    server.serve_stdio()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
