"""Persistent artifact + audit stores for REST modes (P1-C / WS13).

Production institutional path is PostgreSQL (atomic writes, tenant constraints,
unique IDs, artifact hashes, source linkage, schema versions, transactional
hash-chained audit).

Optional dependency: ``psycopg`` (v3) — install via ``pip install 'akta-protocol[rest]'``.

CI / offline tests may use in-memory, file, or SQLite fallbacks. SQLite is never
accepted as the institutional production store.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Protocol

from akta.hash import hash_object

ARTIFACT_SCHEMA_VERSION = "akta-rest-artifact-v1"
AUDIT_SCHEMA_VERSION = "akta-rest-audit-v1"


class ArtifactStore(Protocol):
    def put(
        self,
        kind: str,
        data: dict[str, Any],
        *,
        tenant_id: str,
        caller_id: str,
        source_artifact_id: str | None = None,
        schema_version: str | None = None,
    ) -> str: ...

    def get(
        self, artifact_id: str, *, tenant_id: str, caller_id: str, role: str
    ) -> dict[str, Any] | None: ...


class AuditLedger(Protocol):
    def append(self, entry: dict[str, Any]) -> None: ...


def _collision_resistant_id(kind: str) -> str:
    return f"AKTA-{kind.upper()}-{uuid.uuid4().hex}-{uuid.uuid4().hex[:8]}"


def _artifact_hash(data: dict[str, Any]) -> str:
    return hash_object(data)


def _normalize_stored(
    *,
    artifact_id: str,
    kind: str,
    data: dict[str, Any],
    tenant_id: str,
    caller_id: str,
    source_artifact_id: str | None,
    schema_version: str | None,
) -> dict[str, Any]:
    return {
        "artifact_id": artifact_id,
        "kind": kind,
        "data": data,
        "tenant_id": tenant_id,
        "caller_id": caller_id,
        "created_at": time.time(),
        "artifact_hash": _artifact_hash(data),
        "source_artifact_id": source_artifact_id,
        "schema_version": schema_version or ARTIFACT_SCHEMA_VERSION,
    }


class InMemoryArtifactStore:
    """Development-local only. Forbidden as sole store in institutional-service."""

    def __init__(self) -> None:
        self._items: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def put(
        self,
        kind: str,
        data: dict[str, Any],
        *,
        tenant_id: str,
        caller_id: str,
        source_artifact_id: str | None = None,
        schema_version: str | None = None,
    ) -> str:
        artifact_id = _collision_resistant_id(kind)
        payload = _normalize_stored(
            artifact_id=artifact_id,
            kind=kind,
            data=data,
            tenant_id=tenant_id,
            caller_id=caller_id,
            source_artifact_id=source_artifact_id,
            schema_version=schema_version,
        )
        with self._lock:
            self._items[artifact_id] = payload
        return artifact_id

    def get(
        self, artifact_id: str, *, tenant_id: str, caller_id: str, role: str
    ) -> dict[str, Any] | None:
        with self._lock:
            item = self._items.get(artifact_id)
        if item is None:
            return None
        if item.get("tenant_id") != tenant_id:
            return None
        if role not in {"admin", "auditor"} and item.get("caller_id") != caller_id:
            return None
        return {
            "kind": item["kind"],
            "data": item["data"],
            "tenant_id": item["tenant_id"],
            "artifact_hash": item.get("artifact_hash"),
            "source_artifact_id": item.get("source_artifact_id"),
            "schema_version": item.get("schema_version"),
        }


class InMemoryAuditLedger:
    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._prev_hash = "sha256:" + ("0" * 64)

    def append(self, entry: dict[str, Any]) -> None:
        with self._lock:
            record = dict(entry)
            record["audit_schema_version"] = AUDIT_SCHEMA_VERSION
            record["prev_hash"] = self._prev_hash
            record["entry_hash"] = hash_object(
                {k: v for k, v in record.items() if k != "entry_hash"}
            )
            self._prev_hash = record["entry_hash"]
            self.entries.append(record)


class FileArtifactStore:
    """Durable JSON artifact store for pilot-service / development."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, artifact_id: str) -> Path:
        safe = "".join(c for c in artifact_id if c.isalnum() or c in "-_")
        return self.root / f"{safe}.json"

    def put(
        self,
        kind: str,
        data: dict[str, Any],
        *,
        tenant_id: str,
        caller_id: str,
        source_artifact_id: str | None = None,
        schema_version: str | None = None,
    ) -> str:
        artifact_id = _collision_resistant_id(kind)
        payload = _normalize_stored(
            artifact_id=artifact_id,
            kind=kind,
            data=data,
            tenant_id=tenant_id,
            caller_id=caller_id,
            source_artifact_id=source_artifact_id,
            schema_version=schema_version,
        )
        path = self._path(artifact_id)
        tmp = path.with_suffix(".json.tmp")
        with self._lock:
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            os.replace(tmp, path)
        return artifact_id

    def get(
        self, artifact_id: str, *, tenant_id: str, caller_id: str, role: str
    ) -> dict[str, Any] | None:
        path = self._path(artifact_id)
        if not path.is_file():
            return None
        with self._lock:
            item = json.loads(path.read_text(encoding="utf-8"))
        if item.get("tenant_id") != tenant_id:
            return None
        if role not in {"admin", "auditor"} and item.get("caller_id") != caller_id:
            return None
        return {
            "kind": item["kind"],
            "data": item["data"],
            "tenant_id": item["tenant_id"],
            "artifact_hash": item.get("artifact_hash"),
            "source_artifact_id": item.get("source_artifact_id"),
            "schema_version": item.get("schema_version"),
        }


class FileAuditLedger:
    """Append-only JSONL audit ledger for pilot-service mode."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._prev_hash = self._load_tail_hash()

    def _load_tail_hash(self) -> str:
        if not self.path.is_file():
            return "sha256:" + ("0" * 64)
        last = "sha256:" + ("0" * 64)
        with self.path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    last = str(entry.get("entry_hash") or last)
                except json.JSONDecodeError:
                    continue
        return last

    def append(self, entry: dict[str, Any]) -> None:
        record = dict(entry)
        with self._lock:
            record["audit_schema_version"] = AUDIT_SCHEMA_VERSION
            record["prev_hash"] = self._prev_hash
            record["entry_hash"] = hash_object(
                {k: v for k, v in record.items() if k != "entry_hash"}
            )
            self._prev_hash = record["entry_hash"]
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, default=str) + "\n")


class SqliteArtifactStore:
    """CI/offline fallback only — not valid for institutional-service."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    caller_id TEXT NOT NULL,
                    artifact_hash TEXT NOT NULL,
                    source_artifact_id TEXT,
                    schema_version TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    data_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_artifacts_tenant ON artifacts(tenant_id)"
            )
            conn.commit()

    def put(
        self,
        kind: str,
        data: dict[str, Any],
        *,
        tenant_id: str,
        caller_id: str,
        source_artifact_id: str | None = None,
        schema_version: str | None = None,
    ) -> str:
        artifact_id = _collision_resistant_id(kind)
        payload = _normalize_stored(
            artifact_id=artifact_id,
            kind=kind,
            data=data,
            tenant_id=tenant_id,
            caller_id=caller_id,
            source_artifact_id=source_artifact_id,
            schema_version=schema_version,
        )
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO artifacts (
                    artifact_id, kind, tenant_id, caller_id, artifact_hash,
                    source_artifact_id, schema_version, created_at, data_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["artifact_id"],
                    payload["kind"],
                    payload["tenant_id"],
                    payload["caller_id"],
                    payload["artifact_hash"],
                    payload["source_artifact_id"],
                    payload["schema_version"],
                    payload["created_at"],
                    json.dumps(payload["data"]),
                ),
            )
            conn.commit()
        return artifact_id

    def get(
        self, artifact_id: str, *, tenant_id: str, caller_id: str, role: str
    ) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM artifacts WHERE artifact_id = ?",
                (artifact_id,),
            ).fetchone()
        if row is None:
            return None
        if row["tenant_id"] != tenant_id:
            return None
        if role not in {"admin", "auditor"} and row["caller_id"] != caller_id:
            return None
        return {
            "kind": row["kind"],
            "data": json.loads(row["data_json"]),
            "tenant_id": row["tenant_id"],
            "artifact_hash": row["artifact_hash"],
            "source_artifact_id": row["source_artifact_id"],
            "schema_version": row["schema_version"],
        }


class SqliteAuditLedger:
    """CI/offline hash-chained audit fallback — not institutional production."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, check_same_thread=False)

    def _init(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_entries (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    entry_hash TEXT NOT NULL UNIQUE,
                    prev_hash TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    entry_json TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def append(self, entry: dict[str, Any]) -> None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT entry_hash FROM audit_entries ORDER BY seq DESC LIMIT 1"
            ).fetchone()
            prev = row[0] if row else ("sha256:" + ("0" * 64))
            record = dict(entry)
            record["audit_schema_version"] = AUDIT_SCHEMA_VERSION
            record["prev_hash"] = prev
            record["entry_hash"] = hash_object(
                {k: v for k, v in record.items() if k != "entry_hash"}
            )
            conn.execute(
                """
                INSERT INTO audit_entries (entry_hash, prev_hash, created_at, entry_json)
                VALUES (?, ?, ?, ?)
                """,
                (
                    record["entry_hash"],
                    prev,
                    time.time(),
                    json.dumps(record, default=str),
                ),
            )
            conn.commit()


def _require_psycopg():
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise ImportError(
            "institutional PostgreSQL persistence requires psycopg. "
            "Install with: pip install 'akta-protocol[rest]'  (or pip install 'psycopg[binary]')"
        ) from exc
    return psycopg, dict_row


class PostgresArtifactStore:
    """Institutional PostgreSQL artifact store (atomic, tenant-constrained)."""

    def __init__(self, dsn: str | None = None) -> None:
        self.dsn = (
            dsn
            or os.environ.get("AKTA_REST_DATABASE_URL")
            or os.environ.get("DATABASE_URL")
            or ""
        ).strip()
        if not self.dsn:
            raise ValueError(
                "PostgreSQL artifact store requires AKTA_REST_DATABASE_URL or DATABASE_URL"
            )
        self._psycopg, self._dict_row = _require_psycopg()
        self._lock = threading.Lock()
        self._ensure_schema()

    def _connect(self):
        return self._psycopg.connect(self.dsn, row_factory=self._dict_row)

    def _ensure_schema(self) -> None:
        ddl = """
        CREATE TABLE IF NOT EXISTS akta_artifacts (
            artifact_id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            caller_id TEXT NOT NULL,
            artifact_hash TEXT NOT NULL,
            source_artifact_id TEXT REFERENCES akta_artifacts(artifact_id),
            schema_version TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            data_json JSONB NOT NULL,
            CONSTRAINT akta_artifacts_tenant_id_nonempty CHECK (tenant_id <> ''),
            CONSTRAINT akta_artifacts_hash_format CHECK (artifact_hash LIKE 'sha256:%')
        );
        CREATE UNIQUE INDEX IF NOT EXISTS uq_akta_artifacts_tenant_hash
            ON akta_artifacts (tenant_id, artifact_hash, kind);
        CREATE INDEX IF NOT EXISTS idx_akta_artifacts_tenant
            ON akta_artifacts (tenant_id);
        CREATE INDEX IF NOT EXISTS idx_akta_artifacts_source
            ON akta_artifacts (source_artifact_id);
        """
        with self._lock, self._connect() as conn:
            conn.execute(ddl)
            conn.commit()

    def put(
        self,
        kind: str,
        data: dict[str, Any],
        *,
        tenant_id: str,
        caller_id: str,
        source_artifact_id: str | None = None,
        schema_version: str | None = None,
    ) -> str:
        if not tenant_id:
            raise ValueError("tenant_id required for PostgreSQL artifact writes")
        artifact_id = _collision_resistant_id(kind)
        payload = _normalize_stored(
            artifact_id=artifact_id,
            kind=kind,
            data=data,
            tenant_id=tenant_id,
            caller_id=caller_id,
            source_artifact_id=source_artifact_id,
            schema_version=schema_version,
        )
        with self._lock, self._connect() as conn:
            with conn.transaction():
                conn.execute(
                    """
                    INSERT INTO akta_artifacts (
                        artifact_id, kind, tenant_id, caller_id, artifact_hash,
                        source_artifact_id, schema_version, data_json
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    """,
                    (
                        payload["artifact_id"],
                        payload["kind"],
                        payload["tenant_id"],
                        payload["caller_id"],
                        payload["artifact_hash"],
                        payload["source_artifact_id"],
                        payload["schema_version"],
                        json.dumps(payload["data"]),
                    ),
                )
        return artifact_id

    def get(
        self, artifact_id: str, *, tenant_id: str, caller_id: str, role: str
    ) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT kind, tenant_id, caller_id, artifact_hash, source_artifact_id,
                       schema_version, data_json
                FROM akta_artifacts
                WHERE artifact_id = %s AND tenant_id = %s
                """,
                (artifact_id, tenant_id),
            ).fetchone()
        if row is None:
            return None
        if role not in {"admin", "auditor"} and row["caller_id"] != caller_id:
            return None
        data = row["data_json"]
        if isinstance(data, str):
            data = json.loads(data)
        return {
            "kind": row["kind"],
            "data": data,
            "tenant_id": row["tenant_id"],
            "artifact_hash": row["artifact_hash"],
            "source_artifact_id": row["source_artifact_id"],
            "schema_version": row["schema_version"],
        }


class PostgresAuditLedger:
    """Transactional hash-chained audit ledger on PostgreSQL."""

    def __init__(self, dsn: str | None = None) -> None:
        self.dsn = (
            dsn
            or os.environ.get("AKTA_REST_DATABASE_URL")
            or os.environ.get("DATABASE_URL")
            or ""
        ).strip()
        if not self.dsn:
            raise ValueError(
                "PostgreSQL audit ledger requires AKTA_REST_DATABASE_URL or DATABASE_URL"
            )
        self._psycopg, self._dict_row = _require_psycopg()
        self._lock = threading.Lock()
        self._ensure_schema()

    def _connect(self):
        return self._psycopg.connect(self.dsn, row_factory=self._dict_row)

    def _ensure_schema(self) -> None:
        ddl = """
        CREATE TABLE IF NOT EXISTS akta_audit_entries (
            seq BIGSERIAL PRIMARY KEY,
            entry_hash TEXT NOT NULL UNIQUE,
            prev_hash TEXT NOT NULL,
            tenant_id TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            entry_json JSONB NOT NULL,
            CONSTRAINT akta_audit_hash_format CHECK (entry_hash LIKE 'sha256:%')
        );
        CREATE INDEX IF NOT EXISTS idx_akta_audit_tenant ON akta_audit_entries (tenant_id);
        """
        with self._lock, self._connect() as conn:
            conn.execute(ddl)
            conn.commit()

    def append(self, entry: dict[str, Any]) -> None:
        with self._lock, self._connect() as conn:
            with conn.transaction():
                row = conn.execute(
                    "SELECT entry_hash FROM akta_audit_entries ORDER BY seq DESC LIMIT 1"
                ).fetchone()
                prev = row["entry_hash"] if row else ("sha256:" + ("0" * 64))
                record = dict(entry)
                record["audit_schema_version"] = AUDIT_SCHEMA_VERSION
                record["prev_hash"] = prev
                record["entry_hash"] = hash_object(
                    {k: v for k, v in record.items() if k != "entry_hash"}
                )
                conn.execute(
                    """
                    INSERT INTO akta_audit_entries (entry_hash, prev_hash, tenant_id, entry_json)
                    VALUES (%s, %s, %s, %s::jsonb)
                    """,
                    (
                        record["entry_hash"],
                        prev,
                        record.get("tenant_id"),
                        json.dumps(record, default=str),
                    ),
                )


def build_stores_for_mode(
    mode: str,
    *,
    data_dir: str | Path,
    database_url: str | None = None,
) -> tuple[Any, Any, str, str]:
    """Return (artifacts, audit, artifact_kind, audit_kind) for a REST mode."""
    from adapters.generic_rest.identity import (
        DEVELOPMENT_LOCAL,
        INSTITUTIONAL_SERVICE,
        PILOT_SERVICE,
    )

    data_dir = Path(data_dir)
    dsn = (database_url or os.environ.get("AKTA_REST_DATABASE_URL") or "").strip()

    if mode == INSTITUTIONAL_SERVICE:
        artifacts = PostgresArtifactStore(dsn or None)
        audit = PostgresAuditLedger(dsn or None)
        return artifacts, audit, "postgresql", "postgresql"

    if mode == PILOT_SERVICE:
        # Prefer file stores; allow sqlite when explicitly requested for CI.
        if os.environ.get("AKTA_REST_USE_SQLITE", "").strip().lower() in (
            "1",
            "true",
            "yes",
        ):
            artifacts = SqliteArtifactStore(data_dir / "artifacts.sqlite")
            audit = SqliteAuditLedger(data_dir / "audit.sqlite")
            return artifacts, audit, "sqlite", "sqlite"
        artifacts = FileArtifactStore(data_dir / "artifacts")
        audit = FileAuditLedger(data_dir / "audit.jsonl")
        return artifacts, audit, "file", "file"

    if mode != DEVELOPMENT_LOCAL:
        raise ValueError(f"unknown REST mode for stores: {mode}")
    return InMemoryArtifactStore(), InMemoryAuditLedger(), "memory", "memory"


def verify_artifact_integrity(stored: dict[str, Any], *, expected_hash: str | None = None) -> list[str]:
    """Verify stored artifact hash (+ optional expected hash)."""
    errors: list[str] = []
    data = stored.get("data")
    if not isinstance(data, dict):
        return ["artifact data missing or not an object"]
    recomputed = _artifact_hash(data)
    stored_hash = stored.get("artifact_hash")
    if stored_hash and stored_hash != recomputed:
        errors.append(
            f"artifact_hash mismatch: stored={stored_hash!r} recomputed={recomputed!r}"
        )
    if expected_hash and expected_hash != recomputed:
        errors.append(
            f"expected artifact hash mismatch: expected={expected_hash!r} got={recomputed!r}"
        )
    return errors


__all__ = [
    "ARTIFACT_SCHEMA_VERSION",
    "AUDIT_SCHEMA_VERSION",
    "ArtifactStore",
    "AuditLedger",
    "FileArtifactStore",
    "FileAuditLedger",
    "InMemoryArtifactStore",
    "InMemoryAuditLedger",
    "PostgresArtifactStore",
    "PostgresAuditLedger",
    "SqliteArtifactStore",
    "SqliteAuditLedger",
    "build_stores_for_mode",
    "verify_artifact_integrity",
]
