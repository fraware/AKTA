"""Inter-rater agreement metrics (directive §8 empirical benchmark).

Synthetic fixtures only — do not treat reviewer ids as real independent experts.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Sequence


def cohens_kappa(rater_a: Sequence[str], rater_b: Sequence[str]) -> float:
    """Cohen's kappa for two raters with categorical labels."""
    if len(rater_a) != len(rater_b) or not rater_a:
        raise ValueError("rater sequences must be non-empty and equal length")
    n = len(rater_a)
    labels = sorted(set(rater_a) | set(rater_b))
    agree = sum(1 for a, b in zip(rater_a, rater_b) if a == b) / n
    # Expected agreement
    pa = Counter(rater_a)
    pb = Counter(rater_b)
    expected = sum((pa[l] / n) * (pb[l] / n) for l in labels)
    if expected >= 1.0:
        return 1.0
    return (agree - expected) / (1.0 - expected)


def fleiss_kappa(ratings: Sequence[Sequence[str]]) -> float:
    """Fleiss' kappa for N items × k raters (rows=items, cols=raters).

    Placeholder-quality implementation for CI scaffolding with synthetic labels.
    """
    if not ratings:
        raise ValueError("ratings required")
    n_items = len(ratings)
    n_raters = len(ratings[0])
    if any(len(row) != n_raters for row in ratings):
        raise ValueError("ragged ratings matrix")
    labels = sorted({lab for row in ratings for lab in row})
    # Proportion of all assignments per label
    counts = Counter(lab for row in ratings for lab in row)
    total = n_items * n_raters
    p = {l: counts[l] / total for l in labels}
    pe = sum(v * v for v in p.values())
    # Per-item agreement
    po_sum = 0.0
    for row in ratings:
        c = Counter(row)
        po_sum += (sum(v * v for v in c.values()) - n_raters) / (n_raters * (n_raters - 1))
    po = po_sum / n_items
    if pe >= 1.0:
        return 1.0
    return (po - pe) / (1.0 - pe)


def krippendorff_alpha_nominal(ratings: Sequence[Sequence[str | None]]) -> float:
    """Krippendorff's alpha (nominal) with optional missing values (None).

    Synthetic-fixture scaffolding; not a full reliability suite.
    """
    # Flatten pair coincidence matrix
    units = []
    for row in ratings:
        observed = [v for v in row if v is not None]
        if len(observed) < 2:
            continue
        units.append(observed)
    if not units:
        return 0.0
    # Observed disagreement
    do = 0.0
    pairs = 0
    value_counts: Counter[str] = Counter()
    for observed in units:
        m = len(observed)
        value_counts.update(observed)
        pairs += m * (m - 1)
        for i, a in enumerate(observed):
            for b in observed[i + 1 :]:
                if a != b:
                    do += 2  # each unordered pair counted twice in coincidence form
    if pairs == 0:
        return 0.0
    do /= pairs
    # Expected disagreement
    n = sum(value_counts.values())
    de = 0.0
    labels = list(value_counts)
    for i, a in enumerate(labels):
        for b in labels[i + 1 :]:
            de += (value_counts[a] * value_counts[b]) * 2
    de = de / (n * (n - 1)) if n > 1 else 0.0
    if de == 0:
        return 1.0
    return 1.0 - (do / de)


def agreement_report_from_synthetic_fixture(fixture: dict[str, Any]) -> dict[str, Any]:
    """Compute agreement metrics from a clearly marked synthetic fixture.

    Expected shape::
        {
          "synthetic": true,
          "note": "CI placeholder — not independent expert labels",
          "rater_a": [...],
          "rater_b": [...],
          "multi_rater": [[...], ...]  # optional
        }
    """
    if not fixture.get("synthetic"):
        raise ValueError("empirical agreement fixtures must set synthetic=true")
    report: dict[str, Any] = {
        "synthetic": True,
        "note": fixture.get("note", "synthetic CI fixture"),
        "cohens_kappa": cohens_kappa(fixture["rater_a"], fixture["rater_b"]),
    }
    if fixture.get("multi_rater"):
        report["fleiss_kappa"] = fleiss_kappa(fixture["multi_rater"])
        report["krippendorff_alpha_nominal"] = krippendorff_alpha_nominal(fixture["multi_rater"])
    return report
