"""Canonical hashing utilities for AKTA artifacts."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(data: Any) -> str:
    """Serialize data to canonical JSON for hashing."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_hex(data: str | bytes) -> str:
    """Return sha256: prefixed hex digest."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    digest = hashlib.sha256(data).hexdigest()
    return f"sha256:{digest}"


def hash_object(data: Any) -> str:
    """Hash a JSON-serializable object."""
    return sha256_hex(canonical_json(data))


def hash_file_content(content: str | bytes) -> str:
    """Hash raw file content."""
    return sha256_hex(content)
