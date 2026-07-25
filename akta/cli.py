"""AKTA CLI entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from akta import __version__
from akta.cards import validate_card_file
from akta.context import AKTAContext
from akta.gate import AKTAGate
from akta.records import AKTADecision, AKTARecord, validate_against_schema


def _load_json(path: str) -> dict | list | str:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def cmd_gate(args: argparse.Namespace) -> int:
    ai_output = _load_json(args.output) if args.output else args.ai_text or ""
    context_data = _load_json(args.context) if args.context else {}
    context = AKTAContext.from_dict(context_data if isinstance(context_data, dict) else {})

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
        pilot_mode=getattr(args, "mode", None),
    )
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    decision.save(out_path)
    payload = decision.to_dict()
    print(json.dumps(payload, indent=2))
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
    decision = AKTADecision.from_file(args.decision).to_dict() if args.decision else None
    export_pcs_bundle(record, args.out, decision=decision, validate=args.validate)
    print(f"PCS artifact bundle exported to {args.out}")
    return 0


def cmd_export_pf(args: argparse.Namespace) -> int:
    from adapters.pf_core.export_obligation import export_pf_obligation

    record = AKTARecord.from_file(args.record)
    decision_id = None
    if args.decision:
        decision_id = AKTADecision.from_file(args.decision).to_dict().get("decision_id")
    path = export_pf_obligation(record, args.out, validate=args.validate, decision_id=decision_id)
    print(f"PF-Core obligation exported to {path}")
    return 0


def cmd_review_trigger_export(args: argparse.Namespace) -> int:
    decision = AKTADecision.from_file(args.decision)
    d = decision.to_dict()
    trigger = d.get("review_trigger")
    if not trigger:
        print("Decision has no review_trigger (admissibility may not require review)", file=sys.stderr)
        return 1
    validate_against_schema(trigger, "review_trigger.schema.json")
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(trigger, indent=2), encoding="utf-8")
    print(json.dumps(trigger, indent=2))
    return 0


def cmd_migrate_legacy_grant(args: argparse.Namespace) -> int:
    """Explicit legacy → scope-grant-v2 migration (AKTA 1.1 WS4)."""
    from akta.scope_grant_verifier import migrate_legacy_grant_to_v2

    raw = _load_json(args.grant)
    if not isinstance(raw, dict):
        print("Grant file must contain a JSON object", file=sys.stderr)
        return 1
    migrated = migrate_legacy_grant_to_v2(raw, grant_version=args.grant_version)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(migrated, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "out": str(out_path), "grant_version": args.grant_version}))
    return 0


def cmd_validate_stack_profile(args: argparse.Namespace) -> int:
    from akta.stack_profile import validate_stack_profile

    result = validate_stack_profile(args.profile)
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


def cmd_reconstruct(args: argparse.Namespace) -> int:
    from akta.reconstruct import write_reconstruction_report

    report = write_reconstruction_report(
        args.release,
        args.out,
        require_bindings=not args.allow_missing_bindings,
    )
    print(json.dumps(report, indent=2))
    return 0 if report.get("ok") else 1


def cmd_link_outcome(args: argparse.Namespace) -> int:
    from akta.pilot_metrics import OutcomeMutationError, link_outcome_to_record

    record = _load_json(args.record)
    outcome_ref = _load_json(args.outcome_ref)
    if not isinstance(record, dict) or not isinstance(outcome_ref, dict):
        print("record and outcome-ref must be JSON objects", file=sys.stderr)
        return 1
    try:
        updated = link_outcome_to_record(record, outcome_ref)
    except OutcomeMutationError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 1
    out_path = Path(args.out) if args.out else Path(args.record)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(updated, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "out": str(out_path), "outcome_refs": len((updated.get("integrations") or {}).get("outcome_refs") or [])}))
    return 0


def cmd_export_pilot_metrics(args: argparse.Namespace) -> int:
    from akta.pilot_metrics import export_pilot_metrics, load_records_dir

    records = load_records_dir(args.records)
    comparisons = None
    if args.comparisons:
        raw = _load_json(args.comparisons)
        comparisons = raw if isinstance(raw, list) else [raw]
    metrics = export_pilot_metrics(records, shadow_comparisons=comparisons)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(metrics, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="akta",
        description=f"AKTA {__version__} — Open Scientific Action Protocol",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"AKTA {__version__}",
    )
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
    gate.add_argument(
        "--mode",
        help=(
            "Pilot mode (AS-05): retrospective_reconstruction | prospective_shadow | "
            "read_only_support | execution_adjacent | bounded_execution. "
            "Distinct from REST service deployment --mode. Default: omit for pre-AS-05 behavior."
        ),
    )
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
    pcs.add_argument("--decision", help="Optional full decision JSON for manifest")
    pcs.add_argument("--out", required=True)
    pcs.add_argument("--validate", action="store_true", help="Validate manifest against PCS schema")
    pcs.set_defaults(func=cmd_export_pcs)

    pf = export_sub.add_parser("pf", help="Export PF-Core obligation")
    pf.add_argument("--record", required=True)
    pf.add_argument("--decision", help="Optional decision JSON for decision_id")
    pf.add_argument("--out", required=True)
    pf.add_argument("--validate", action="store_true", help="Validate against PF obligation schema")
    pf.set_defaults(func=cmd_export_pf)

    rev = sub.add_parser("review-trigger", help="Review trigger operations")
    rev_sub = rev.add_subparsers(dest="review_command", required=True)
    rev_export = rev_sub.add_parser("export", help="Export review trigger from decision")
    rev_export.add_argument("--decision", required=True)
    rev_export.add_argument("--out", required=True)
    rev_export.set_defaults(func=cmd_review_trigger_export)

    migrate = sub.add_parser(
        "migrate-legacy-grant",
        help="Migrate a legacy SCOPE grant to scope-grant-v2 (explicit CLI only)",
    )
    migrate.add_argument("--grant", required=True, help="Legacy grant JSON path")
    migrate.add_argument("--out", required=True, help="Migrated grant JSON path")
    migrate.add_argument("--grant-version", default="2.0.0")
    migrate.set_defaults(func=cmd_migrate_legacy_grant)

    vsp = sub.add_parser(
        "validate-stack-profile",
        help="Validate a stack_profile.json against release pins (AS-02)",
    )
    vsp.add_argument("profile", help="Path to stack_profile.json")
    vsp.set_defaults(func=cmd_validate_stack_profile)

    recon = sub.add_parser(
        "reconstruct",
        help="Reconstruct/verify an action release bundle (AS-08)",
    )
    recon.add_argument(
        "--release",
        required=True,
        help="Path to action_release/ or pcs_bundle directory",
    )
    recon.add_argument("--out", required=True, help="Output reconstruction.json path")
    recon.add_argument(
        "--allow-missing-bindings",
        action="store_true",
        help="Do not fail when historical bundles omit bindings",
    )
    recon.set_defaults(func=cmd_reconstruct)

    link = sub.add_parser(
        "link-outcome",
        help="Append an outcome_ref to a record without mutating admissibility (AS-07)",
    )
    link.add_argument("--record", required=True, help="AKTA record JSON path")
    link.add_argument("--outcome-ref", required=True, help="outcome_ref JSON path")
    link.add_argument(
        "--out",
        help="Output path (default: overwrite --record)",
    )
    link.set_defaults(func=cmd_link_outcome)

    metrics = sub.add_parser(
        "export-pilot-metrics",
        help="Export privacy-preserving pilot metrics aggregates (AS-07)",
    )
    metrics.add_argument("--records", required=True, help="Directory or file of AKTA records")
    metrics.add_argument("--out", required=True, help="Output metrics.json path")
    metrics.add_argument(
        "--comparisons",
        help="Optional shadow comparison JSON (list or object)",
    )
    metrics.set_defaults(func=cmd_export_pilot_metrics)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
