from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from backend.tracknet import setup as tracknet_setup


def _source(path: Path, payload: bytes) -> dict[Path, dict[str, str]]:
    return {
        path: {
            "url": f"{tracknet_setup.BASE_URL}/TrackNet.index",
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
    }


def test_upstream_checkpoint_is_commit_pinned() -> None:
    assert len(tracknet_setup.UPSTREAM_COMMIT) == 40
    assert "/main/" not in tracknet_setup.BASE_URL
    assert tracknet_setup.UPSTREAM_COMMIT in tracknet_setup.BASE_URL


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "https://example.invalid/TrackNet.index",
        (
            "https://raw.githubusercontent.com.evil.invalid/"
            "Chang-Chia-Chi/TrackNet-Badminton-Tracking-tensorflow2/"
            f"{tracknet_setup.UPSTREAM_COMMIT}/weights/TrackNet.index"
        ),
        (
            "https://raw.githubusercontent.com/"
            "Chang-Chia-Chi/TrackNet-Badminton-Tracking-tensorflow2/"
            "main/weights/TrackNet.index"
        ),
        f"{tracknet_setup.BASE_URL}/TrackNet.index?download=1",
        f"{tracknet_setup.BASE_URL}/TrackNet.index#fragment",
    ],
)
def test_weight_url_rejects_untrusted_locations(url: str) -> None:
    with pytest.raises(ValueError, match="Untrusted TrackNet checkpoint URL"):
        tracknet_setup._validated_weight_url(url)


@pytest.mark.parametrize(
    "name",
    ["TrackNet.index", "TrackNet.data-00000-of-00001"],
)
def test_weight_url_accepts_only_pinned_checkpoint_objects(name: str) -> None:
    url = f"{tracknet_setup.BASE_URL}/{name}"
    assert tracknet_setup._validated_weight_url(url) == url


def test_verified_cached_weight_skips_network(tmp_path, monkeypatch) -> None:
    payload = b"trusted-checkpoint"
    target = tmp_path / "TrackNet.index"
    target.write_bytes(payload)
    monkeypatch.setattr(tracknet_setup, "WEIGHT_SOURCES", _source(target, payload))

    def _unexpected_download(*_args, **_kwargs):
        raise AssertionError("verified cache must not hit network")

    monkeypatch.setattr(tracknet_setup.urllib.request, "urlretrieve", _unexpected_download)

    tracknet_setup.cmd_download()

    assert target.read_bytes() == payload
    assert not target.with_name(target.name + ".part").exists()


def test_corrupt_cached_weight_is_replaced_only_after_hash_verification(
    tmp_path, monkeypatch
) -> None:
    trusted = b"trusted-checkpoint"
    target = tmp_path / "TrackNet.index"
    target.write_bytes(b"corrupt-cache")
    monkeypatch.setattr(tracknet_setup, "WEIGHT_SOURCES", _source(target, trusted))

    def _download(_url: str, destination: Path):
        Path(destination).write_bytes(trusted)
        return str(destination), None

    monkeypatch.setattr(tracknet_setup.urllib.request, "urlretrieve", _download)

    tracknet_setup.cmd_download()

    assert target.read_bytes() == trusted
    assert not target.with_name(target.name + ".part").exists()


def test_hash_mismatch_never_promotes_downloaded_weight(tmp_path, monkeypatch) -> None:
    trusted = b"trusted-checkpoint"
    target = tmp_path / "TrackNet.index"
    monkeypatch.setattr(tracknet_setup, "WEIGHT_SOURCES", _source(target, trusted))

    def _download(_url: str, destination: Path):
        Path(destination).write_bytes(b"attacker-controlled")
        return str(destination), None

    monkeypatch.setattr(tracknet_setup.urllib.request, "urlretrieve", _download)

    with pytest.raises(RuntimeError, match="SHA256 mismatch"):
        tracknet_setup.cmd_download()

    assert not target.exists()
    assert not target.with_name(target.name + ".part").exists()
