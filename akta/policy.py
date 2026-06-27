"""Policy bundle loading."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from akta.errors import PolicyError
from akta.hash import hash_file_content, hash_object


POLICY_FILES = [
    "action_ontology.yaml",
    "responsibility_levels.yaml",
    "evidence_states.yaml",
    "validation_statuses.yaml",
    "verification_statuses.yaml",
    "deployment_profiles.yaml",
    "admissibility_matrix.yaml",
    "evidence_to_action_matrix.yaml",
]


@dataclass
class PolicyBundle:
    """Loaded AKTA policy bundle."""

    policy_dir: Path
    action_ontology: dict[str, Any]
    responsibility_levels: dict[str, Any]
    evidence_states: dict[str, Any]
    validation_statuses: dict[str, Any]
    verification_statuses: dict[str, Any]
    deployment_profiles: dict[str, Any]
    admissibility_matrix: dict[str, Any]
    evidence_to_action_matrix: dict[str, Any]
    tool_registry: dict[str, Any]
    version: str = "akta-core-v0.1"
    policy_hash: str = ""
    tool_registry_hash: str = ""
    _raw_files: dict[str, str] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dir(
        cls,
        policy_dir: str | Path,
        tool_registry_path: str | Path | None = None,
    ) -> PolicyBundle:
        policy_dir = Path(policy_dir)
        if not policy_dir.is_dir():
            raise PolicyError(f"Policy directory not found: {policy_dir}")

        loaded: dict[str, Any] = {}
        raw_files: dict[str, str] = {}
        for name in POLICY_FILES:
            path = policy_dir / name
            if not path.exists():
                raise PolicyError(f"Missing policy file: {path}")
            content = path.read_text(encoding="utf-8")
            raw_files[name] = content
            loaded[name.replace(".yaml", "")] = yaml.safe_load(content)

        registry_path = Path(tool_registry_path) if tool_registry_path else policy_dir / "default_tool_registry.yaml"
        if not registry_path.exists():
            raise PolicyError(f"Tool registry not found: {registry_path}")
        registry_content = registry_path.read_text(encoding="utf-8")
        raw_files["default_tool_registry.yaml"] = registry_content
        tool_registry = yaml.safe_load(registry_content)

        version = loaded["action_ontology"].get("version", "akta-core-v0.1")
        policy_hash = hash_object({k: raw_files[k] for k in sorted(raw_files) if k != "default_tool_registry.yaml"})
        tool_registry_hash = hash_file_content(registry_content)

        return cls(
            policy_dir=policy_dir,
            action_ontology=loaded["action_ontology"],
            responsibility_levels=loaded["responsibility_levels"],
            evidence_states=loaded["evidence_states"],
            validation_statuses=loaded["validation_statuses"],
            verification_statuses=loaded["verification_statuses"],
            deployment_profiles=loaded["deployment_profiles"],
            admissibility_matrix=loaded["admissibility_matrix"],
            evidence_to_action_matrix=loaded["evidence_to_action_matrix"],
            tool_registry=tool_registry,
            version=version,
            policy_hash=policy_hash,
            tool_registry_hash=tool_registry_hash,
            _raw_files=raw_files,
        )

    def get_profile(self, profile: str) -> dict[str, Any]:
        profiles = self.deployment_profiles.get("profiles", {})
        if profile not in profiles:
            raise PolicyError(f"Unknown deployment profile: {profile}")
        info = profiles[profile]
        if not info.get("supported", True):
            raise PolicyError(
                f"Deployment profile {profile} is not supported in v0.1: "
                f"{info.get('disclaimer', '')}"
            )
        return info

    def normalize_decision(self, raw: str) -> str:
        aliases = self.admissibility_matrix.get("decision_aliases", {})
        return aliases.get(raw, raw)
