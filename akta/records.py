"""AKTA Record generation and validation."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import jsonschema

from akta.hash import hash_object
from akta.errors import SchemaValidationError


SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"


def _load_schema(name: str) -> dict[str, Any]:
    with open(SCHEMAS_DIR / name, encoding="utf-8") as f:
        return json.load(f)


def validate_against_schema(data: dict[str, Any], schema_name: str) -> None:
    schema = _load_schema(schema_name)
    try:
        jsonschema.validate(instance=data, schema=schema)
    except jsonschema.ValidationError as exc:
        raise SchemaValidationError(str(exc)) from exc


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_record_id() -> str:
    return f"AKTA-SAR-{uuid.uuid4().hex[:8].upper()}"


def new_decision_id() -> str:
    return f"AKTA-DEC-{uuid.uuid4().hex[:8].upper()}"


def new_review_trigger_id() -> str:
    return f"AKTA-REVTRIG-{uuid.uuid4().hex[:8].upper()}"


def ai_output_summary(ai_output: Any) -> str:
    if isinstance(ai_output, str):
        return ai_output
    if isinstance(ai_output, dict):
        return str(ai_output.get("summary") or ai_output.get("text") or ai_output)
    return str(ai_output)


def build_review_trigger(
    *,
    decision_id: str,
    record_id: str,
    role: str,
    action_type: str,
    requested_tool: str = "",
    requested_action: str = "",
    deployment_profile: str = "",
    scientific_action_type: str = "",
    responsibility_level: str = "",
    evidence_state: str = "",
    validation_status: str = "",
    verification_status: str = "",
    admissibility: str = "",
    decision_reason: str = "",
    blocked_tools: list[str] | None = None,
    allowed_next_steps: list[str] | None = None,
    policy_hash: str = "",
    tool_registry_hash: str = "",
    domain_overlay_hash: str | None = None,
    classifier_confidence: float = 0.95,
    classification_rationale: str = "",
    consequentiality: bool = False,
    consequentiality_reason: str = "",
    scientific_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build SCOPE-compatible review trigger artifact."""
    scope_map = {
        "A5_protocol_modification": "protocol_draft_to_validation_run",
        "A6_experimental_planning": "experimental_plan_review",
        "A7_resource_or_queue_prioritization": "queue_prioritization_review",
        "A10_publication_or_claim_escalation": "publication_claim_review",
    }
    trigger = {
        "review_trigger_id": new_review_trigger_id(),
        "decision_id": decision_id,
        "source_record_id": record_id,
        "requested_tool": requested_tool,
        "requested_action": requested_action,
        "deployment_profile": deployment_profile,
        "scientific_action_type": scientific_action_type or action_type,
        "responsibility_level": responsibility_level,
        "evidence_state": evidence_state,
        "validation_status": validation_status,
        "verification_status": verification_status,
        "admissibility": admissibility,
        "decision_reason": decision_reason,
        "required_review_role": role or "domain_scientist",
        "review_scope": scope_map.get(action_type, "scientific_action_review"),
        "review_artifacts_required": [
            "ai_output",
            "akta_record",
            "protocol_diff",
            "evidence_state",
            "validation_status",
            "blocked_tools",
            "next_admissible_steps",
        ],
        "blocked_tools": blocked_tools or [],
        "allowed_next_steps": allowed_next_steps or [],
        "approval_effect": "Allows scoped next step only; not global permission.",
        "default_expiration": "single_run",
        "policy_hash": policy_hash,
        "tool_registry_hash": tool_registry_hash,
        "classifier_confidence": classifier_confidence,
        "classification_rationale": classification_rationale,
        "consequentiality": consequentiality,
        "consequentiality_reason": consequentiality_reason,
        "scientific_context": scientific_context or {},
    }
    if domain_overlay_hash:
        trigger["domain_overlay_hash"] = domain_overlay_hash
    trigger["review_trigger_hash"] = hash_object(
        {k: v for k, v in trigger.items() if k != "review_trigger_hash"}
    )
    return trigger


class AKTADecision:
    """AKTA admissibility decision."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    @property
    def admissibility(self) -> str:
        return self._data["admissibility"]

    @property
    def data(self) -> dict[str, Any]:
        return dict(self._data)

    def to_dict(self) -> dict[str, Any]:
        return dict(self._data)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self._data, indent=indent, ensure_ascii=False)

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def from_file(cls, path: str | Path) -> AKTADecision:
        with open(path, encoding="utf-8") as f:
            return cls(json.load(f))

    def to_record(
        self,
        ai_output: Any = None,
        context: dict[str, Any] | None = None,
    ) -> AKTARecord:
        ctx = context or {}
        summary = ai_output_summary(ai_output) if ai_output else self._data.get("ai_output_summary", "")
        raw_ref = hash_object(summary) if summary else None

        classification_block = {
            "scientific_action_type": self._data["scientific_action_type"],
            "responsibility_level": self._data["responsibility_level"],
            "evidence_state": self._data["evidence_state"],
            "validation_status": self._data["validation_status"],
            "verification_status": self._data["verification_status"],
            "classifier_confidence": self._data.get("classifier_confidence", 0.95),
        }
        if self._data.get("classification"):
            classification_block["classification_detail"] = self._data["classification"]

        record_body = {
            "record_id": new_record_id(),
            "record_type": "scientific_action_record",
            "timestamp": self._data.get("timestamp", utc_now_iso()),
            "system": {
                "system_id": self._data.get("system_id", ctx.get("system_id", "example_agent")),
                "model_id": ctx.get("model_id", "unknown"),
                "agent_id": ctx.get("agent_id", "agent_001"),
                "session_id": ctx.get("session_id", "session_default"),
            },
            "scientific_context": {
                "domain": self._data.get("domain", ctx.get("domain", "generic")),
                "project_id": ctx.get("project_id", "demo_project"),
                "deployment_profile": self._data["deployment_profile"],
                **(
                    {"domain_overlay": self._data["domain_overlay_version"]}
                    if self._data.get("domain_overlay_version")
                    else {}
                ),
            },
            "ai_output": {
                "summary": summary or "No AI output summary provided.",
                "raw_ref": raw_ref,
                "output_type": ctx.get("output_type", "natural_language_recommendation"),
            },
            "requested_transition": {
                "requested_action": self._data["requested_action"],
                "requested_tool": self._data["requested_tool"],
                **(
                    {"tool_payload_ref": ctx["tool_payload_ref"]}
                    if ctx.get("tool_payload_ref")
                    else {}
                ),
            },
            "classification": classification_block,
            "decision": {
                "admissibility": self._data["admissibility"],
                "decision_reason": self._data["decision_reason"],
                "blocked_tools": self._data.get("blocked_tools", []),
                "allowed_tools": self._data.get("allowed_tools", []),
                "required_review_role": self._data.get("required_review_role"),
                "next_admissible_steps": self._data.get("next_admissible_steps", []),
                "consequentiality": self._data.get("consequentiality", False),
                "consequentiality_reason": self._data.get("consequentiality_reason", ""),
            },
            "provenance": {
                "policy_version": self._data["policy_version"],
                "policy_hash": self._data["policy_hash"],
                **(
                    {"domain_overlay_version": self._data["domain_overlay_version"]}
                    if self._data.get("domain_overlay_version")
                    else {}
                ),
                **(
                    {"domain_overlay_hash": self._data["domain_overlay_hash"]}
                    if self._data.get("domain_overlay_hash")
                    else {}
                ),
                "tool_registry_hash": self._data["tool_registry_hash"],
            },
            "integrations": {
                "vsa_report_ref": ctx.get("vsa_report_ref"),
                "pf_core_obligation_ref": None,
                "pcs_artifact_ref": None,
                "prior_akta_records": ctx.get("prior_akta_records", []),
            },
        }
        if self._data.get("review_trigger"):
            record_body["review_trigger"] = self._data["review_trigger"]
        record_body["record_hash"] = hash_object({k: v for k, v in record_body.items() if k != "record_hash"})
        return AKTARecord(record_body)


class AKTARecord:
    """AKTA scientific action record."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    @property
    def data(self) -> dict[str, Any]:
        return dict(self._data)

    def to_dict(self) -> dict[str, Any]:
        return dict(self._data)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self._data, indent=indent, ensure_ascii=False)

    def save(self, path: str | Path, validate: bool = True) -> None:
        if validate:
            validate_against_schema(self._data, "akta_record.schema.json")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def from_file(cls, path: str | Path) -> AKTARecord:
        with open(path, encoding="utf-8") as f:
            return cls(json.load(f))

    @classmethod
    def from_decision_file(cls, decision_path: str | Path, **kwargs: Any) -> AKTARecord:
        decision = AKTADecision.from_file(decision_path)
        return decision.to_record(**kwargs)
