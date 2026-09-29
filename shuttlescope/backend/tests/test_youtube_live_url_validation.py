# -*- coding: utf-8 -*-
"""round156 R156-S1 回帰テスト: /api/youtube_live/start の URL 検証.

防御層は 2 段:
  1. routers.youtube_live._validate_public_https_url
     (Pydantic StartRequest.url field_validator として効く)
  2. services.youtube_live_recorder._validate_drm_capture_url
     (create_drm_job 内の defense-in-depth)

両方が同じ規則で SSRF / scheme 混在 / embedded creds / 内部 IP / 制御文字を
reject することを担保する。
"""
from __future__ import annotations

import pytest

from backend.routers.youtube_live import _validate_public_https_url
from backend.services.youtube_live_recorder import _validate_drm_capture_url


# loopback / localhost / private / link-local / IPv6 ULA / unspecified / metadata
_SSRF_URLS = [
    "https://127.0.0.1/",
    "https://localhost/",
    "https://[::1]/",
    "https://0.0.0.0/",
    "https://10.0.0.1/",
    "https://192.168.0.1/",
    "https://172.16.0.1/",
    "https://169.254.169.254/latest/meta-data/",  # AWS IMDS
    "https://[fe80::1]/",                         # IPv6 link-local
    "https://[fc00::1]/",                         # IPv6 ULA
]

# scheme 違い / embedded creds / 制御文字
_SCHEME_AND_CRED_URLS = [
    "http://example.com/",              # http
    "ftp://example.com/",               # ftp
    "javascript:alert(1)",              # js
    "data:text/html,<script>",          # data
    "file:///etc/passwd",               # file
    "https://user:pass@example.com/",   # embedded creds
    "https://user@example.com/",        # embedded user only
    "https://example.com/\x00null",     # null byte
    "https://example.com/\nlog",        # newline
    "https://example.com/\rcr",         # CR
    "https://example.com/\x7fdel",      # DEL
]

_GOOD_URLS = [
    "https://example.com/",
    "https://www.youtube.com/watch?v=abc",
    "https://app.shuttle-scope.com/",
    "https://news.bbc.co.uk/article/123",
    "https://www.youtube-nocookie.com/embed/xyz",
]


@pytest.mark.parametrize("url", _SSRF_URLS)
def test_pydantic_layer_rejects_ssrf(url):
    """Pydantic 層 (StartRequest.url) が内部 IP を reject する."""
    with pytest.raises(ValueError):
        _validate_public_https_url(url)


@pytest.mark.parametrize("url", _SCHEME_AND_CRED_URLS)
def test_pydantic_layer_rejects_scheme_and_creds(url):
    """Pydantic 層が scheme 違い / embedded creds / 制御文字を reject する."""
    with pytest.raises(ValueError):
        _validate_public_https_url(url)


@pytest.mark.parametrize("url", _SSRF_URLS + _SCHEME_AND_CRED_URLS)
def test_drm_capture_defense_layer_rejects_all(url):
    """create_drm_job 内の防御層が同じ規則で reject する."""
    with pytest.raises(ValueError):
        _validate_drm_capture_url(url)


@pytest.mark.parametrize("url", _GOOD_URLS)
def test_good_urls_pass_both_layers(url):
    """正常 URL は両層を通過する."""
    out1 = _validate_public_https_url(url)
    out2 = _validate_drm_capture_url(url)
    assert out1 == url.strip()
    assert out2 == url.strip()


def test_drm_capture_layer_rejects_http_even_when_subprocess_layer_allows():
    """`_validate_url_for_subprocess` は http も許可するが、screen capture 経路
    (`_validate_drm_capture_url`) は https のみ許可する。"""
    from backend.services.youtube_live_recorder import _validate_url_for_subprocess
    # subprocess 用は http を通す (yt-dlp / ffmpeg 経路用)
    assert _validate_url_for_subprocess("http://example.com/") == "http://example.com/"
    # capture 用は reject
    with pytest.raises(ValueError):
        _validate_drm_capture_url("http://example.com/")


def test_oversize_url_rejected():
    """500 文字超は Pydantic Field の max_length で reject (動作確認のため
    Pydantic 検証経路を別途テスト)."""
    from backend.routers.youtube_live import StartRequest
    long_url = "https://example.com/" + "a" * 600
    with pytest.raises(Exception):
        StartRequest(url=long_url, quality="best")
