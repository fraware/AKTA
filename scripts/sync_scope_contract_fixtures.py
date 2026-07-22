"""Sync AKTA SCOPE contract fixtures from a live SCOPE sibling checkout."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = ROOT / "tests" / "fixtures"
SCOPE_ORDER_FILE = "scope_scope_order.json"
SCOPE_NARROWING_FILE = "scope_valid_narrowing.json"

CANONICAL_NARROWING_PAIRS: list[dict[str, str]] = [
    {
        "requested_scope": "active_protocol_update",
        "granted_scope": "protocol_draft",
        "rationale": "Protocol owner may approve draft-only changes instead of active update",
    },
    {
        "requested_scope": "single_validation_plan",
        "granted_scope": "protocol_draft",
        "rationale": "Validation plan request narrowed to protocol draft only",
    },
    {
        "requested_scope": "single_run_queue_priority",
        "granted_scope": "single_validation_plan",
        "rationale": "Queue priority narrowed to validation planning",
    },
    {
        "requested_scope": "robot_queue_submission",
        "granted_scope": "single_run_queue_priority",
        "rationale": "Robot submission narrowed to queue prioritization only",
    },
]

AKTA_APPROVAL_SCOPES = frozenset({
    "protocol_draft",
    "active_protocol_update",
    "single_validation_plan",
    "single_validation_run_draft",
    "single_run_queue_priority",
    "robot_queue_submission",
    "execution_payload_preparation",
    "publication_claim",
    "scientific_memory_import",
})


def _resolve_scope_repo(explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit
    env = os.environ.get("SCOPE_REPO_PATH", "").strip()
    if env:
        return Path(env)
    sibling = ROOT.parent / "SCOPE"
    if sibling.is_dir():
        return sibling
    raise FileNotFoundError(
        "SCOPE repo not found; set SCOPE_REPO_PATH or pass --scope-repo"
    )


def _read_scope_core_version(scope_repo: Path) -> str:
    versions_path = scope_repo / "scope" / "integration_versions.py"
    if not versions_path.is_file():
        raise FileNotFoundError(f"Missing SCOPE integration_versions.py: {versions_path}")
    ns: dict[str, Any] = {}
    exec(versions_path.read_text(encoding="utf-8"), ns)
    core = ns.get("SCOPE_CORE_VERSION")
    if not core:
        raise ValueError("SCOPE_CORE_VERSION not defined in integration_versions.py")
    review = ns.get("AKTA_REVIEW_CONTRACT_VERSION", "")
    if review:
        suffix = str(review).removeprefix("scope-akta-review-")
        return f"akta-scope-contract-{suffix}"
    core_suffix = str(core).removeprefix("scope-core-")
    return f"akta-scope-contract-{core_suffix}"


def _read_scope_order(scope_repo: Path) -> list[str]:
    approval_path = scope_repo / "policy" / "approval_scopes.yaml"
    if not approval_path.is_file():
        raise FileNotFoundError(f"Missing SCOPE approval_scopes.yaml: {approval_path}")
    data = yaml.safe_load(approval_path.read_text(encoding="utf-8")) or {}
    hierarchy = data.get("hierarchy") or []
    order = [str(s) for s in hierarchy if str(s) in AKTA_APPROVAL_SCOPES]
    if not order:
        raise ValueError("No AKTA approval scopes found in SCOPE hierarchy")
    return order


def _validate_narrowing_against_order(
    order: list[str],
    pairs: list[dict[str, str]],
) -> None:
    rank = {scope: idx for idx, scope in enumerate(order)}
    for entry in pairs:
        requested = entry["requested_scope"]
        granted = entry["granted_scope"]
        if requested not in rank or granted not in rank:
            raise ValueError(
                f"Narrowing pair ({requested}, {granted}) references scope outside order"
            )
        if rank[granted] >= rank[requested]:
            raise ValueError(
                f"Narrowing pair ({requested}, {granted}) is not a strict narrowing"
            )


def build_fixtures(*, scope_repo: Path) -> tuple[dict[str, Any], dict[str, Any], str]:
    contract_version = _read_scope_core_version(scope_repo)
    scope_order = _read_scope_order(scope_repo)
    pairs = list(CANONICAL_NARROWING_PAIRS)
    _validate_narrowing_against_order(scope_order, pairs)

    versions_path = scope_repo / "scope" / "integration_versions.py"
    ns: dict[str, Any] = {}
    exec(versions_path.read_text(encoding="utf-8"), ns)
    source_core = str(ns.get("SCOPE_CORE_VERSION", "unknown"))

    order_fixture = {
        "contract_version": contract_version,
        "scope_order": scope_order,
        "source_scope_core": source_core,
    }
    narrowing_fixture = {
        "contract_version": contract_version,
        "valid_narrowing_pairs": pairs,
    }
    return order_fixture, narrowing_fixture, contract_version


def sync_fixtures(
    *,
    scope_repo: Path,
    fixtures_dir: Path = FIXTURES_DIR,
    dry_run: bool = False,
) -> dict[str, Any]:
    order_fixture, narrowing_fixture, contract_version = build_fixtures(scope_repo=scope_repo)
    report: dict[str, Any] = {
        "contract_version": contract_version,
        "scope_repo": str(scope_repo.resolve()),
        "updated": [],
        "unchanged": [],
    }

    for name, payload in (
        (SCOPE_ORDER_FILE, order_fixture),
        (SCOPE_NARROWING_FILE, narrowing_fixture),
    ):
        path = fixtures_dir / name
        existing: dict[str, Any] | None = None
        if path.is_file():
            existing = json.loads(path.read_text(encoding="utf-8"))
        if existing == payload:
            report["unchanged"].append(name)
            continue
        report["updated"].append(name)
        if not dry_run:
            fixtures_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync AKTA SCOPE contract fixtures from SCOPE repo")
    parser.add_argument("--scope-repo", type=Path, default=None, help="Path to SCOPE sibling repo")
    parser.add_argument(
        "--fixtures-dir",
        type=Path,
        default=FIXTURES_DIR,
        help="AKTA tests/fixtures directory",
    )
    parser.add_argument("--dry-run", action="store_true", help="Report drift without writing")
    args = parser.parse_args(argv)

    try:
        scope_repo = _resolve_scope_repo(args.scope_repo)
        report = sync_fixtures(
            scope_repo=scope_repo,
            fixtures_dir=args.fixtures_dir,
            dry_run=args.dry_run,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, indent=2))
        return 1

    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
