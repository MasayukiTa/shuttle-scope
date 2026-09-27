"""Canonical UUID validation for cross-device row identity."""
from __future__ import annotations

import uuid
from typing import Any, Optional


def canonical_identity_uuid(value: Any) -> Optional[str]:
    """Return canonical lowercase hyphenated UUID, or None for invalid input.

    Cross-device sync uses UUID strings as row identity. Accepting arbitrary
    strings here lets non-UUID values participate in identity lookup and
    conflict resolution. Normal UUID text is accepted case-insensitively but
    must use the canonical 36-character hyphenated shape.
    """
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if len(raw) != 36:
        return None
    try:
        parsed = uuid.UUID(raw)
    except (ValueError, AttributeError):
        return None
    canonical = str(parsed)
    if raw.lower() != canonical:
        return None
    return canonical
