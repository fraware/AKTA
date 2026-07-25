"""Import VSA ScientificReport as AKTA evidence context (v0.6 rich claim graph).

AS-01: prefer normalized ``vsa_bundle`` over loose ``vsa_report``; require
digestable frozen bundles; reject ambiguous multi-report context without an
explicit selected digest; verify recomputed digest matches declared digest.
"""

from __future__ import annotations

from typing import Any

from akta.errors import AKTAError
from akta.hash import hash_object
from akta.records import validate_against_schema


class VSAImportError(AKTAError):
    """Fail-closed VSA bundle import / digest verification error."""


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

VSA_BUNDLE_SCHEMA = "akta-vsa-decision-time-bundle-v1"


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


def freeze_vsa_bundle(report: dict[str, Any]) -> dict[str, Any]:
    """Return a digestable decision-time VSA bundle (no digest fields)."""
    if not isinstance(report, dict) or not report:
        raise VSAImportError("missing_digest: VSA report/bundle is empty or not an object")
    if not (report.get("report_id") or report.get("id") or report.get("scientific_report_id")):
        raise VSAImportError("missing_digest: VSA report lacks report_id for frozen binding")
    frozen = {
        k: v
        for k, v in report.items()
        if k not in ("bundle_digest", "declared_digest", "digest")
    }
    return {
        "schema": VSA_BUNDLE_SCHEMA,
        "bundle_version": str(frozen.get("schema_version") or frozen.get("version") or "vsa-1"),
        **frozen,
    }


def compute_vsa_bundle_digest(bundle: dict[str, Any]) -> str:
    frozen = {k: v for k, v in bundle.items() if k not in ("bundle_digest", "declared_digest", "digest")}
    return hash_object(frozen)


def verify_vsa_bundle_digest(bundle: dict[str, Any], declared: str | None = None) -> str:
    """Recompute digest and fail closed on mismatch with declared digest."""
    computed = compute_vsa_bundle_digest(bundle)
    expected = declared or bundle.get("bundle_digest") or bundle.get("declared_digest") or bundle.get("digest")
    if expected is not None and expected != computed:
        raise VSAImportError(
            f"vsa_bundle_digest_mismatch: declared {expected} != computed {computed}"
        )
    return computed


def _collect_evidence_refs(payload: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for key in ("evidence_refs", "report_refs", "vsa_reports"):
        value = payload.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    refs.append(item)
                elif isinstance(item, dict):
                    rid = item.get("report_id") or item.get("id") or item.get("digest")
                    if rid:
                        refs.append(str(rid))
    if isinstance(payload.get("reports"), list) and len(payload["reports"]) > 1:
        for item in payload["reports"]:
            if isinstance(item, dict):
                rid = item.get("report_id") or item.get("id")
                if rid:
                    refs.append(str(rid))
    return refs


def resolve_vsa_source(context: dict[str, Any]) -> dict[str, Any]:
    """Prefer normalized ``vsa_bundle`` over loose ``vsa_report`` when both present.

    Rejects ambiguous multi-report context without an explicit selected digest.
    """
    if not isinstance(context, dict):
        raise VSAImportError("invalid_input: context must be an object")

    selected = (
        context.get("selected_vsa_digest")
        or (context.get("metadata") or {}).get("selected_vsa_digest")
        or context.get("vsa_selected_digest")
    )

    bundle = context.get("vsa_bundle")
    report = context.get("vsa_report")
    refs = _collect_evidence_refs(context)
    if bundle is not None and report is not None:
        # Prefer bundle; still require disambiguation when multiple refs exist.
        source = bundle
    elif bundle is not None:
        source = bundle
    elif report is not None:
        source = report
    else:
        raise VSAImportError("missing_digest: no vsa_bundle or vsa_report in context")

    if not isinstance(source, dict):
        raise VSAImportError("invalid_input: vsa_bundle/vsa_report must be an object")

    if len(set(refs)) > 1 and not selected:
        raise VSAImportError(
            "ambiguous_evidence_refs: multiple VSA evidence refs present without "
            "explicit selected_vsa_digest"
        )

    if selected:
        digest = verify_vsa_bundle_digest(source)
        if digest != selected and source.get("report_id") != selected and source.get("id") != selected:
            declared = source.get("bundle_digest") or source.get("declared_digest")
            if declared != selected and digest != selected:
                raise VSAImportError(
                    f"ambiguous_evidence_refs: selected_vsa_digest {selected} does not "
                    f"match resolved bundle digest {digest}"
                )

    return source if isinstance(source, dict) else {}


def normalize_vsa_bundle(
    report_or_bundle: dict[str, Any],
    *,
    declared_digest: str | None = None,
    require_declared_digest: bool = False,
) -> dict[str, Any]:
    """Freeze, digest, and optionally verify a VSA decision-time bundle."""
    bundle = freeze_vsa_bundle(report_or_bundle)
    declared = declared_digest or report_or_bundle.get("bundle_digest") or report_or_bundle.get(
        "declared_digest"
    )
    if require_declared_digest and not declared:
        raise VSAImportError("missing_digest: declared VSA bundle digest required")
    digest = verify_vsa_bundle_digest(bundle, declared=declared)
    out = dict(bundle)
    out["bundle_digest"] = digest
    return out


def import_vsa_report(
    report: dict[str, Any],
    *,
    validate: bool = False,
    declared_digest: str | None = None,
    require_digest: bool = False,
) -> dict[str, Any]:
    """Map VSA ScientificReport shape to AKTA context fields.

    Always attaches a normalized ``vsa_bundle`` with ``bundle_digest``. When a
    declared digest is provided (or embedded), recomputed digest must match.
    """
    if validate:
        validate_vsa_report(report)

    bundle = normalize_vsa_bundle(
        report,
        declared_digest=declared_digest,
        require_declared_digest=require_digest,
    )
    digest = bundle["bundle_digest"]

    context: dict[str, Any] = {
        "vsa_report": report,
        "vsa_bundle": bundle,
        "vsa_decision_time_bundle_digest": digest,
    }

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
    metadata["vsa_bundle_digest"] = digest

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


def import_vsa_context(context: dict[str, Any], *, validate: bool = False) -> dict[str, Any]:
    """Resolve preferred VSA source from context and import with digest checks."""
    source = resolve_vsa_source(context)
    return import_vsa_report(source, validate=validate)
