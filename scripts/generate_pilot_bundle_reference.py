"""Generate hash-only pilot bundle reference manifest."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REF_DIR = ROOT / "examples" / "pilot_bundle_reference"
PILOT_DIR = ROOT / "dist" / "pilot_bundle"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def main() -> int:
    manifest: dict[str, str] = {}
    if PILOT_DIR.is_dir():
        for path in sorted(PILOT_DIR.rglob("*")):
            if path.is_file():
                rel = path.relative_to(PILOT_DIR).as_posix()
                manifest[rel] = f"sha256:{_sha256(path)}"
    else:
        manifest["_note"] = "Generate dist/pilot_bundle first; writing placeholder manifest"
    REF_DIR.mkdir(parents=True, exist_ok=True)
    out = REF_DIR / "manifest_hashes.json"
    out.write_text(json.dumps({"pilot_bundle_version": "akta-pilot-v1.0", "files": manifest}, indent=2), encoding="utf-8")
    print(f"Wrote {out} ({len(manifest)} entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
