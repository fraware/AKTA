"""Import VSA ScientificReport as AKTA evidence context."""

from __future__ import annotations

from typing import Any


EVIDENCE_STRENGTH_MAP = {
    "none": "E0_no_evidence",
    "no_evidence": "E0_no_evidence",
    "anecdotal": "E1_anecdotal_or_informal_observation",
    "preliminary": "E2_preliminary_signal",
    "weak": "E2_preliminary_signal",
    "noisy": "E3_noisy_or_conflicting_evidence",
    "conflicting": "E3_noisy_or_conflicting_evidence",
    "consistent": "E4_internally_consistent_evidence",
    "internally_consistent": "E4_internally_consistent_evidence",
    "replicated": "E5_internally_replicated_evidence",
    "internally_replicated": "E5_internally_replicated_evidence",
    "independent": "E6_independently_reproduced_evidence",
    "independently_reproduced": "E6_independently_reproduced_evidence",
    "validated": "E7_deployment_validated_evidence",
    "deployment_validated": "E7_deployment_validated_evidence",
}


def import_vsa_report(report: dict[str, Any]) -> dict[str, Any]:
    """Map a simplified VSA report to AKTA context fields."""
    context: dict[str, Any] = {"vsa_report": report}

    if "evidence_state" in report:
        context["evidence_state"] = report["evidence_state"]
    elif "overall_evidence_strength" in report:
        strength = str(report["overall_evidence_strength"]).lower()
        context["evidence_state"] = EVIDENCE_STRENGTH_MAP.get(strength, "E2_preliminary_signal")

    validation = report.get("validation_results", {})
    if report.get("validation_status"):
        context["validation_status"] = report["validation_status"]
    elif validation.get("independently_replicated"):
        context["validation_status"] = "V5_independently_replicated"
    elif validation.get("internally_replicated"):
        context["validation_status"] = "V4_internally_replicated"
    elif validation.get("literature_supported"):
        context["validation_status"] = "V1_literature_supported"
    else:
        context["validation_status"] = "V0_unvalidated"

    warnings = report.get("warnings", [])
    if warnings:
        context["metadata"] = {"vsa_warnings": warnings}

    if report.get("human_review"):
        context["metadata"] = context.get("metadata", {})
        context["metadata"]["vsa_human_review"] = report["human_review"]

    context["vsa_report_ref"] = report.get("report_id") or report.get("id")
    return context
