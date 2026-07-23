"""Persistent artifact + audit stores for institutional REST mode (P1-C)."""

from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Protocol


class ArtifactStore(Protocol):
    def put(self, kind: str, data: dict[str, Any], *, tenant_id: str, caller_id: str) -> str: ...

    def get(self, artifact_id: str, *, tenant_id: str, caller_id: str, role: str) -> dict[str, Any] | None: ...


class AuditLedger(Protocol):
    def append(self, entry: dict[str, Any]) -> None: ...


class InMemoryArtifactStore:
    """Development-local only. Forbidden as sole store in institutional-service."""

    def __init__(self) -> None:
        self._items: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def put(self, kind: str, data: dict[str, Any], *, tenant_id: str, caller_id: str) -> str:
        artifact_id = f"AKTA-{kind.upper()}-{uuid.uuid4().hex[:12]}"
        with self._lock:
            self._items[artifact_id] = {
                "kind": kind,
                "data": data,
                "tenant_id": tenant_id,
                "caller_id": caller_id,
                "created_at": time.time(),
            }
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
        return {"kind": item["kind"], "data": item["data"], "tenant_id": item["tenant_id"]}


class InMemoryAuditLedger:
    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def append(self, entry: dict[str, Any]) -> None:
        with self._lock:
            self.entries.append(dict(entry))


class FileArtifactStore:
    """Durable JSON artifact store bound to tenant + caller permissions."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, artifact_id: str) -> Path:
        safe = "".join(c for c in artifact_id if c.isalnum() or c in "-_")
        return self.root / f"{safe}.json"

    def put(self, kind: str, data: dict[str, Any], *, tenant_id: str, caller_id: str) -> str:
        artifact_id = f"AKTA-{kind.upper()}-{uuid.uuid4().hex[:12]}"
        payload = {
            "artifact_id": artifact_id,
            "kind": kind,
            "data": data,
            "tenant_id": tenant_id,
            "caller_id": caller_id,
            "created_at": time.time(),
        }
        path = self._path(artifact_id)
        with self._lock:
            path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
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
        return {"kind": item["kind"], "data": item["data"], "tenant_id": item["tenant_id"]}


class FileAuditLedger:
    """Append-only JSONL audit ledger for institutional-service mode."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def append(self, entry: dict[str, Any]) -> None:
        line = json.dumps(entry, default=str)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")


__all__ = [
    "ArtifactStore",
    "AuditLedger",
    "FileArtifactStore",
    "FileAuditLedger",
    "InMemoryArtifactStore",
    "InMemoryAuditLedger",
]
