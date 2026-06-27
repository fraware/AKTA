"""AKTA CLI entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from akta.cards import validate_card_file
from akta.context import AKTAContext
from akta.gate import AKTAGate
from akta.records import AKTADecision, AKTARecord


def _load_json(path: str) -> dict | list | str:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def cmd_gate(args: argparse.Namespace) -> int:
    ai_output = _load_json(args.output) if args.output else args.ai_text or ""
    context_data = _load_json(args.context) if args.context else {}
    context = AKTAContext.from_dict(context_data)

    gate = AKTAGate.from_policy_dir(
        args.policy_dir,
        overlays_dir=args.overlays_dir,
        tool_registry_path=args.tool_registry,
    )
    decision = gate.evaluate(
        ai_output=ai_output,
        requested_tool=args.tool,
        requested_action=args.action or args.tool.split(".")[-1],
        context=context,
        deployment_profile=args.profile,
        domain_overlay=args.domain_overlay,
    )
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    decision.save(out_path)
    print(json.dumps(decision.to_dict(), indent=2))
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    decision = AKTADecision.from_file(args.decision)
    context = _load_json(args.context) if args.context else {}
    ai_output = _load_json(args.ai_output) if args.ai_output else None
    record = decision.to_record(ai_output=ai_output, context=context if isinstance(context, dict) else {})
    out_path = Path(args.out)
    record.save(out_path)
    print(json.dumps(record.to_dict(), indent=2))
    return 0


def cmd_card_validate(args: argparse.Namespace) -> int:
    card = validate_card_file(args.card)
    print(f"AKTA Card valid: {card.get('system_name', 'unknown')}")
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    from evals.run_scenarios import run_scenario_eval

    report = run_scenario_eval(
        scenarios_path=args.scenarios,
        expected_path=args.expected,
        policy_dir=args.policy_dir,
        overlays_dir=args.overlays_dir,
    )
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report.get("passed") else 1


def cmd_export_pcs(args: argparse.Namespace) -> int:
    from adapters.pcs.export_artifact import export_pcs_bundle

    record = AKTARecord.from_file(args.record)
    export_pcs_bundle(record, args.out)
    print(f"PCS artifact bundle exported to {args.out}")
    return 0


def cmd_export_pf(args: argparse.Namespace) -> int:
    from adapters.pf_core.export_obligation import export_pf_obligation

    record = AKTARecord.from_file(args.record)
    path = export_pf_obligation(record, args.out)
    print(f"PF-Core obligation exported to {path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="akta", description="AKTA v0.1 — Open Scientific Action Protocol")
    sub = parser.add_subparsers(dest="command", required=True)

    gate = sub.add_parser("gate", help="Evaluate scientific action admissibility")
    gate.add_argument("--output", help="AI output JSON file")
    gate.add_argument("--ai-text", help="AI output text (alternative to --output)")
    gate.add_argument("--tool", required=True, help="Requested tool name")
    gate.add_argument("--action", help="Requested action name")
    gate.add_argument("--profile", default="P2_analysis_assistant", help="Deployment profile")
    gate.add_argument("--context", help="Context JSON file")
    gate.add_argument("--domain-overlay", help="Domain overlay name")
    gate.add_argument("--policy-dir", default="policy", help="Policy directory")
    gate.add_argument("--overlays-dir", default="overlays", help="Overlays directory")
    gate.add_argument("--tool-registry", help="Tool registry YAML path")
    gate.add_argument("--out", required=True, help="Output decision JSON path")
    gate.set_defaults(func=cmd_gate)

    record = sub.add_parser("record", help="Generate AKTA Record from decision")
    record.add_argument("--decision", required=True, help="Decision JSON file")
    record.add_argument("--context", help="Optional context JSON")
    record.add_argument("--ai-output", help="Optional AI output JSON")
    record.add_argument("--out", required=True, help="Output record JSON path")
    record.set_defaults(func=cmd_record)

    card = sub.add_parser("card", help="AKTA Card operations")
    card_sub = card.add_subparsers(dest="card_command", required=True)
    validate = card_sub.add_parser("validate", help="Validate AKTA Card")
    validate.add_argument("card", help="AKTA Card JSON file")
    validate.set_defaults(func=cmd_card_validate)

    eval_cmd = sub.add_parser("eval", help="Run scenario evaluation")
    eval_cmd.add_argument("--scenarios", required=True, help="Scenarios JSONL file")
    eval_cmd.add_argument("--expected", required=True, help="Expected decisions JSONL file")
    eval_cmd.add_argument("--policy-dir", default="policy")
    eval_cmd.add_argument("--overlays-dir", default="overlays")
    eval_cmd.add_argument("--out", help="Report output path")
    eval_cmd.set_defaults(func=cmd_eval)

    export = sub.add_parser("export", help="Export adapters")
    export_sub = export.add_subparsers(dest="export_command", required=True)

    pcs = export_sub.add_parser("pcs", help="Export PCS artifact bundle")
    pcs.add_argument("--record", required=True)
    pcs.add_argument("--out", required=True)
    pcs.set_defaults(func=cmd_export_pcs)

    pf = export_sub.add_parser("pf", help="Export PF-Core obligation")
    pf.add_argument("--record", required=True)
    pf.add_argument("--out", required=True)
    pf.set_defaults(func=cmd_export_pf)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
