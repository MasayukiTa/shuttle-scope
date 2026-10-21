"""公開トップ (home.html.j2) の主 CTA・分析方法の置き場所・aria-label 日英化の検証。

トップは日英を 1 つの HTML に持ち、html[lang] と JS で切り替える。
そのためここでは描画した HTML 文字列を直接検査する (DB 不要)。
"""
import re

from backend.config import settings
from backend.routers import public_site

REGISTER_HREF = "https://app.shuttle-scope.com/#/register"


def _render(monkeypatch, enabled: int) -> str:
    monkeypatch.setattr(settings, "ss_registration_enabled", enabled, raising=False)
    return public_site._render_home_str()


def _hero(html: str) -> str:
    start = html.index('<section class="hero">')
    return html[start:html.index("</section>", start)]


def test_home_shows_registration_cta_when_enabled(monkeypatch):
    html = _render(monkeypatch, 1)
    hero = _hero(html)
    # 主 CTA は登録。リンク先はアプリの実在ルート (#/register)
    assert f'<a href="{REGISTER_HREF}" class="btn-cta">' in hero
    assert "β版を試す(無料で登録)" in hero
    assert "Try the beta (free sign-up)" in hero
    # 承認制の説明が CTA の近くにある
    assert "登録後、内容を確認してから利用できるようになります。" in hero
    assert "Your account becomes usable after it has been reviewed." in hero
    # お問い合わせは副 CTA として残る
    assert 'href="/contact" class="btn-cta-sub"' in hero
    # フッターの新規登録リンクも出る
    assert html.count(REGISTER_HREF) >= 4


def test_home_falls_back_to_contact_cta_when_registration_disabled(monkeypatch):
    html = _render(monkeypatch, 0)
    hero = _hero(html)
    assert f'href="{REGISTER_HREF}"' not in html
    assert "β版を試す" not in html
    assert '<a href="/contact" class="btn-cta">' in hero
    assert "お問い合わせ" in hero


def test_home_registration_flag_failure_falls_back_to_contact(monkeypatch):
    def boom():
        raise RuntimeError("flag unavailable")

    monkeypatch.setattr("backend.routers.auth_email._registration_enabled", boom)
    html = public_site._render_home_str()
    assert f'href="{REGISTER_HREF}"' not in html
    assert '<a href="/contact" class="btn-cta">' in _hero(html)


def test_algorithm_names_are_not_in_main_body(monkeypatch):
    html = _render(monkeypatch, 1)
    details = re.search(r'<details class="method">.*?</details>', html, re.S)
    assert details is not None
    body_without_method = html.replace(details.group(0), "")
    for name in ("Markov", "EPV"):
        assert name not in body_without_method
        assert name in details.group(0)
    # 本文には不確実性の方針が残る
    assert "断定はしません" in body_without_method
    assert "never presented as certain" in body_without_method


def test_theme_toggle_aria_label_is_localized(monkeypatch):
    html = _render(monkeypatch, 1)
    button = re.search(r'<button class="theme-toggle"[^>]*>', html).group(0)
    assert 'aria-label="テーマ切り替え"' in button
    assert 'data-label-ja="テーマ切り替え"' in button
    assert 'data-label-en="Switch between light and dark theme"' in button
    # 英語表示のときに data-label-<lang> を aria-label へ反映するスクリプトがある
    assert "getAttribute('data-label-'+lang)" in html
    assert "setAttribute('aria-label',t)" in html
