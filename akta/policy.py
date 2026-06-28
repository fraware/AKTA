"""Policy bundle loading."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from akta.errors import PolicyError, UnsupportedProfileError
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
    "evidence_to_action_rules.yaml",
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
    evidence_to_action_rules: dict[str, Any]
    tool_registry: dict[str, Any]
    tool_to_requested_scope: dict[str, Any]
    version: str = "akta-core-v0.5"
    policy_hash: str = ""
    tool_registry_hash: str = ""
    integrity_mode: str = "dev_unsigned"
    policy_file_versions: dict[str, str] = field(default_factory=dict, repr=False)
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
        file_versions: dict[str, str] = {}
        for name in POLICY_FILES:
            path = policy_dir / name
            if not path.exists():
                raise PolicyError(f"Missing policy file: {path}")
            content = path.read_text(encoding="utf-8")
            raw_files[name] = content
            parsed = yaml.safe_load(content)
            loaded[name.replace(".yaml", "")] = parsed
            file_versions[name] = parsed.get("policy_file_version", parsed.get("version", "unknown"))

        registry_path = Path(tool_registry_path) if tool_registry_path else policy_dir / "default_tool_registry.yaml"
        if not registry_path.exists():
            raise PolicyError(f"Tool registry not found: {registry_path}")
        registry_content = registry_path.read_text(encoding="utf-8")
        raw_files["default_tool_registry.yaml"] = registry_content
        tool_registry = yaml.safe_load(registry_content)
        file_versions["default_tool_registry.yaml"] = tool_registry.get(
            "policy_file_version", tool_registry.get("version", "unknown")
        )

        scope_path = policy_dir / "tool_to_requested_scope.yaml"
        if not scope_path.exists():
            raise PolicyError(f"Tool scope mapping not found: {scope_path}")
        scope_content = scope_path.read_text(encoding="utf-8")
        raw_files["tool_to_requested_scope.yaml"] = scope_content
        tool_to_requested_scope = yaml.safe_load(scope_content)
        file_versions["tool_to_requested_scope.yaml"] = tool_to_requested_scope.get(
            "policy_file_version", tool_to_requested_scope.get("version", "unknown")
        )

        version = loaded["action_ontology"].get(
            "policy_bundle_version",
            loaded["action_ontology"].get("version", "akta-core-v0.5"),
        )
        policy_hash = hash_object({
            k: raw_files[k]
            for k in sorted(raw_files)
            if k not in ("default_tool_registry.yaml", "tool_to_requested_scope.yaml")
        })
        tool_registry_hash = hash_file_content(registry_content)

        from akta.policy_signing import verify_policy_bundle_integrity

        integrity_result = verify_policy_bundle_integrity(policy_dir, required=False)

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
            evidence_to_action_rules=loaded["evidence_to_action_rules"],
            tool_registry=tool_registry,
            tool_to_requested_scope=tool_to_requested_scope,
            version=version,
            policy_hash=policy_hash,
            tool_registry_hash=tool_registry_hash,
            integrity_mode=integrity_result.integrity_mode,
            policy_file_versions=file_versions,
            _raw_files=raw_files,
        )

    def get_profile(self, profile: str) -> dict[str, Any]:
        profiles = self.deployment_profiles.get("profiles", {})
        if profile not in profiles:
            raise PolicyError(f"Unknown deployment profile: {profile}")
        info = profiles[profile]
        if not info.get("supported", True):
            raise UnsupportedProfileError(
                profile,
                reason=str(info.get("disclaimer", "")),
            )
        return info

    def normalize_decision(self, raw: str) -> str:
        aliases = self.admissibility_matrix.get("decision_aliases", {})
        return aliases.get(raw, raw)

    def profile_matrix_raw(self, profile: str, action_type: str) -> str:
        matrix = self.admissibility_matrix.get("matrix", {})
        row = matrix.get(action_type, {})
        return row.get(profile, "blocked")
