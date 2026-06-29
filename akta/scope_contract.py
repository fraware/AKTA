"""SCOPE-compatible contract helpers for AKTA review triggers and packets.

When the SCOPE repository is not available locally, these helpers mirror the
field extraction and approval_scopes validation that SCOPE performs on AKTA
review triggers and review packets.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from akta.scope_mapping import VALID_REQUESTED_SCOPES

SCOPE_APPROVAL_SCOPES = frozenset(VALID_REQUESTED_SCOPES)

_AKTA_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_FIXTURES_DIR = _AKTA_ROOT / "tests" / "fixtures"

# v0.2 review_scope vocabulary -> v0.3 requested_scope (compat for SCOPE simulator).
LEGACY_REVIEW_SCOPE_MAP: dict[str, str] = {
    "draft_only": "protocol_draft",
    "protocol_draft": "protocol_draft",
    "active_protocol": "active_protocol_update",
    "active_protocol_update": "active_protocol_update",
    "run_plan": "single_validation_plan",
    "single_validation_plan": "single_validation_plan",
    "validation_draft": "single_validation_run_draft",
    "single_validation_run_draft": "single_validation_run_draft",
    "queue_prioritization": "single_run_queue_priority",
    "single_run_queue_priority": "single_run_queue_priority",
    "robot_submission": "robot_queue_submission",
    "robot_queue_submission": "robot_queue_submission",
    "execution_preparation": "execution_payload_preparation",
    "execution_payload_preparation": "execution_payload_preparation",
    "publication_claim": "publication_claim",
    "scientific_memory_import": "scientific_memory_import",
}


def _fixture_candidates(basename: str) -> list[Path]:
    """Resolve fixture path: SCOPE repo (live contract) then AKTA tests/fixtures."""
    candidates: list[Path] = []
    scope_repo = os.environ.get("SCOPE_REPO_PATH", "").strip()
    if scope_repo:
        root = Path(scope_repo)
        for sub in ("schemas", "tests/fixtures", "fixtures"):
            candidates.append(root / sub / basename)
            candidates.append(root / sub / basename.replace(".json", ".fixture.json"))
    candidates.append(_DEFAULT_FIXTURES_DIR / basename)
    return candidates


def _load_fixture_json(basename: str) -> dict[str, Any]:
    for path in _fixture_candidates(basename):
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    raise FileNotFoundError(
        f"SCOPE contract fixture not found: {basename} "
        f"(checked SCOPE_REPO_PATH and {_DEFAULT_FIXTURES_DIR})"
    )


@lru_cache(maxsize=1)
def load_scope_order() -> tuple[str, ...]:
    """Ordered SCOPE approval scopes (narrowest to broadest) from fixture contract."""
    data = _load_fixture_json("scope_scope_order.json")
    order = data.get("scope_order")
    if not isinstance(order, list) or not order:
        raise ValueError("scope_scope_order.json missing non-empty scope_order list")
    return tuple(str(s) for s in order)


@lru_cache(maxsize=1)
def load_valid_narrowing_pairs() -> frozenset[tuple[str, str]]:
    """Valid (requested_scope, granted_scope) narrowing pairs from fixture contract."""
    data = _load_fixture_json("scope_valid_narrowing.json")
    pairs = data.get("valid_narrowing_pairs")
    if not isinstance(pairs, list):
        raise ValueError("scope_valid_narrowing.json missing valid_narrowing_pairs list")
    result: set[tuple[str, str]] = set()
    for entry in pairs:
        if not isinstance(entry, dict):
            continue
        requested = entry.get("requested_scope")
        granted = entry.get("granted_scope")
        if requested and granted:
            result.add((str(requested), str(granted)))
    return frozenset(result)


def scope_rank(scope: str) -> int:
    """Return 1-based rank from fixture scope order; unknown scopes rank last."""
    try:
        return load_scope_order().index(scope) + 1
    except ValueError:
        return 99


def is_valid_narrowing_grant(*, granted_scope: str, requested_scope: str) -> bool:
    """True when granted scope equals or validly narrows requested scope per fixture."""
    if granted_scope == requested_scope:
        return True
    return (requested_scope, granted_scope) in load_valid_narrowing_pairs()


def resolve_trigger_requested_scope(trigger: dict[str, Any]) -> str | None:
    """Resolve requested_scope from v0.3 field or legacy review_scope fallback."""
    scope = trigger.get("requested_scope")
    if scope in SCOPE_APPROVAL_SCOPES:
        return scope
    legacy = trigger.get("review_scope")
    if legacy:
        mapped = LEGACY_REVIEW_SCOPE_MAP.get(str(legacy))
        if mapped in SCOPE_APPROVAL_SCOPES:
            return mapped
    return None


def extract_scope_fields(trigger: dict[str, Any]) -> dict[str, Any]:
    """Extract SCOPE-consumed fields from an AKTA review trigger."""
    return {
        "review_trigger_id": trigger.get("review_trigger_id"),
        "review_trigger_version": trigger.get("review_trigger_version"),
        "akta_decision_id": trigger.get("akta_decision_id") or trigger.get("decision_id"),
        "akta_record_id": trigger.get("akta_record_id") or trigger.get("source_record_id"),
        "requested_scope": resolve_trigger_requested_scope(trigger),
        "review_route": trigger.get("review_route"),
        "required_review_role": trigger.get("required_review_role"),
        "blocked_tools": list(trigger.get("blocked_tools") or []),
        "allowed_next_steps": list(trigger.get("allowed_next_steps") or []),
        "policy_hash": trigger.get("policy_hash"),
        "tool_registry_hash": trigger.get("tool_registry_hash"),
    }


def validate_requested_scope(trigger: dict[str, Any]) -> None:
    """Raise ValueError if requested_scope is missing or not a SCOPE approval scope."""
    scope = resolve_trigger_requested_scope(trigger)
    if not scope:
        legacy = trigger.get("review_scope")
        if legacy:
            raise ValueError(f"invalid legacy review_scope: {legacy}")
        raise ValueError("review trigger missing required requested_scope")


def _scope_grant_approved_scope(scope_grant: dict[str, Any]) -> str | None:
    """Extract approved scope from simulated or real SCOPE v0.5 grant shapes."""
    approved = scope_grant.get("granted_scope")
    if approved:
        return str(approved)
    auth = scope_grant.get("authorization") or {}
    approved = auth.get("approved_scope")
    return str(approved) if approved else None


def _scope_grant_requested_scope(
    scope_grant: dict[str, Any],
    record: dict[str, Any] | None = None,
    trigger: dict[str, Any] | None = None,
) -> str | None:
    """Extract requested scope from grant, trigger, or record fallback chain."""
    requested = scope_grant.get("requested_scope")
    if requested:
        return str(requested)
    source = scope_grant.get("source") or {}
    requested = source.get("requested_scope")
    if requested:
        return str(requested)
    if trigger:
        requested = trigger.get("requested_scope")
        if requested:
            return str(requested)
    if record:
        rt = record.get("review_trigger") or {}
        requested = rt.get("requested_scope")
        if requested:
            return str(requested)
    return None


def validate_approval_grant(
    *,
    granted_scope: str,
    requested_scope: str,
    allowed_tools: list[str] | None = None,
    blocked_tools: list[str] | None = None,
) -> dict[str, Any]:
    """Simulate SCOPE scoped grant validation (authority-transfer boundary)."""
    if granted_scope not in SCOPE_APPROVAL_SCOPES:
        raise ValueError(f"invalid granted_scope: {granted_scope}")

    if not is_valid_narrowing_grant(
        granted_scope=granted_scope,
        requested_scope=requested_scope,
    ):
        raise ValueError(
            f"grant scope {granted_scope} does not cover requested_scope {requested_scope}"
        )

    narrowed = granted_scope != requested_scope
    return {
        "granted_scope": granted_scope,
        "requested_scope": requested_scope,
        "allowed_tools": allowed_tools or [],
        "blocked_tools": blocked_tools or [],
        "scope_covered": granted_scope == requested_scope,
        "narrow_draft_grant": (
            narrowed
            and requested_scope == "active_protocol_update"
            and granted_scope == "protocol_draft"
        ),
        "narrow_grant": narrowed,
    }


def assemble_review_packet(
    trigger: dict[str, Any],
    record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a SCOPE review packet from trigger-only, record-only, or combined inputs."""
    validate_requested_scope(trigger)
    packet: dict[str, Any] = {
        "packet_type": "scope_review_packet",
        "trigger": extract_scope_fields(trigger),
    }
    if record is not None:
        packet["record"] = {
            "record_id": record.get("record_id"),
            "record_hash": record.get("record_hash"),
            "classification": record.get("classification"),
            "decision": record.get("decision"),
        }
        packet["packet_mode"] = "trigger_plus_record"
    else:
        packet["packet_mode"] = "trigger_only"
    return packet
