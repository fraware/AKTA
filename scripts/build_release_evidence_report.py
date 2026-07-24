"""Build machine-readable AKTA release evidence report (WS14 / P1-18).

Emits one signed report containing component / contract wheel hashes, sibling
SHAs, schema and vocabulary hashes, authorization manifest hash, trust registry
hashes, test commands/results, workflow run IDs, CodeQL, dependency audit, SBOM
hashes, empirical status, and known limitations.

When workflow run IDs are absent the report is marked ``unverified``.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
REPORT_TYPE = "akta_release_evidence_v2"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"


def _git_rev(cwd: Path | None = None) -> str | None:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(cwd or ROOT),
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return out.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def _load_json(path: Path) -> Any | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _file_hashes(pattern: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for path in sorted(ROOT.glob(pattern)):
        if path.is_file():
            out[str(path.relative_to(ROOT)).replace("\\", "/")] = _sha256_file(path)
    return out


def _schema_hashes() -> dict[str, str]:
    hashes: dict[str, str] = {}
    try:
        from akta.shared_contracts import (
            ENVELOPE_SCHEMA_NAME,
            GRANT_STATUS_SCHEMA_NAME,
            GRANT_V2_SCHEMA_NAME,
            authorization_envelope_schema_hash,
            load_contract_schema,
        )
        from akta.hash import hash_object

        hashes["authorization_envelope"] = authorization_envelope_schema_hash()
        for name in (ENVELOPE_SCHEMA_NAME, GRANT_V2_SCHEMA_NAME, GRANT_STATUS_SCHEMA_NAME):
            schema = load_contract_schema(name)
            hashes[name] = hash_object(schema)
    except Exception as exc:  # noqa: BLE001 — report collection must not crash
        hashes["error"] = str(exc)
    return hashes


def _vocabulary_hashes(shared_pin: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "family_vocabulary": shared_pin.get("family_vocabulary"),
        "operation_vocabulary": shared_pin.get("operation_vocabulary"),
        "family_vocabulary_hash": shared_pin.get("family_vocabulary_hash"),
        "operation_vocabulary_hash": shared_pin.get("operation_vocabulary_hash"),
    }
    try:
        from akta.shared_contracts import shared_contract_report

        report = shared_contract_report()
        for key in (
            "family_vocabulary",
            "operation_vocabulary",
            "family_vocabulary_hash",
            "operation_vocabulary_hash",
        ):
            if report.get(key):
                out[key] = report[key]
    except Exception as exc:  # noqa: BLE001
        out["live_error"] = str(exc)
    return {k: v for k, v in out.items() if v is not None}


def _trust_manifest_hashes() -> dict[str, str]:
    from akta.hash import hash_file_content

    names = [
        "scope_grant_issuer_registry.yaml",
        "scope_status_attestation_registry.yaml",
        "scope_policy_manifest_signer_registry.yaml",
        "scope_compatibility_manifest.json",
        "effective_policy_manifest.json",
        "shared_contracts_pin.json",
        "release_pins.yaml",
        "runtime_capability_mapping.yaml",
    ]
    out: dict[str, str] = {}
    for name in names:
        path = ROOT / "policy" / name
        if path.is_file():
            out[name] = hash_file_content(path.read_text(encoding="utf-8"))
    return out


def _authorization_manifest_hash() -> dict[str, Any]:
    """Hash of the stored effective-policy / compatibility authorization surfaces."""
    from akta.hash import hash_file_content

    effective_path = ROOT / "policy" / "effective_policy_manifest.json"
    compat_path = ROOT / "policy" / "scope_compatibility_manifest.json"
    info: dict[str, Any] = {}
    if effective_path.is_file():
        payload = _load_json(effective_path) or {}
        info["effective_policy_manifest_file_hash"] = hash_file_content(
            effective_path.read_text(encoding="utf-8")
        )
        info["effective_policy_manifest_hash"] = payload.get("manifest_hash")
        info["effective_policy_hash"] = payload.get("effective_policy_hash")
    if compat_path.is_file():
        info["compatibility_manifest_hash"] = hash_file_content(
            compat_path.read_text(encoding="utf-8")
        )
    return info


def _sibling_commits() -> dict[str, Any]:
    from akta.release_pins import load_release_pins, pins_for_release_report
    from akta.sibling_repos import discover_sibling, git_rev_parse_head

    pins = load_release_pins()
    report = pins_for_release_report(pins)
    components = pins.get("components") or {}
    discovered: dict[str, Any] = {}
    sibling_shas: dict[str, Any] = {}
    for name, entry in components.items():
        if not isinstance(entry, dict):
            continue
        env_var = str(entry.get("env_var") or "")
        found = discover_sibling(env_var) if env_var else None
        head = git_rev_parse_head(found) if found else None
        pinned = entry.get("commit")
        discovered[name] = {
            "pinned_commit": pinned,
            "status": entry.get("status"),
            "checkout": str(found) if found else None,
            "checkout_head": head,
            "placeholder": "PLACEHOLDER" in str(pinned or "").upper()
            or str(entry.get("status") or "") == "missing_placeholder",
        }
        sibling_shas[name] = {
            "pinned": pinned,
            "checkout_head": head,
            "tag": entry.get("tag"),
        }
    return {"pins": report, "checkouts": discovered, "sibling_shas": sibling_shas}


def _component_artifact_hashes(shared_pin: dict[str, Any]) -> dict[str, Any]:
    """AKTA commit + SCOPE pin + contract wheel / archive hashes."""
    try:
        from akta.release_pins import load_release_pins

        release_pins = load_release_pins()
    except Exception:
        release_pins = {}
    scope_entry = ((release_pins.get("components") or {}).get("SCOPE") or {})
    shared = release_pins.get("shared_contracts") or {}
    return {
        "akta_commit": _git_rev(),
        "akta_package_version": (release_pins.get("target_ecosystem") or {}).get("akta"),
        "scope_commit": scope_entry.get("commit"),
        "scope_tag": scope_entry.get("tag"),
        "contract_package": shared_pin.get("package") or shared.get("package"),
        "contract_package_version": shared_pin.get("package_version")
        or shared.get("package_version"),
        "contract_wheel_sha256": shared_pin.get("wheel_sha256")
        or shared.get("wheel_sha256"),
        "contract_source_archive_sha256": shared_pin.get("source_archive_sha256")
        or shared.get("source_archive_sha256"),
        "contract_release_manifest_sha256": shared_pin.get("release_manifest_sha256")
        or shared.get("release_manifest_sha256"),
        "contract_release_artifact_hash": shared_pin.get("release_artifact_hash")
        or shared.get("release_artifact_hash"),
        "contract_release_signer": shared_pin.get("release_signer")
        or shared.get("release_signer"),
    }


def _collect_eval_reports() -> dict[str, Any]:
    reports_dir = ROOT / "evals" / "reports"
    out: dict[str, Any] = {}
    if not reports_dir.is_dir():
        return out
    for path in sorted(reports_dir.glob("*.json")):
        out[path.name] = {
            "path": str(path.relative_to(ROOT)).replace("\\", "/"),
            "sha256": _sha256_file(path),
            "bytes": path.stat().st_size,
        }
    return out


def _dependency_audit() -> dict[str, Any]:
    audit_path = ROOT / "requirements-audit.txt"
    result_path = ROOT / "dist" / "pip-audit.json"
    info: dict[str, Any] = {
        "requirements_audit": str(audit_path.relative_to(ROOT))
        if audit_path.is_file()
        else None,
        "result_path": None,
        "ok": None,
    }
    if result_path.is_file():
        info["result_path"] = str(result_path.relative_to(ROOT)).replace("\\", "/")
        info["sha256"] = _sha256_file(result_path)
        payload = _load_json(result_path)
        if isinstance(payload, dict):
            deps = payload.get("dependencies") or []
            vulns = sum(len(d.get("vulns") or []) for d in deps if isinstance(d, dict))
            info["vulnerability_count"] = vulns
            info["ok"] = vulns == 0
        elif isinstance(payload, list):
            info["ok"] = len(payload) == 0
            info["vulnerability_count"] = len(payload)
    return info


def _codeql_result() -> dict[str, Any]:
    """Record CodeQL workflow status from env or artifact stub."""
    status = os.environ.get("AKTA_CODEQL_CONCLUSION") or os.environ.get(
        "CODEQL_CONCLUSION"
    )
    artifact = ROOT / "dist" / "codeql-result.json"
    payload = _load_json(artifact)
    return {
        "workflow": ".github/workflows/codeql.yml",
        "conclusion": status or (payload or {}).get("conclusion"),
        "run_id": os.environ.get("AKTA_CODEQL_RUN_ID")
        or (payload or {}).get("run_id"),
        "artifact": str(artifact.relative_to(ROOT)).replace("\\", "/")
        if artifact.is_file()
        else None,
        "note": (
            "CodeQL runs as a separate workflow; conclusion is recorded when "
            "AKTA_CODEQL_CONCLUSION is set or dist/codeql-result.json is present."
        ),
    }


def _sbom_info() -> dict[str, Any]:
    candidates = [
        ROOT / "dist" / "akta.cdx.json",
        ROOT / "dist" / "akta.sbom.stub.json",
    ]
    for path in candidates:
        if path.is_file():
            return {
                "path": str(path.relative_to(ROOT)).replace("\\", "/"),
                "sha256": _sha256_file(path),
                "stub": path.name.endswith("stub.json"),
            }
    return {"path": None, "note": "SBOM not generated yet"}


def _vsa_pin_status() -> dict[str, Any]:
    from akta.release_pins import load_release_pins

    pins = load_release_pins()
    vsa = (pins.get("components") or {}).get("VSA") or {}
    commit = str(vsa.get("commit") or "")
    status = str(vsa.get("status") or "")
    placeholder = (
        "PLACEHOLDER" in commit.upper()
        or "UNAVAILABLE" in commit.upper()
        or status == "missing_placeholder"
        or not commit
        or commit == "0" * 40
    )
    return {
        "pinned": not placeholder and status == "pinned",
        "fail_closed_placeholder": placeholder,
        "commit": commit,
        "tag": vsa.get("tag"),
        "status": status,
        "note": (
            "VSA pin is a real commit; institutional_release still fail-closes "
            "on missing checkout or SHA mismatch."
            if not placeholder
            else (
                "VSA pin is missing or placeholder; institutional_release "
                "must stay red until a real commit is pinned."
            )
        ),
    }


def _workflow_run_ids() -> dict[str, Any]:
    """Collect CI workflow run identifiers from the environment."""
    ids = {
        "github_run_id": os.environ.get("GITHUB_RUN_ID")
        or os.environ.get("AKTA_WORKFLOW_RUN_ID"),
        "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "github_workflow": os.environ.get("GITHUB_WORKFLOW"),
        "github_job": os.environ.get("GITHUB_JOB"),
        "github_sha": os.environ.get("GITHUB_SHA"),
        "github_ref": os.environ.get("GITHUB_REF"),
        "codeql_run_id": os.environ.get("AKTA_CODEQL_RUN_ID"),
        "release_gate_run_id": os.environ.get("AKTA_RELEASE_GATE_RUN_ID"),
    }
    present = {k: v for k, v in ids.items() if v}
    return {
        "ids": present,
        "primary_run_id": present.get("github_run_id"),
        "absent": not bool(present.get("github_run_id")),
    }


def _empirical_status() -> dict[str, Any]:
    """Read-only empirical study status (does not rewrite locked artifacts)."""
    protocol_path = ROOT / "evals" / "empirical" / "study_protocol.json"
    prereg_path = ROOT / "evals" / "empirical" / "preregistration.json"
    report_path = ROOT / "evals" / "reports" / "empirical_agreement.json"
    protocol = _load_json(protocol_path) or {}
    prereg = _load_json(prereg_path) or {}
    report = _load_json(report_path) or {}
    return {
        "empirical_complete": bool(
            protocol.get("empirical_complete")
            or prereg.get("empirical_complete")
            or report.get("empirical_complete")
        ),
        "protocol_version": protocol.get("protocol_version")
        or prereg.get("protocol_version"),
        "preregistration_id": protocol.get("preregistration_id")
        or prereg.get("preregistration_id"),
        "beta": protocol.get("beta", prereg.get("beta")),
        "study_protocol_path": "evals/empirical/study_protocol.json"
        if protocol_path.is_file()
        else None,
        "preregistration_path": "evals/empirical/preregistration.json"
        if prereg_path.is_file()
        else None,
        "agreement_report_path": "evals/reports/empirical_agreement.json"
        if report_path.is_file()
        else None,
        "agreement_report_sha256": _sha256_file(report_path)
        if report_path.is_file()
        else None,
    }


def _known_limitations() -> list[dict[str, Any]]:
    """Structured known limitations for the release evidence report."""
    limitations: list[dict[str, Any]] = [
        {
            "id": "contracts-2.2-wheel-pending",
            "summary": (
                "Canonical scientific-authorization-contracts 2.2 wheel hash is "
                "still PLACEHOLDER; release/production/institutional modes fail closed."
            ),
        },
        {
            "id": "scope-2.2-co-release-pending",
            "summary": (
                "SCOPE 2.2 co-release commit/tag not yet substituted; discovery "
                "pins remain fail-closed for institutional release until updated."
            ),
        },
        {
            "id": "empirical-incomplete",
            "summary": (
                "Empirical impact study is preregistered but empirical_complete "
                "remains false until the signed protocol run completes."
            ),
        },
        {
            "id": "non-certification",
            "summary": (
                "AKTA does not certify deployment safety, replace IRB/biosafety "
                "review, or guarantee sibling live availability in default CI."
            ),
            "doc": "docs/limitations.md",
        },
    ]
    limitations_doc = ROOT / "docs" / "limitations.md"
    if limitations_doc.is_file():
        text = limitations_doc.read_text(encoding="utf-8")
        # Capture top-level "explicitly does not" bullets from the newest section.
        bullets = re.findall(r"^- (.+)$", text, flags=re.MULTILINE)
        for bullet in bullets[:8]:
            limitations.append({
                "id": "limitations-doc",
                "summary": bullet.strip(),
                "doc": "docs/limitations.md",
            })
    return limitations


def _report_signing_payload(report_hash: str) -> bytes:
    return report_hash.encode("utf-8")


def _resolve_report_hmac_key(explicit: bytes | str | None = None) -> bytes | None:
    if explicit is not None:
        return explicit if isinstance(explicit, bytes) else explicit.encode("utf-8")
    for env_name in (
        "AKTA_RELEASE_EVIDENCE_HMAC_KEY",
        "AKTA_POLICY_HMAC_KEY",
    ):
        raw = os.environ.get(env_name)
        if raw:
            return raw.encode("utf-8")
    return None


def _resolve_report_ed25519_key(explicit: bytes | None = None) -> bytes | None:
    if explicit is not None:
        return explicit
    for env_name in (
        "AKTA_RELEASE_EVIDENCE_SIGNING_KEY",
        "AKTA_POLICY_SIGNING_KEY",
    ):
        raw = os.environ.get(env_name, "").strip()
        if not raw:
            continue
        if len(raw) == 64 and all(c in "0123456789abcdefABCDEF" for c in raw):
            return bytes.fromhex(raw)
        try:
            decoded = base64.b64decode(raw)
            if len(decoded) in (32, 64):
                return decoded
        except ValueError:
            continue
    return None


def sign_release_evidence_report(
    report: dict[str, Any],
    *,
    private_key: bytes | None = None,
    hmac_key: bytes | str | None = None,
    key_id: str | None = None,
) -> dict[str, Any]:
    """Attach Ed25519 or HMAC signature over ``report_hash``."""
    out = dict(report)
    report_hash = str(out.get("report_hash") or "")
    if not report_hash:
        raise ValueError("report_hash required before signing")
    payload = _report_signing_payload(report_hash)

    ed_key = _resolve_report_ed25519_key(private_key)
    if ed_key is not None:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        if len(ed_key) == 32:
            private = Ed25519PrivateKey.from_private_bytes(ed_key)
        elif len(ed_key) == 64:
            private = Ed25519PrivateKey.from_private_bytes(ed_key[:32])
        else:
            raise ValueError("Ed25519 private key must be 32 or 64 bytes")
        signature = private.sign(payload)
        public_bytes = private.public_key().public_bytes_raw()
        out["signed_payload_hash"] = report_hash
        out["signature"] = {
            "algorithm": "Ed25519",
            "value": base64.b64encode(signature).decode("ascii"),
            "public_key": base64.b64encode(public_bytes).decode("ascii"),
            "key_id": key_id or "release-evidence-primary",
        }
        return out

    mac_key = _resolve_report_hmac_key(hmac_key)
    if mac_key is None:
        return out

    digest = hmac.new(mac_key, payload, hashlib.sha256).hexdigest()
    out["signed_payload_hash"] = report_hash
    out["signature"] = {
        "algorithm": "HMAC-SHA256",
        "value": digest,
        "key_id": key_id or "release-evidence-hmac",
    }
    return out


def verify_release_evidence_signature(
    report: dict[str, Any],
    *,
    hmac_key: bytes | str | None = None,
) -> None:
    """Verify release evidence signature; raise ValueError on failure."""
    sig = report.get("signature")
    if not isinstance(sig, dict) or not sig.get("value"):
        raise ValueError("release evidence report missing signature")
    report_hash = str(report.get("report_hash") or "")
    if not report_hash:
        raise ValueError("release evidence report missing report_hash")
    if (
        report.get("signed_payload_hash") is not None
        and report.get("signed_payload_hash") != report_hash
    ):
        raise ValueError("signed_payload_hash must equal report_hash")
    payload = _report_signing_payload(report_hash)
    algo = sig.get("algorithm")
    if algo == "HMAC-SHA256":
        mac_key = _resolve_report_hmac_key(hmac_key)
        if mac_key is None:
            raise ValueError("HMAC verification requires signing key")
        expected = hmac.new(mac_key, payload, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, str(sig.get("value") or "")):
            raise ValueError("release evidence HMAC signature verification failed")
        return
    if algo == "Ed25519":
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        signature = base64.b64decode(str(sig.get("value") or ""))
        raw = str(sig.get("public_key") or "").strip()
        if not raw:
            raise ValueError("Ed25519 signature missing public_key")
        key_bytes = (
            bytes.fromhex(raw)
            if len(raw) == 64 and all(c in "0123456789abcdefABCDEF" for c in raw)
            else base64.b64decode(raw)
        )
        try:
            Ed25519PublicKey.from_public_bytes(key_bytes).verify(signature, payload)
        except InvalidSignature as exc:
            raise ValueError(
                "release evidence Ed25519 signature verification failed"
            ) from exc
        return
    raise ValueError(f"Unsupported release evidence signature algorithm: {algo!r}")


def build_release_evidence_report(
    *,
    test_results: dict[str, Any] | None = None,
    sign: bool | None = None,
    private_key: bytes | None = None,
    hmac_key: bytes | str | None = None,
) -> dict[str, Any]:
    from akta.release_pins import load_release_pins

    shared_pin = _load_json(ROOT / "policy" / "shared_contracts_pin.json") or {}
    workflow_runs = _workflow_run_ids()
    component_hashes = _component_artifact_hashes(shared_pin)
    siblings = _sibling_commits()
    verification_status = "unverified" if workflow_runs["absent"] else "verified"

    report: dict[str, Any] = {
        "report_type": REPORT_TYPE,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "verification_status": verification_status,
        "akta_commit": component_hashes.get("akta_commit"),
        "component_hashes": component_hashes,
        "component_commits": {
            "pins": siblings.get("pins"),
            "checkouts": siblings.get("checkouts"),
        },
        "sibling_shas": siblings.get("sibling_shas") or {},
        "shared_contracts": {
            "package": shared_pin.get("package") or "scientific-authorization-contracts",
            "package_version": shared_pin.get("package_version"),
            "release_artifact_hash": shared_pin.get("release_artifact_hash"),
            "wheel_sha256": shared_pin.get("wheel_sha256"),
            "source_archive_sha256": shared_pin.get("source_archive_sha256"),
            "release_manifest_sha256": shared_pin.get("release_manifest_sha256"),
            "release_signer": shared_pin.get("release_signer"),
        },
        "schema_hashes": _schema_hashes(),
        "vocabulary_hashes": _vocabulary_hashes(shared_pin),
        "authorization_manifest_hash": _authorization_manifest_hash(),
        "trust_manifest_hashes": _trust_manifest_hashes(),
        "trust_registry_hashes": {
            k: v
            for k, v in _trust_manifest_hashes().items()
            if k.endswith("_registry.yaml") or "registry" in k
        },
        "release_pins": load_release_pins(),
        "package_hashes": {
            **_file_hashes("dist/*.whl"),
            **_file_hashes("dist/*.tar.gz"),
            **_file_hashes("dist-repro/*.whl"),
        },
        "reproducibility": _load_json(ROOT / "dist" / "reproducibility.json"),
        "sbom": _sbom_info(),
        "dependency_audit": _dependency_audit(),
        "codeql": _codeql_result(),
        "workflow_run_ids": workflow_runs,
        "evaluation_reports": _collect_eval_reports(),
        "test_commands_results": test_results
        or _load_json(ROOT / "dist" / "release_test_results.json")
        or {
            "note": (
                "Populate dist/release_test_results.json from CI (pytest / wheel smoke "
                "/ verify_v1_release) or pass --test-results."
            )
        },
        "empirical_status": _empirical_status(),
        "known_limitations": _known_limitations(),
        "vsa_pin": _vsa_pin_status(),
        "beta": True,
        "unverified_reason": (
            "workflow run IDs absent; mark report unverified until CI attaches "
            "GITHUB_RUN_ID / AKTA_WORKFLOW_RUN_ID"
            if workflow_runs["absent"]
            else None
        ),
    }
    # Drop internal path annotation from pins if present.
    if isinstance(report["release_pins"], dict):
        report["release_pins"].pop("_source", None)

    # Hash excludes signature fields so signing does not invalidate the digest.
    body_for_hash = {
        k: v
        for k, v in report.items()
        if k not in ("report_hash", "signature", "signed_payload_hash")
    }
    report["report_hash"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(body_for_hash, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
    )

    should_sign = sign
    if should_sign is None:
        should_sign = (
            private_key is not None
            or hmac_key is not None
            or _resolve_report_ed25519_key() is not None
            or _resolve_report_hmac_key() is not None
        )
    if should_sign:
        report = sign_release_evidence_report(
            report,
            private_key=private_key,
            hmac_key=hmac_key,
        )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build AKTA release evidence report")
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "dist" / "release_evidence.json",
    )
    parser.add_argument(
        "--test-results",
        type=Path,
        default=None,
        help="Optional JSON file with test command results",
    )
    parser.add_argument(
        "--sign",
        action="store_true",
        help="Force signing (uses AKTA_RELEASE_EVIDENCE_* or policy signing keys)",
    )
    parser.add_argument(
        "--no-sign",
        action="store_true",
        help="Skip signing even when signing keys are present",
    )
    args = parser.parse_args(argv)
    test_results = _load_json(args.test_results) if args.test_results else None
    sign: bool | None
    if args.no_sign:
        sign = False
    elif args.sign:
        sign = True
    else:
        sign = None
    report = build_release_evidence_report(test_results=test_results, sign=sign)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(
        json.dumps(
            {
                "out": str(args.out),
                "report_hash": report.get("report_hash"),
                "report_type": report.get("report_type"),
                "verification_status": report.get("verification_status"),
                "signed": bool((report.get("signature") or {}).get("value")),
                "akta_commit": report.get("akta_commit"),
                "vsa_pin": {
                    "pinned": (report.get("vsa_pin") or {}).get("pinned"),
                    "commit": (report.get("vsa_pin") or {}).get("commit"),
                    "tag": (report.get("vsa_pin") or {}).get("tag"),
                },
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
