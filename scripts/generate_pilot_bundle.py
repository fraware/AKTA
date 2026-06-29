"""Generate frozen pilot bundle with live SCOPE (v1.0 release gate)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    if not (os.environ.get("SCOPE_REPO_PATH") or os.environ.get("SCOPE_CLI")):
        print("Set SCOPE_REPO_PATH or SCOPE_CLI for live SCOPE", file=sys.stderr)
        return 1

    from akta.scope_contract import validate_scope_runtime_contract

    validate_scope_runtime_contract(strict=True)

    sys.path.insert(0, str(ROOT))
    from scripts.demo_reconstructable_experiment import run_demo

    return run_demo(cross_repo=True, pilot=True)


if __name__ == "__main__":
    raise SystemExit(main())
