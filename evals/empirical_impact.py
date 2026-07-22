"""Empirical impact benchmark entrypoint (directive §8.2).

Ground truth must not be developer policy outputs. Labels come from independent
domain review processes; this entrypoint consumes annotation fixtures and
computes agreement scaffolding. Synthetic fixtures are allowed for CI only when
marked ``synthetic: true``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evals.agreement import agreement_report_from_synthetic_fixture

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FIXTURE = ROOT / "evals" / "fixtures" / "synthetic_inter_rater.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AKTA empirical-impact agreement scaffolding")
    parser.add_argument("--fixture", default=str(DEFAULT_FIXTURE))
    parser.add_argument(
        "--out",
        default=str(ROOT / "evals" / "reports" / "empirical_agreement.json"),
    )
    args = parser.parse_args(argv)
    fixture = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
    report = {
        "suite": "empirical_impact",
        "ground_truth_source": "independent_or_synthetic_annotations",
        "warning": (
            "Do not treat developer policy outputs as empirical ground truth. "
            "Preserve raw annotation schema fields in fixtures."
        ),
        "agreement": agreement_report_from_synthetic_fixture(fixture),
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"suite": "empirical_impact", "out": args.out, "kappa": report["agreement"]["cohens_kappa"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
