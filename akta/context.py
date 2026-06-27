"""AKTA context model."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class AKTAContext:
    """Structured context for gate evaluation."""

    domain: str | None = None
    project_id: str | None = None
    system_id: str = "example_agent"
    model_id: str | None = None
    agent_id: str | None = None
    session_id: str | None = None
    evidence_state: str | None = None
    validation_status: str | None = None
    verification_status: str | None = None
    consequential: bool | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    vsa_report: dict[str, Any] | None = None
    prior_akta_records: list[dict[str, Any]] = field(default_factory=list)
    handoff_chain: list[dict[str, Any]] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AKTAContext:
        known = {
            "domain",
            "project_id",
            "system_id",
            "model_id",
            "agent_id",
            "session_id",
            "evidence_state",
            "validation_status",
            "verification_status",
            "consequential",
            "metadata",
            "vsa_report",
            "prior_akta_records",
            "handoff_chain",
        }
        kwargs = {k: data[k] for k in known if k in data}
        extra = {k: v for k, v in data.items() if k not in known}
        ctx = cls(**kwargs)
        ctx.extra = extra
        return ctx

    @classmethod
    def from_file(cls, path: str | Path) -> AKTAContext:
        with open(path, encoding="utf-8") as f:
            return cls.from_dict(json.load(f))

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key in (
            "domain",
            "project_id",
            "system_id",
            "model_id",
            "agent_id",
            "session_id",
            "evidence_state",
            "validation_status",
            "verification_status",
            "consequential",
            "metadata",
            "vsa_report",
            "prior_akta_records",
            "handoff_chain",
        ):
            value = getattr(self, key)
            if value is not None and value != [] and value != {}:
                result[key] = value
        result.update(self.extra)
        return result
