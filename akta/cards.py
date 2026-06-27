"""AKTA Card validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from akta.errors import SchemaValidationError
from akta.records import validate_against_schema


def validate_card(card: dict[str, Any]) -> None:
    """Validate an AKTA Card against schema."""
    try:
        validate_against_schema(card, "akta_card.schema.json")
    except SchemaValidationError:
        raise
    except Exception as exc:
        raise SchemaValidationError(str(exc)) from exc

    if not card.get("non_certification_statement"):
        raise SchemaValidationError("AKTA Card must include non_certification_statement.")


def validate_card_file(path: str | Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        card = json.load(f)
    validate_card(card)
    return card
