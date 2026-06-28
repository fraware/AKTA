"""Import VSA ScientificReport as AKTA evidence context (v0.6 rich claim graph)."""

from __future__ import annotations

from typing import Any

from akta.records import validate_against_schema


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

EVIDENCE_RANK = {v: i for i, v in enumerate([
    "E0_no_evidence", "E1_anecdotal_or_informal_observation", "E2_preliminary_signal",
    "E3_noisy_or_conflicting_evidence", "E4_internally_consistent_evidence",
    "E5_internally_replicated_evidence", "E6_independently_reproduced_evidence",
    "E7_deployment_validated_evidence",
])}


def validate_vsa_report(report: dict[str, Any]) -> None:
    """Validate report against VSA ScientificReport schema."""
    validate_against_schema(report, "vsa_scientific_report.schema.json")


def _map_evidence_level(level: str) -> str | None:
    return EVIDENCE_STRENGTH_MAP.get(str(level).lower())


def _aggregate_claim_evidence(claims: list[dict[str, Any]]) -> str:
    """Derive conservative evidence state from claim graph."""
    mapped: list[str] = []
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        level = claim.get("evidence_level") or claim.get("status")
        if level:
            m = _map_evidence_level(str(level))
            if m:
                mapped.append(m)
    if not mapped:
        return "E0_no_evidence"
    return min(mapped, key=lambda s: EVIDENCE_RANK.get(s, 99))


def _resolve_validation_from_results(vr: dict[str, Any]) -> str:
    if vr.get("independently_replicated"):
        return "V5_independently_replicated"
    if vr.get("internally_replicated"):
        return "V4_internally_replicated"
    if vr.get("preliminary_experimental"):
        return "V3_preliminary_experimental_support"
    if vr.get("simulation_supported"):
        return "V2_simulation_supported"
    if vr.get("literature_supported"):
        return "V1_literature_supported"
    return "V0_unvalidated"


def _build_claim_graph_summary(report: dict[str, Any]) -> dict[str, Any]:
    claims = [c for c in (report.get("claims") or []) if isinstance(c, dict)]
    links = [l for l in (report.get("evidence_links") or []) if isinstance(l, dict)]
    return {
        "claim_count": len(claims),
        "evidence_link_count": len(links),
        "claim_ids": [c.get("claim_id") for c in claims if c.get("claim_id")][:20],
        "linked_claims": sorted({l.get("claim_id") for l in links if l.get("claim_id")}),
    }


def import_vsa_report(report: dict[str, Any], *, validate: bool = False) -> dict[str, Any]:
    """Map VSA ScientificReport shape to AKTA context fields."""
    if validate:
        validate_vsa_report(report)

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
        context["evidence_state"] = _aggregate_claim_evidence(report["claims"])

    if report.get("validation_status"):
        context["validation_status"] = report["validation_status"]
    elif report.get("validation_results"):
        vr = report["validation_results"]
        if isinstance(vr, dict):
            context["validation_status"] = _resolve_validation_from_results(vr)
    else:
        context["validation_status"] = "V0_unvalidated"

    metadata: dict[str, Any] = {}
    if report.get("warnings"):
        metadata["vsa_warnings"] = report["warnings"]
    if report.get("limitations"):
        metadata["vsa_limitations"] = report["limitations"]
    if report.get("disclaimers"):
        metadata["disclaimer"] = (
            report["disclaimers"][0]
            if isinstance(report["disclaimers"], list)
            else report["disclaimers"]
        )
    if report.get("human_review"):
        metadata["vsa_human_review"] = report["human_review"]

    graph = _build_claim_graph_summary(report)
    metadata["vsa_claim_graph"] = graph

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
