from __future__ import annotations

import uuid

import pytest

from backend.utils.server_video_ref import (
    parse_server_video_ref,
    resolve_server_video_path,
)


def test_hyphenated_uuid_is_reconstructed(tmp_path):
    uid = str(uuid.uuid4())
    ref, path = resolve_server_video_path(tmp_path, f"server://{uid}.MP4")
    assert ref.upload_id == uid
    assert ref.filename == f"{uid}.mp4"
    assert path == (tmp_path / f"{uid}.mp4").resolve()


def test_hex_uuid_legacy_form_is_preserved(tmp_path):
    uid = uuid.uuid4().hex
    ref, path = resolve_server_video_path(tmp_path, f"server://{uid}.mov")
    assert ref.upload_id == uid
    assert path.name == f"{uid}.mov"


@pytest.mark.parametrize(
    "raw",
    [
        "server://../outside.mp4",
        "server://sub/dir.mp4",
        r"server://sub\dir.mp4",
        "server://not-a-uuid.mp4",
        "server://{00000000-0000-0000-0000-000000000000}.mp4",
        "server://00000000-0000-0000-0000-000000000000.exe",
        "server://00000000-0000-0000-0000-000000000000.mp4 ",
        "https://example.com/video.mp4",
        "server://",
    ],
)
def test_malformed_refs_are_rejected(raw):
    with pytest.raises(ValueError):
        parse_server_video_ref(raw)
