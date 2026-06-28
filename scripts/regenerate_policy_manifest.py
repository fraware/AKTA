"""Regenerate policy_manifest.yaml after policy file changes (v0.6)."""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import os
from pathlib import Path

import yaml

from akta.hash import hash_file_content
from akta.policy_integrity import ED25519_ALGORITHM, HMAC_ALGORITHM, sign_manifest_ed25519

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


def _load_signing_key() -> bytes | None:
    raw = os.environ.get("AKTA_POLICY_SIGNING_KEY", "").strip()
    if not raw:
        return None
    if len(raw) == 64 and all(c in "0123456789abcdefABCDEF" for c in raw):
        return bytes.fromhex(raw)
    try:
        return base64.b64decode(raw)
    except ValueError:
        return raw.encode("utf-8")


def build_manifest(*, algorithm: str = "auto") -> dict:
    files: dict[str, str] = {}
    for name in MANIFEST_FILES:
        path = POLICY_DIR / name
        files[name] = hash_file_content(path.read_text(encoding="utf-8"))

    manifest: dict = {
        "version": "akta-policy-manifest-v0.6",
        "bundle_version": "akta-core-v0.6",
        "files": files,
    }

    signing_key = _load_signing_key()
    use_ed25519 = algorithm == ED25519_ALGORITHM or (algorithm == "auto" and signing_key is not None)

    if use_ed25519 and signing_key:
        manifest = sign_manifest_ed25519(manifest, signing_key)
        prev_keys = os.environ.get("AKTA_POLICY_PREVIOUS_PUBLIC_KEYS", "")
        if prev_keys:
            manifest["public_keys"] = [
                {"key_id": f"legacy-{i}", "public_key": k.strip()}
                for i, k in enumerate(prev_keys.split(","))
                if k.strip()
            ]
    else:
        key = os.environ.get("AKTA_POLICY_HMAC_KEY", DEFAULT_HMAC_KEY)
        if isinstance(key, str):
            key_bytes = key.encode("utf-8")
        else:
            key_bytes = key
        payload = "|".join(f"{k}:{v}" for k, v in sorted(files.items()))
        sig = hmac.new(key_bytes, payload.encode("utf-8"), hashlib.sha256).hexdigest()
        manifest["signature"] = {"algorithm": HMAC_ALGORITHM, "value": sig}

    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Regenerate AKTA policy manifest")
    parser.add_argument(
        "--algorithm",
        choices=["auto", HMAC_ALGORITHM, ED25519_ALGORITHM],
        default="auto",
        help="Signature algorithm (auto prefers Ed25519 when AKTA_POLICY_SIGNING_KEY set)",
    )
    args = parser.parse_args()
    manifest = build_manifest(algorithm=args.algorithm)
    out = POLICY_DIR / "policy_manifest.yaml"
    out.write_text(yaml.dump(manifest, sort_keys=False, default_flow_style=False), encoding="utf-8")
    algo = manifest.get("signature", {}).get("algorithm", "none")
    print(f"Wrote {out} (signature: {algo})")


if __name__ == "__main__":
    main()
