"""Domain overlay loading and constraints."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from akta.errors import PolicyError
from akta.hash import hash_file_content


OVERLAY_ALIASES = {
    "generic_lab_v0": "generic_lab_v0.yaml",
    "materials_v0": "materials_v0.yaml",
    "computational_science_v0": "computational_science_v0.yaml",
    "biology_v0": "biology_v0.yaml",
    "chemistry_v0": "chemistry_v0.yaml",
    "clinical_v0": "clinical_v0.yaml",
    # Deprecated aliases retained for scenario compatibility.
    "biology_placeholder": "biology_v0.yaml",
    "chemistry_placeholder": "chemistry_v0.yaml",
    "clinical_placeholder": "clinical_v0.yaml",
}


@dataclass
class DomainOverlay:
    """Loaded domain overlay."""

    name: str
    data: dict[str, Any]
    overlay_hash: str
    path: Path | None = None

    @property
    def version(self) -> str:
        return self.data.get("version", self.name)

    @property
    def operational(self) -> bool:
        return bool(self.data.get("operational", True))

    @property
    def domain(self) -> str:
        return self.data.get("domain", "unknown")

    @classmethod
    def load(cls, overlay_name: str, overlays_dir: str | Path | None = None) -> DomainOverlay | None:
        if not overlay_name:
            return None
        overlays_dir = Path(overlays_dir or "overlays")
        filename = OVERLAY_ALIASES.get(overlay_name, f"{overlay_name}.yaml")
        path = overlays_dir / filename
        if not path.exists():
            alt = overlays_dir / overlay_name
            if alt.suffix != ".yaml":
                alt = overlays_dir / f"{overlay_name}.yaml"
            if alt.exists():
                path = alt
            else:
                raise PolicyError(f"Domain overlay not found: {overlay_name}")
        content = path.read_text(encoding="utf-8")
        data = yaml.safe_load(content)
        return cls(name=overlay_name, data=data, overlay_hash=hash_file_content(content), path=path)

    def blocked_actions(self) -> list[str]:
        return list(self.data.get("blocked_actions", []))

    def minimum_evidence_for(self) -> dict[str, str]:
        return dict(self.data.get("minimum_evidence_for", {}))

    def required_review_roles(self) -> dict[str, list[str]]:
        return dict(self.data.get("required_review_roles", {}))

    def tool_restrictions(self) -> dict[str, dict[str, str]]:
        return dict(self.data.get("tool_restrictions", {}))
