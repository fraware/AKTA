"""Import PF trace certificate / proof artifact into AKTA context (v0.6)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import json


def import_pf_trace_certificate(
    artifact: dict[str, Any] | str | Path,
) -> dict[str, Any]:
    """Attach PF proof/trace certificate metadata to AKTA evaluation context."""
    if isinstance(artifact, (str, Path)):
        data = json.loads(Path(artifact).read_text(encoding="utf-8"))
    else:
        data = artifact

    context: dict[str, Any] = {}
    metadata: dict[str, Any] = {}

    cert_id = (
        data.get("certificate_id")
        or data.get("trace_id")
        or data.get("proof_id")
        or data.get("obligation_id")
    )
    if cert_id:
        metadata["pf_trace_certificate_id"] = cert_id

    if data.get("obligation_hash"):
        metadata["pf_obligation_hash"] = data["obligation_hash"]
    if data.get("source_record_id"):
        metadata["pf_source_record_id"] = data["source_record_id"]
    if data.get("decision_id"):
        metadata["pf_decision_id"] = data["decision_id"]
    if data.get("enforcement_mode"):
        metadata["pf_enforcement_mode"] = data["enforcement_mode"]

    proof = data.get("proof") or data.get("trace") or data.get("runtime_proof")
    if proof:
        metadata["pf_trace_proof"] = proof

    if metadata:
        context["metadata"] = metadata

    integrations = {
        "pf_trace_ref": cert_id,
        "pf_obligation_type": data.get("obligation_type"),
        "pf_decision": data.get("decision"),
    }
    context["integrations"] = {k: v for k, v in integrations.items() if v is not None}
    return context


def merge_pf_trace_into_context(
    context: dict[str, Any],
    artifact: dict[str, Any] | str | Path,
) -> dict[str, Any]:
    """Merge PF trace import into an existing AKTA context dict."""
    imported = import_pf_trace_certificate(artifact)
    merged = dict(context)
    merged_metadata = dict(merged.get("metadata") or {})
    merged_metadata.update(imported.get("metadata") or {})
    merged["metadata"] = merged_metadata
    merged_integrations = dict(merged.get("integrations") or {})
    merged_integrations.update(imported.get("integrations") or {})
    if merged_integrations:
        merged["integrations"] = merged_integrations
    return merged
