"""Build machine-readable AKTA release evidence report (WS14).

Collects component commits, schema/trust hashes, test commands/results,
evaluation reports, package hashes, SBOM, dependency audit, and CodeQL status.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


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
    ]
    out: dict[str, str] = {}
    for name in names:
        path = ROOT / "policy" / name
        if path.is_file():
            out[name] = hash_file_content(path.read_text(encoding="utf-8"))
    return out


def _sibling_commits() -> dict[str, Any]:
    from akta.release_pins import load_release_pins, pins_for_release_report
    from akta.sibling_repos import discover_sibling, git_rev_parse_head

    pins = load_release_pins()
    report = pins_for_release_report(pins)
    components = pins.get("components") or {}
    discovered: dict[str, Any] = {}
    for name, entry in components.items():
        if not isinstance(entry, dict):
            continue
        env_var = str(entry.get("env_var") or "")
        found = discover_sibling(env_var) if env_var else None
        head = git_rev_parse_head(found) if found else None
        discovered[name] = {
            "pinned_commit": entry.get("commit"),
            "status": entry.get("status"),
            "checkout": str(found) if found else None,
            "checkout_head": head,
            "placeholder": "PLACEHOLDER" in str(entry.get("commit") or "").upper()
            or str(entry.get("status") or "") == "missing_placeholder",
        }
    return {"pins": report, "checkouts": discovered}


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


def build_release_evidence_report(
    *,
    test_results: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from akta.release_pins import load_release_pins

    shared_pin = _load_json(ROOT / "policy" / "shared_contracts_pin.json") or {}
    report: dict[str, Any] = {
        "report_type": "akta_release_evidence_v1",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "akta_commit": _git_rev(),
        "component_commits": _sibling_commits(),
        "shared_contracts": {
            "package": shared_pin.get("package") or "scientific-authorization-contracts",
            "package_version": shared_pin.get("package_version"),
            "release_artifact_hash": shared_pin.get("release_artifact_hash"),
        },
        "schema_hashes": _schema_hashes(),
        "trust_manifest_hashes": _trust_manifest_hashes(),
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
        "evaluation_reports": _collect_eval_reports(),
        "test_commands_results": test_results
        or _load_json(ROOT / "dist" / "release_test_results.json")
        or {
            "note": (
                "Populate dist/release_test_results.json from CI (pytest / wheel smoke "
                "/ verify_v1_release) or pass --test-results."
            )
        },
        "vsa_pin": _vsa_pin_status(),
        "beta": True,
    }
    # Drop internal path annotation from pins if present.
    if isinstance(report["release_pins"], dict):
        report["release_pins"].pop("_source", None)
    report["report_hash"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                {k: v for k, v in report.items() if k != "report_hash"},
                sort_keys=True,
                default=str,
            ).encode("utf-8")
        ).hexdigest()
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
    args = parser.parse_args(argv)
    test_results = _load_json(args.test_results) if args.test_results else None
    report = build_release_evidence_report(test_results=test_results)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(
        json.dumps(
            {
                "out": str(args.out),
                "report_hash": report.get("report_hash"),
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
