"""Example VSA report import for AKTA context enrichment."""

from __future__ import annotations

import json
from pathlib import Path

from adapters.vsa.import_report import import_vsa_report

EXAMPLE_REPORT = Path(__file__).resolve().parent / "vsa_report_example.json"


def main() -> None:
    report = json.loads(EXAMPLE_REPORT.read_text(encoding="utf-8"))
    context = import_vsa_report(report)
    print(json.dumps(context, indent=2))


if __name__ == "__main__":
    main()
