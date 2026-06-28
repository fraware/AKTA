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

VALIDATION_MAP = {
    "unvalidated": "V0_unvalidated",
    "literature_supported": "V1_literature_supported",
    "simulation_supported": "V2_simulation_supported",
    "preliminary_experimental": "V3_preliminary_experimental_support",
    "internally_replicated": "V4_internally_replicated",
    "independently_replicated": "V5_independently_replicated",
}


def import_vsa_report(report: dict[str, Any]) -> dict[str, Any]:
    """Map VSA ScientificReport shape to AKTA context fields."""
    context: dict[str, Any] = {"vsa_report": report}

    if "evidence_state" in report:
        context["evidence_state"] = report["evidence_state"]
    elif report.get("overall_evidence_strength"):
        strength = str(report["overall_evidence_strength"]).lower()
        context["evidence_state"] = EVIDENCE_STRENGTH_MAP.get(strength, "E0_no_evidence")
    elif report.get("evidence_strength"):
        strength = str(report["evidence_strength"]).lower()
        context["evidence_state"] = EVIDENCE_STRENGTH_MAP.get(strength, "E0_no_evidence")
    elif report.get("claims"):
        levels = [
            str(c.get("evidence_level", "")).lower()
            for c in report["claims"]
            if isinstance(c, dict)
        ]
        mapped = [EVIDENCE_STRENGTH_MAP.get(l) for l in levels if EVIDENCE_STRENGTH_MAP.get(l)]
        context["evidence_state"] = mapped[0] if mapped else "E0_no_evidence"

    if report.get("validation_status"):
        context["validation_status"] = report["validation_status"]
    elif report.get("validation_results"):
        vr = report["validation_results"]
        if isinstance(vr, dict):
            if vr.get("independently_replicated"):
                context["validation_status"] = "V5_independently_replicated"
            elif vr.get("internally_replicated"):
                context["validation_status"] = "V4_internally_replicated"
            elif vr.get("literature_supported"):
                context["validation_status"] = "V1_literature_supported"
            else:
                context["validation_status"] = "V0_unvalidated"
    else:
        context["validation_status"] = "V0_unvalidated"

    metadata: dict[str, Any] = {}
    if report.get("warnings"):
        metadata["vsa_warnings"] = report["warnings"]
    if report.get("limitations"):
        metadata["vsa_limitations"] = report["limitations"]
    if report.get("disclaimers"):
        metadata["disclaimer"] = report["disclaimers"][0] if isinstance(report["disclaimers"], list) else report["disclaimers"]
    if report.get("human_review"):
        metadata["vsa_human_review"] = report["human_review"]
    if metadata:
        context["metadata"] = metadata

    context["vsa_report_ref"] = (
        report.get("report_id") or report.get("id") or report.get("scientific_report_id")
    )
    if report.get("domain"):
        context["domain"] = report["domain"]
    if report.get("project_id"):
        context["project_id"] = report["project_id"]
    return context
