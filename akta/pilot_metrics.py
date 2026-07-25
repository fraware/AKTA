"""Append-only outcome references and privacy-preserving pilot metrics (AS-07)."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from akta.errors import AKTAError
from akta.failure_mapping import map_local_reason
from akta.hash import hash_object
from akta.records import utc_now_iso, validate_against_schema

OUTCOME_REF_VERSION = "akta-outcome-ref-v1"
PILOT_METRICS_VERSION = "akta-pilot-metrics-v1"

_BINDING_COMPLETENESS_FIELDS = (
    "decision_id",
    "record_id",
    "policy_hash",
    "tool_registry_hash",
    "requested_tool",
    "action_class",
    "vsa_decision_time_bundle_digest",
    "decision_basis_digest",
)

_FORBIDDEN_METRIC_KEYS = {
    "ai_output",
    "summary",
    "raw_text",
    "patient",
    "email",
    "name",
    "ssn",
    "evidence_text",
    "claim_text",
}


class OutcomeMutationError(AKTAError):
    """Attempt to mutate historical admissibility via outcome linkage."""


def _decision_digest(decision: dict[str, Any]) -> str:
    body = {k: v for k, v in decision.items() if k not in ("integrations",)}
    return hash_object(body)


def _record_digest(record: dict[str, Any]) -> str:
    return record.get("record_hash") or hash_object(
        {k: v for k, v in record.items() if k != "record_hash"}
    )


def build_outcome_ref(
    *,
    record: dict[str, Any],
    decision: dict[str, Any] | None = None,
    memory_entry_digest: str,
    linker_identity: str,
    timestamp: str | None = None,
    prev_outcome_ref_digest: str | None = None,
    notes: str = "",
    validate: bool = True,
) -> dict[str, Any]:
    dec = decision or {
        "decision_id": record.get("record_id", "").replace("SAR", "DEC"),
        "admissibility": (record.get("decision") or {}).get("admissibility"),
    }
    ref: dict[str, Any] = {
        "outcome_ref_version": OUTCOME_REF_VERSION,
        "outcome_ref_id": f"AKTA-OUT-{uuid.uuid4().hex[:8].upper()}",
        "decision_id": dec.get("decision_id") or (record.get("bindings") or {}).get("decision_id"),
        "record_id": record.get("record_id"),
        "decision_digest": _decision_digest(dec),
        "record_digest": _record_digest(record),
        "memory_entry_digest": memory_entry_digest,
        "timestamp": timestamp or utc_now_iso(),
        "linker_identity": linker_identity,
        "verdict_mutation": False,
        "prev_outcome_ref_digest": prev_outcome_ref_digest,
        "notes": notes,
    }
    ref["outcome_ref_digest"] = hash_object(
        {k: v for k, v in ref.items() if k != "outcome_ref_digest"}
    )
    if validate:
        validate_against_schema(ref, "outcome_ref.schema.json")
    return ref


def link_outcome_to_record(
    record: dict[str, Any],
    outcome_ref: dict[str, Any],
    *,
    original_admissibility: str | None = None,
) -> dict[str, Any]:
    """Append outcome_ref to record integrations; never mutate admissibility."""
    if outcome_ref.get("verdict_mutation") is not False:
        raise OutcomeMutationError("verdict_mutation must be false")
    validate_against_schema(outcome_ref, "outcome_ref.schema.json")

    updated = json.loads(json.dumps(record))  # deep copy via JSON
    decision = updated.get("decision") or {}
    prior_adm = original_admissibility or decision.get("admissibility")
    if decision.get("admissibility") != prior_adm:
        raise OutcomeMutationError("admissibility mutation rejected")

    # Reject attempts to rewrite admissibility through the outcome payload.
    if "admissibility" in outcome_ref and outcome_ref["admissibility"] != prior_adm:
        raise OutcomeMutationError("outcome_ref cannot rewrite admissibility")

    integrations = dict(updated.get("integrations") or {})
    refs = list(integrations.get("outcome_refs") or [])
    prev = refs[-1].get("outcome_ref_digest") if refs else None
    if outcome_ref.get("prev_outcome_ref_digest") in (None, "") and prev:
        outcome_ref = dict(outcome_ref)
        outcome_ref["prev_outcome_ref_digest"] = prev
        outcome_ref["outcome_ref_digest"] = hash_object(
            {k: v for k, v in outcome_ref.items() if k != "outcome_ref_digest"}
        )
    refs.append(outcome_ref)
    integrations["outcome_refs"] = refs
    updated["integrations"] = integrations

    # Recompute record_hash without changing decision.admissibility.
    updated["record_hash"] = hash_object(
        {k: v for k, v in updated.items() if k != "record_hash"}
    )
    if (updated.get("decision") or {}).get("admissibility") != prior_adm:
        raise OutcomeMutationError("admissibility mutation rejected after link")
    return updated


def reject_admissibility_rewrite(
    record: dict[str, Any],
    *,
    new_admissibility: str,
) -> dict[str, Any]:
    """Explicit fail-closed helper for mutation attempts."""
    current = (record.get("decision") or {}).get("admissibility")
    if new_admissibility != current:
        failure = map_local_reason(
            "outcome_mutation_rejected",
            detail=f"cannot rewrite admissibility {current} -> {new_admissibility}",
            layer="outcome",
        )
        raise OutcomeMutationError(failure["detail"])
    return record


def binding_completeness(bindings: dict[str, Any] | None) -> float:
    b = bindings or {}
    present = sum(1 for f in _BINDING_COMPLETENESS_FIELDS if b.get(f))
    return present / len(_BINDING_COMPLETENESS_FIELDS)


def _assert_no_raw_pii(metrics: dict[str, Any]) -> None:
    blob = json.dumps(metrics)
    for key in _FORBIDDEN_METRIC_KEYS:
        # Allow the key name only inside non_claims strings.
        pass
    def _walk(obj: Any, path: str = "") -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in _FORBIDDEN_METRIC_KEYS and k != "non_claims":
                    raise AKTAError(f"pilot_metrics_forbidden_field:{path}.{k}")
                _walk(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                _walk(v, f"{path}[{i}]")

    _walk(metrics)


def export_pilot_metrics(
    records: list[dict[str, Any]],
    *,
    shadow_comparisons: list[dict[str, Any]] | None = None,
    validate: bool = True,
) -> dict[str, Any]:
    """Emit aggregate-only pilot metrics (no raw evidence / PII fields)."""
    n = len(records)
    adm_counts: dict[str, int] = {}
    reason_counts: dict[str, int] = {}
    sufficiency = {"sufficient": 0, "insufficient": 0, "unknown": 0}
    completeness_scores: list[float] = []
    later_inapprop = 0
    unnecessary_block = 0

    for rec in records:
        decision = rec.get("decision") or {}
        adm = str(decision.get("admissibility") or "unknown")
        adm_counts[adm] = adm_counts.get(adm, 0) + 1
        reason = str(decision.get("decision_reason") or "unspecified")[:80]
        # Store hashed/bucketed reason codes only — not free-text essays.
        code = (rec.get("failure") or {}).get("local_reason_code") or reason.split(":")[0][:64]
        reason_counts[code] = reason_counts.get(code, 0) + 1

        evidence = (rec.get("classification") or {}).get("evidence_state") or ""
        if evidence.startswith("E0") or evidence.startswith("E1") or evidence.startswith("E2"):
            sufficiency["insufficient"] += 1
        elif evidence.startswith("E"):
            sufficiency["sufficient"] += 1
        else:
            sufficiency["unknown"] += 1

        completeness_scores.append(binding_completeness(rec.get("bindings")))

        meta = (rec.get("scientific_context") or {})
        if meta.get("later_inappropriate_authorization"):
            later_inapprop += 1
        if adm == "blocked" and meta.get("unnecessary_blocking"):
            unnecessary_block += 1

    comparisons = shadow_comparisons or []
    disagreements = sum(1 for c in comparisons if c.get("disagreement"))
    disagreement_rate = (disagreements / len(comparisons)) if comparisons else 0.0

    rates = {k: (v / n if n else 0.0) for k, v in adm_counts.items()}
    metrics = {
        "pilot_metrics_version": PILOT_METRICS_VERSION,
        "record_count": n,
        "evidence_sufficiency": {
            k: (v / n if n else 0.0) for k, v in sufficiency.items()
        },
        "admissibility_rates": rates,
        "reason_code_distribution": reason_counts,
        "human_disagreement_rate": disagreement_rate,
        "later_inappropriate_authorization_rate": (later_inapprop / n) if n else 0.0,
        "unnecessary_blocking_rate": (unnecessary_block / n) if n else 0.0,
        "time_to_decision": {"count": n, "mean_seconds": None},
        "reconstruction_completeness": (
            sum(completeness_scores) / len(completeness_scores) if completeness_scores else 0.0
        ),
        "non_claims": [
            "No institution-wide scientific efficacy metric.",
            "Aggregates only; raw evidence text and PII are excluded.",
            "Outcome links are append-only and do not mutate admissibility.",
        ],
    }
    _assert_no_raw_pii(metrics)
    if validate:
        validate_against_schema(metrics, "pilot_metrics.schema.json")
    return metrics


def load_records_dir(path: str | Path) -> list[dict[str, Any]]:
    root = Path(path)
    records: list[dict[str, Any]] = []
    if root.is_file():
        records.append(json.loads(root.read_text(encoding="utf-8")))
        return records
    for p in sorted(root.glob("*.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict) and (data.get("record_id") or data.get("decision")):
            records.append(data)
    return records


__all__ = [
    "OutcomeMutationError",
    "binding_completeness",
    "build_outcome_ref",
    "export_pilot_metrics",
    "link_outcome_to_record",
    "load_records_dir",
    "reject_admissibility_rewrite",
]
