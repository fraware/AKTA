"""Durable SCOPE grant-status replay store (AKTA 1.2 P0-9).

Keyed by ``(tenant_id, grant_id, status_attestor_key_id)``. Acceptance rules:

- newer sequence than stored → accept and update
- same sequence and same status hash → idempotent accept
- same sequence and different hash → reject
- lower sequence → reject
- stale ``checked_at`` → reject
- unauthorized attestor rotation → reject

Replay state is never stored on the untrusted grant dictionary.
"""

from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from akta.hash import hash_object

DEFAULT_MAX_CHECKED_AT_AGE_SECONDS = 300
_SAFE_KEY = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True)
class StatusReplayRecord:
    tenant_id: str
    grant_id: str
    status_attestor_key_id: str
    last_ledger_sequence: int
    last_status_hash: str
    last_checked_at: str
    last_verified_at: str


@dataclass(frozen=True)
class StatusReplayDecision:
    accepted: bool
    idempotent: bool
    errors: tuple[str, ...]
    record: StatusReplayRecord | None = None


def _parse_iso(value: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _safe_component(value: str) -> str:
    cleaned = _SAFE_KEY.sub("_", value.strip())
    return cleaned[:120] or "unknown"


def _record_key(tenant_id: str, grant_id: str, attestor_key_id: str) -> str:
    return hash_object(
        {
            "tenant_id": tenant_id,
            "grant_id": grant_id,
            "status_attestor_key_id": attestor_key_id,
        }
    ).removeprefix("sha256:")


class StatusReplayStore:
    """Filesystem-backed durable replay store for signed grant status."""

    def __init__(
        self,
        root: str | Path,
        *,
        max_checked_at_age_seconds: int | None = None,
        authorized_attestors: set[str] | frozenset[str] | None = None,
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_checked_at_age_seconds = (
            DEFAULT_MAX_CHECKED_AT_AGE_SECONDS
            if max_checked_at_age_seconds is None
            else max(0, int(max_checked_at_age_seconds))
        )
        self._authorized_attestors = (
            frozenset(str(x) for x in authorized_attestors)
            if authorized_attestors is not None
            else None
        )
        self._lock = threading.RLock()

    @classmethod
    def from_env(
        cls,
        *,
        max_checked_at_age_seconds: int | None = None,
        authorized_attestors: set[str] | frozenset[str] | None = None,
    ) -> StatusReplayStore | None:
        raw = os.environ.get("AKTA_STATUS_REPLAY_STORE_PATH", "").strip()
        if not raw:
            return None
        age = max_checked_at_age_seconds
        if age is None:
            env_age = os.environ.get("AKTA_MAX_GRANT_STATUS_AGE_SECONDS", "").strip()
            if env_age:
                try:
                    age = max(0, int(env_age))
                except ValueError:
                    age = DEFAULT_MAX_CHECKED_AT_AGE_SECONDS
        return cls(
            raw,
            max_checked_at_age_seconds=age,
            authorized_attestors=authorized_attestors,
        )

    def _path_for(
        self, tenant_id: str, grant_id: str, attestor_key_id: str
    ) -> Path:
        digest = _record_key(tenant_id, grant_id, attestor_key_id)
        tenant = _safe_component(tenant_id)
        return self.root / tenant / f"{digest}.json"

    def get(
        self, tenant_id: str, grant_id: str, attestor_key_id: str
    ) -> StatusReplayRecord | None:
        path = self._path_for(tenant_id, grant_id, attestor_key_id)
        with self._lock:
            if not path.is_file():
                return None
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, UnicodeError):
                return None
        if not isinstance(data, dict):
            return None
        try:
            return StatusReplayRecord(
                tenant_id=str(data["tenant_id"]),
                grant_id=str(data["grant_id"]),
                status_attestor_key_id=str(data["status_attestor_key_id"]),
                last_ledger_sequence=int(data["last_ledger_sequence"]),
                last_status_hash=str(data["last_status_hash"]),
                last_checked_at=str(data["last_checked_at"]),
                last_verified_at=str(data["last_verified_at"]),
            )
        except (KeyError, TypeError, ValueError):
            return None

    def _write(self, record: StatusReplayRecord) -> None:
        path = self._path_for(
            record.tenant_id, record.grant_id, record.status_attestor_key_id
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        payload = asdict(record)
        tmp.write_text(
            json.dumps(payload, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp.replace(path)

    def evaluate(
        self,
        *,
        tenant_id: str,
        grant_id: str,
        status_attestor_key_id: str,
        ledger_sequence: int,
        status_hash: str,
        checked_at: str,
        now: datetime | None = None,
        previously_seen_attestors: set[str] | frozenset[str] | None = None,
    ) -> StatusReplayDecision:
        """Apply acceptance rules without mutating untrusted grant objects."""
        errors: list[str] = []
        attestor = str(status_attestor_key_id)
        if not attestor:
            return StatusReplayDecision(
                accepted=False,
                idempotent=False,
                errors=("status attestor key id missing",),
            )

        if self._authorized_attestors is not None and attestor not in self._authorized_attestors:
            return StatusReplayDecision(
                accepted=False,
                idempotent=False,
                errors=(
                    f"unauthorized status attestor rotation/key: {attestor}",
                ),
            )

        checked_dt = _parse_iso(checked_at)
        if checked_dt is None:
            return StatusReplayDecision(
                accepted=False,
                idempotent=False,
                errors=(f"grant status checked_at invalid: {checked_at!r}",),
            )
        current = now or datetime.now(timezone.utc)
        age = (current - checked_dt).total_seconds()
        if age > self.max_checked_at_age_seconds:
            return StatusReplayDecision(
                accepted=False,
                idempotent=False,
                errors=(
                    "grant status attestation stale "
                    f"(age={int(age)}s > max={self.max_checked_at_age_seconds}s)",
                ),
            )

        # Rotation guard: if any prior attestor exists for this tenant/grant and
        # the new key is not authorized, reject.
        if previously_seen_attestors:
            prior = {str(x) for x in previously_seen_attestors if str(x)}
            if prior and attestor not in prior:
                if (
                    self._authorized_attestors is None
                    or attestor not in self._authorized_attestors
                ):
                    return StatusReplayDecision(
                        accepted=False,
                        idempotent=False,
                        errors=(
                            "changed status attestor outside authorized rotation",
                        ),
                    )

        try:
            seq = int(ledger_sequence)
        except (TypeError, ValueError):
            return StatusReplayDecision(
                accepted=False,
                idempotent=False,
                errors=(f"grant status ledger_sequence invalid: {ledger_sequence!r}",),
            )
        if not status_hash:
            return StatusReplayDecision(
                accepted=False,
                idempotent=False,
                errors=("grant status hash missing for replay store",),
            )

        with self._lock:
            existing = self.get(tenant_id, grant_id, attestor)
            if existing is None:
                record = StatusReplayRecord(
                    tenant_id=str(tenant_id),
                    grant_id=str(grant_id),
                    status_attestor_key_id=attestor,
                    last_ledger_sequence=seq,
                    last_status_hash=str(status_hash),
                    last_checked_at=str(checked_at),
                    last_verified_at=current.strftime("%Y-%m-%dT%H:%M:%SZ"),
                )
                self._write(record)
                return StatusReplayDecision(
                    accepted=True, idempotent=False, errors=(), record=record
                )

            if seq < existing.last_ledger_sequence:
                errors.append(
                    f"grant status ledger_sequence replay/out-of-order: {seq}"
                )
            elif seq == existing.last_ledger_sequence:
                if str(status_hash) != existing.last_status_hash:
                    errors.append(
                        "grant status ledger_sequence hash conflict "
                        f"(seq={seq})"
                    )
                else:
                    # Idempotent: refresh verified_at only.
                    record = StatusReplayRecord(
                        tenant_id=existing.tenant_id,
                        grant_id=existing.grant_id,
                        status_attestor_key_id=existing.status_attestor_key_id,
                        last_ledger_sequence=existing.last_ledger_sequence,
                        last_status_hash=existing.last_status_hash,
                        last_checked_at=existing.last_checked_at,
                        last_verified_at=current.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    )
                    self._write(record)
                    return StatusReplayDecision(
                        accepted=True,
                        idempotent=True,
                        errors=(),
                        record=record,
                    )
            else:
                record = StatusReplayRecord(
                    tenant_id=str(tenant_id),
                    grant_id=str(grant_id),
                    status_attestor_key_id=attestor,
                    last_ledger_sequence=seq,
                    last_status_hash=str(status_hash),
                    last_checked_at=str(checked_at),
                    last_verified_at=current.strftime("%Y-%m-%dT%H:%M:%SZ"),
                )
                self._write(record)
                return StatusReplayDecision(
                    accepted=True, idempotent=False, errors=(), record=record
                )

        return StatusReplayDecision(
            accepted=False, idempotent=False, errors=tuple(errors)
        )

    def list_attestors_for_grant(
        self, tenant_id: str, grant_id: str
    ) -> set[str]:
        """Return attestor key ids previously recorded for tenant/grant."""
        tenant_dir = self.root / _safe_component(tenant_id)
        found: set[str] = set()
        if not tenant_dir.is_dir():
            return found
        with self._lock:
            for path in tenant_dir.glob("*.json"):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError, UnicodeError):
                    continue
                if not isinstance(data, dict):
                    continue
                if str(data.get("grant_id")) != str(grant_id):
                    continue
                if str(data.get("tenant_id")) != str(tenant_id):
                    continue
                key = data.get("status_attestor_key_id")
                if key:
                    found.add(str(key))
        return found


def status_hash_for_replay(ledger_status: dict[str, Any]) -> str | None:
    """Prefer attestation/status hash fields; else hash unsigned body."""
    for field_name in (
        "attestation_hash",
        "status_hash",
        "signed_payload_hash",
    ):
        value = ledger_status.get(field_name)
        if value:
            return str(value)
    body = {
        k: v
        for k, v in ledger_status.items()
        if k
        not in {
            "attestation_hash",
            "attestation_signature",
            "signed_payload_hash",
            "status_hash",
            "signature",
        }
    }
    if not body:
        return None
    return hash_object(body)


__all__ = [
    "StatusReplayDecision",
    "StatusReplayRecord",
    "StatusReplayStore",
    "status_hash_for_replay",
]
