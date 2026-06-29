"""Domain overlay loading and constraints (v0.5 governance)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from akta.errors import PolicyError
from akta.hash import hash_file_content
from akta.policy_integrity import is_production_mode


OVERLAY_ALIASES = {
    "generic_lab_v0": "generic_lab_v0.yaml",
    "materials_v0": "materials_v0.yaml",
    "materials_expert_v0": "materials_expert_v0.yaml",
    "computational_science_v0": "computational_science_v0.yaml",
    "biology_v0": "biology_v0.yaml",
    "chemistry_v0": "chemistry_v0.yaml",
    "clinical_v0": "clinical_v0.yaml",
    # Deprecated aliases retained for scenario compatibility.
    "biology_placeholder": "biology_v0.yaml",
    "chemistry_placeholder": "chemistry_v0.yaml",
    "clinical_placeholder": "clinical_v0.yaml",
    "materials_institutional_v1": "materials_institutional_v1.yaml",
}

OVERLAY_TIERS = frozenset({
    "core_reference",
    "experimental_domain_overlay",
    "expert_reviewed_domain_overlay",
    "institutional_deployment_overlay",
})

HIGH_RISK_DOMAINS = frozenset({"biology", "chemistry", "clinical"})
PRODUCTION_APPROVED_TIERS = frozenset({
    "core_reference",
    "expert_reviewed_domain_overlay",
    "institutional_deployment_overlay",
})


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
    def tier(self) -> str:
        return str(self.data.get("tier", "experimental_domain_overlay"))

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
        overlay = cls(name=overlay_name, data=data, overlay_hash=hash_file_content(content), path=path)
        overlay.enforce_production_governance()
        return overlay

    def enforce_production_governance(self) -> None:
        """Refuse high-risk overlays in production unless expert-reviewed tier."""
        if not is_production_mode():
            return
        tier = self.tier
        if tier not in OVERLAY_TIERS:
            raise PolicyError(
                f"Domain overlay {self.name} missing or invalid tier for production: {tier}"
            )
        if self.domain in HIGH_RISK_DOMAINS or tier == "experimental_domain_overlay":
            if tier not in PRODUCTION_APPROVED_TIERS:
                raise PolicyError(
                    f"Production mode refuses overlay {self.name} (tier={tier}). "
                    "High-risk domain overlays require expert_reviewed_domain_overlay "
                    "or institutional_deployment_overlay tier."
                )

    def blocked_actions(self) -> list[str]:
        return list(self.data.get("blocked_actions", []))

    def minimum_evidence_for(self) -> dict[str, str]:
        return dict(self.data.get("minimum_evidence_for", {}))

    def required_review_roles(self) -> dict[str, list[str]]:
        return dict(self.data.get("required_review_roles", {}))

    def tool_restrictions(self) -> dict[str, dict[str, str]]:
        return dict(self.data.get("tool_restrictions", {}))
