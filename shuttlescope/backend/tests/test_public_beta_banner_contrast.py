"""公開サイトのβバナーが、ライト/ダーク両テーマで読めること (WCAG AA)。

以前は背景が --ss-t1 (ダークでは明色 #e6e9ed に反転) で文字が白だったため、
ダークの全公開ページでバナー文字が背景と同化していた。専用トークン
--beta-bg / --beta-fg に分け、テーマごとに十分なコントラストを持たせている。
"""
from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from backend.db.database import get_db
from backend.main import app


def _lum(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    rgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _contrast(a: str, b: str) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


@pytest.fixture()
def page_css(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        client = TestClient(app)
        out = {}
        for path in ("/terms", "/privacy", "/contact"):
            resp = client.get(path)
            assert resp.status_code == 200, path
            out[path] = resp.text
        yield out
    finally:
        app.dependency_overrides.clear()


def test_banner_uses_dedicated_tokens_not_ss_t1(page_css):
    for path, html in page_css.items():
        banner = re.search(r"\.beta-banner\{([^}]*)\}", html)
        assert banner, path
        assert "var(--beta-bg)" in banner.group(1), path
        assert "--ss-t1" not in banner.group(1), path
        text = re.search(r"\.beta-text\{([^}]*)\}", html)
        assert text and "var(--beta-fg)" in text.group(1), path


def _theme_tokens(html: str, theme: str) -> dict[str, str]:
    sel = r':root,\[data-theme="light"\]' if theme == "light" else r'\[data-theme="dark"\]'
    for m in re.finditer(sel + r"\{([^}]*--beta-bg[^}]*)\}", html):
        return dict(re.findall(r"(--beta-[a-z-]+):(#[0-9a-fA-F]{6})", m.group(1)))
    raise AssertionError(f"{theme} beta tokens not found")


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_banner_contrast_meets_wcag_aa(page_css, theme):
    for path, html in page_css.items():
        tok = _theme_tokens(html, theme)
        assert tok["--beta-fg"].lower() != tok["--beta-bg"].lower(), (path, theme)
        assert _contrast(tok["--beta-fg"], tok["--beta-bg"]) >= 4.5, (path, theme)
        assert _contrast(tok["--beta-fg-strong"], tok["--beta-bg"]) >= 4.5, (path, theme)
        # バッジ文字は 11px なので通常文字として AA を要求する
        assert _contrast(tok["--beta-fg-strong"], tok["--beta-badge-bg"]) >= 4.5, (path, theme)
