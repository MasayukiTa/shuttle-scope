"""Strict parser/resolver for ShuttleScope server:// video references."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from backend.utils.safe_path import safe_path


VIDEO_EXTENSIONS = frozenset({
    ".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi", ".mpg", ".mpeg",
})


@dataclass(frozen=True)
class ServerVideoRef:
    filename: str
    upload_id: str
    suffix: str


def parse_server_video_ref(raw: str) -> ServerVideoRef:
    """Parse server://{uuid}{ext} and rebuild safe components.

    Hyphenated UUIDs and legacy uuid.hex are accepted. Other textual UUID
    aliases, separators, traversal, and non-video extensions fail closed.
    """
    if not isinstance(raw, str) or not raw.startswith("server://"):
        raise ValueError("not a server video reference")

    payload = raw[len("server://"):]
    if not payload or payload != payload.strip():
        raise ValueError("invalid server video filename")
    if "/" in payload or "\\" in payload or ".." in payload or "\x00" in payload:
        raise ValueError("invalid server video filename")

    suffix = Path(payload).suffix.lower()
    if suffix not in VIDEO_EXTENSIONS:
        raise ValueError("unsupported server video extension")
    stem = payload[:-len(suffix)]
    if not stem:
        raise ValueError("missing server video UUID")

    try:
        parsed = uuid.UUID(stem)
    except (ValueError, AttributeError) as exc:
        raise ValueError("invalid server video UUID") from exc

    lower = stem.lower()
    if lower == parsed.hex:
        safe_id = parsed.hex
    elif lower == str(parsed):
        safe_id = str(parsed)
    else:
        raise ValueError("non-canonical server video UUID")

    return ServerVideoRef(
        filename=f"{safe_id}{suffix}",
        upload_id=safe_id,
        suffix=suffix,
    )


def resolve_server_video_path(upload_dir: Path, raw: str) -> tuple[ServerVideoRef, Path]:
    """Resolve a validated server reference inside upload_dir."""
    ref = parse_server_video_ref(raw)
    return ref, safe_path(Path(upload_dir), ref.filename)
