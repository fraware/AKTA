"""Regenerate policy_manifest.yaml after policy file changes (dev use)."""

from __future__ import annotations

import hashlib
import hmac
from pathlib import Path

import yaml

from akta.hash import hash_file_content

ROOT = Path(__file__).resolve().parent.parent
POLICY_DIR = ROOT / "policy"

MANIFEST_FILES = [
    "action_ontology.yaml",
    "responsibility_levels.yaml",
    "evidence_states.yaml",
    "validation_statuses.yaml",
    "verification_statuses.yaml",
    "deployment_profiles.yaml",
    "admissibility_matrix.yaml",
    "evidence_to_action_matrix.yaml",
    "evidence_to_action_rules.yaml",
    "default_tool_registry.yaml",
    "tool_to_requested_scope.yaml",
]

DEFAULT_HMAC_KEY = b"akta-dev-policy-integrity-v0.4-test-key"


def main() -> None:
    files: dict[str, str] = {}
    for name in MANIFEST_FILES:
        path = POLICY_DIR / name
        files[name] = hash_file_content(path.read_text(encoding="utf-8"))

    payload = "|".join(f"{k}:{v}" for k, v in sorted(files.items()))
    sig = hmac.new(DEFAULT_HMAC_KEY, payload.encode("utf-8"), hashlib.sha256).hexdigest()

    manifest = {
        "version": "akta-policy-manifest-v0.5",
        "bundle_version": "akta-core-v0.5",
        "files": files,
        "signature": {"algorithm": "HMAC-SHA256", "value": sig},
    }
    out = POLICY_DIR / "policy_manifest.yaml"
    out.write_text(yaml.dump(manifest, sort_keys=False, default_flow_style=False), encoding="utf-8")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
