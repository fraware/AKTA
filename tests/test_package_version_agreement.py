"""P0-2: every declared AKTA package version must agree on 1.2.0."""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from akta import __version__ as akta_version
from akta.cli import build_parser

ROOT = Path(__file__).resolve().parent.parent
EXPECTED = "1.2.0"


def _pyproject_version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'(?m)^version\s*=\s*"([^"]+)"', text)
    assert match, "pyproject.toml missing project version"
    return match.group(1)


def _citation_versions() -> list[str]:
    text = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
    # CITATION.cff is YAML; top-level version + preferred-citation.version.
    data = yaml.safe_load(text)
    versions = [str(data.get("version") or "")]
    preferred = data.get("preferred-citation") or {}
    if isinstance(preferred, dict) and preferred.get("version"):
        versions.append(str(preferred["version"]))
    return versions


def _readme_version() -> str | None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    match = re.search(r"\*\*v(\d+\.\d+\.\d+)\*\*", text)
    return match.group(1) if match else None


def _changelog_has_section() -> bool:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    return f"## [{EXPECTED}]" in text


def _compat_manifest_version() -> str:
    data = json.loads(
        (ROOT / "policy" / "scope_compatibility_manifest.json").read_text(encoding="utf-8")
    )
    return str(data["akta_package_version"])


def _release_pins_akta_target() -> str:
    data = yaml.safe_load((ROOT / "policy" / "release_pins.yaml").read_text(encoding="utf-8"))
    target = data.get("target_ecosystem") or {}
    return str(target.get("akta") or "")


def collect_declared_versions() -> dict[str, str]:
    """Collect every declared package identity surface."""
    declared = {
        "akta.__version__": akta_version,
        "pyproject.toml": _pyproject_version(),
        "README.md": _readme_version() or "",
        "scope_compatibility_manifest.json": _compat_manifest_version(),
        "release_pins.target_ecosystem.akta": _release_pins_akta_target(),
    }
    for idx, value in enumerate(_citation_versions()):
        declared[f"CITATION.cff[{idx}]"] = value
    return declared


def test_package_version_agreement() -> None:
    declared = collect_declared_versions()
    disagreements = {
        surface: value for surface, value in declared.items() if value != EXPECTED
    }
    assert not disagreements, f"version disagreement vs {EXPECTED}: {disagreements}"
    assert _changelog_has_section(), f"CHANGELOG.md missing ## [{EXPECTED}] section"

    parser = build_parser()
    version_action = next(
        (a for a in parser._actions if getattr(a, "dest", None) == "version"),
        None,
    )
    assert version_action is not None
    assert EXPECTED in str(version_action.version)
