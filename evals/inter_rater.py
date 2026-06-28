"""Inter-rater label metadata and agreement statistics for AKTA Bench (v0.6)."""

from __future__ import annotations

from typing import Any

LABEL_SOURCE_ORACLE_INDEPENDENT = "oracle_independent"
LABEL_SOURCE_GATE_DERIVED = "gate_derived"
LABEL_SOURCE_INTER_RATER_CONSENSUS = "inter_rater_consensus"

VALID_LABEL_SOURCES = frozenset({
    LABEL_SOURCE_ORACLE_INDEPENDENT,
    LABEL_SOURCE_GATE_DERIVED,
    LABEL_SOURCE_INTER_RATER_CONSENSUS,
})

INTER_RATER_FIELDS = ("reviewer_ids", "inter_rater_agreement", "label_source")


def extract_label_metadata(expected: dict[str, Any]) -> dict[str, Any] | None:
    """Extract inter-rater fields from an expected_decisions.jsonl row."""
    metadata: dict[str, Any] = {}
    for field in INTER_RATER_FIELDS:
        if field in expected:
            metadata[field] = expected[field]

    if not metadata:
        return None

    label_source = metadata.get("label_source", LABEL_SOURCE_GATE_DERIVED)
    if label_source not in VALID_LABEL_SOURCES:
        raise ValueError(
            f"Invalid label_source {label_source!r}; "
            f"expected one of {sorted(VALID_LABEL_SOURCES)}"
        )

    reviewer_ids = metadata.get("reviewer_ids")
    if reviewer_ids is not None:
        if not isinstance(reviewer_ids, list) or not reviewer_ids:
            raise ValueError("reviewer_ids must be a non-empty list when present")
        if len(set(reviewer_ids)) != len(reviewer_ids):
            raise ValueError("reviewer_ids must be unique")

    agreement = metadata.get("inter_rater_agreement")
    if agreement is not None:
        if not isinstance(agreement, (int, float)) or not (0.0 <= float(agreement) <= 1.0):
            raise ValueError("inter_rater_agreement must be a number in [0.0, 1.0]")

    metadata.setdefault("label_source", LABEL_SOURCE_GATE_DERIVED)
    return metadata


def attach_label_metadata(
    result: dict[str, Any],
    expected: dict[str, Any],
) -> dict[str, Any]:
    """Attach label metadata to a scenario result when present in expected."""
    entry = dict(result)
    label_metadata = extract_label_metadata(expected)
    if label_metadata:
        entry["label_metadata"] = label_metadata
    return entry


def compute_inter_rater_stats(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize inter-rater labeling coverage and agreement from eval results."""
    labeled: list[dict[str, Any]] = []
    by_source: dict[str, int] = {}
    agreements: list[float] = []
    consensus_outcomes: list[bool] = []

    for result in results:
        meta = result.get("label_metadata")
        if not meta:
            continue
        labeled.append(result)
        source = meta.get("label_source", LABEL_SOURCE_GATE_DERIVED)
        by_source[source] = by_source.get(source, 0) + 1

        agreement = meta.get("inter_rater_agreement")
        if agreement is not None:
            agreements.append(float(agreement))

        if source == LABEL_SOURCE_INTER_RATER_CONSENSUS:
            consensus_outcomes.append(bool(result.get("passed")))

    total_labeled = len(labeled)
    stats: dict[str, Any] = {
        "total_labeled": total_labeled,
        "total_unlabeled": len(results) - total_labeled,
        "by_label_source": by_source,
        "mean_inter_rater_agreement": (
            sum(agreements) / len(agreements) if agreements else None
        ),
        "consensus_labeled_count": by_source.get(LABEL_SOURCE_INTER_RATER_CONSENSUS, 0),
        "oracle_independent_count": by_source.get(LABEL_SOURCE_ORACLE_INDEPENDENT, 0),
        "gate_derived_count": by_source.get(LABEL_SOURCE_GATE_DERIVED, 0),
    }

    if consensus_outcomes:
        stats["consensus_accuracy"] = sum(consensus_outcomes) / len(consensus_outcomes)
    else:
        stats["consensus_accuracy"] = None

    high_agreement: list[bool] = []
    for result in labeled:
        meta = result.get("label_metadata") or {}
        agreement = meta.get("inter_rater_agreement")
        if agreement is not None and float(agreement) >= 0.8:
            high_agreement.append(bool(result.get("passed")))
    if high_agreement:
        stats["high_agreement_accuracy"] = sum(high_agreement) / len(high_agreement)
    else:
        stats["high_agreement_accuracy"] = None

    return stats
