"""Public website pages and inquiry endpoints for shuttle-scope.com."""

from __future__ import annotations

import html
import json
import logging
import re
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from backend.config import settings
from backend.db.database import get_db
from backend.db.models import PublicInquiry, ContentReport, HealthSample
from backend.routers.status_page import compute_public_status
from backend.utils.auth import get_auth

logger = logging.getLogger(__name__)
router = APIRouter(tags=["public-site"])

PUBLIC_HOSTS = {"shuttle-scope.com", "www.shuttle-scope.com"}
_recent_contact_requests: dict[str, list[datetime]] = {}

# サイトアイコン / OG 画像を backend/public/ から配信（shuttle-scope.com からも Electron SPA からも利用）
_PUBLIC_ASSETS_DIR = Path(__file__).resolve().parent.parent / "public"

# public site の Jinja2 テンプレートディレクトリ。トップページ (home.html.j2) を含む
# 公開ページ全てを backend/templates/public/*.html.j2 から描画する (旧 _V7_HOME_HTML 定数は廃止)。
# autoescape は jinja2.Environment 経由で必ず有効化 (テンプレ内変数による XSS 防止)。
# 旧 Starlette は Jinja2Templates(autoescape=...) を受け付けないため、env を組んで渡す。
_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
from jinja2 import Environment, FileSystemLoader, select_autoescape  # noqa: E402
# autoescape は select_autoescape で html/htm/xml/j2 に対し明示有効化済み → XSS 防止済み (検証済み FP)。
_jinja_env = Environment(  # nosemgrep
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "htm", "xml", "j2"]),
)
_public_templates = Jinja2Templates(env=_jinja_env)  # Starlette requires directory XOR env


class PublicInquiryCreate(BaseModel):
    # extra フィールドを拒否して mass assignment 攻撃（is_admin/role/status 等の
    # 不正なフィールド混入）を防ぐ。
    model_config = {"extra": "forbid"}

    name: str = Field(min_length=1, max_length=120)
    organization: Optional[str] = Field(default=None, max_length=160)
    role: Optional[str] = Field(default=None, max_length=80)
    contact_reference: Optional[str] = Field(default=None, max_length=200)
    message: str = Field(min_length=10, max_length=4000)
    website: Optional[str] = Field(default=None, max_length=100)

    @field_validator("name", "organization", "role", "contact_reference", "message", mode="before")
    @classmethod
    def _sanitize_field(cls, v):
        if v is None:
            return v
        v = str(v).replace("\x00", "")
        # HTML タグ除去 (Stored XSS 対策 / admin 管理画面での安全表示)。
        # 1 パスでは <scr<!---->ipt> 等の obfuscation で残り物が出るため安定するまでループ。
        for _ in range(8):
            new_v = re.sub(r"<[^>]*>?", "", v)
            if new_v == v:
                break
            v = new_v
        v = v.replace(">", "")
        # BIDI override / ZWSP 等を拒否し、admin 管理画面で表示偽装されないようにする。
        from backend.utils.text_sanitize import reject_bidi_only
        reject_bidi_only(v, "field", max_len=4000)
        return v

    @field_validator("name", "organization", "role", "contact_reference", mode="after")
    @classmethod
    def _strip_newlines(cls, v):
        # Round 258 P2 fix: name/organization/role/contact_reference に \r\n を許すと
        # Slack/メール webhook 通知の line-based payload に "second forged inquiry"
        # を注入できる (例: name="ok\n---\nrole: admin" で受信側が偽の項目を表示)。
        # message は複数行が正当なので除外。
        if v is None:
            return v
        return str(v).replace("\r", "").replace("\n", " ").strip()


class PublicInquiryUpdate(BaseModel):
    status: str = Field(pattern="^(new|reviewed|resolved)$")
    admin_note: Optional[str] = Field(default=None, max_length=4000)


class PublicInquiryBulkDelete(BaseModel):
    """一括削除リクエスト。少なくとも 1 つのフィルタ条件を指定する必要がある。

    - ids: 指定 ID の通知を削除（選択削除）
    - statuses: 指定ステータス（例 ["resolved"]）に該当する通知を削除
    - created_before / created_after: ISO8601 日時。期間指定削除用
    """
    ids: Optional[list[int]] = Field(default=None, max_length=1000)
    statuses: Optional[list[str]] = Field(default=None, max_length=3)
    created_before: Optional[str] = Field(default=None, max_length=40)
    created_after: Optional[str] = Field(default=None, max_length=40)


class PublicInquiryOut(BaseModel):
    id: int
    name: str
    organization: Optional[str]
    role: Optional[str]
    contact_reference: Optional[str]
    message: str
    status: str
    admin_note: Optional[str]
    created_at: str
    # R42: ban_appeal 等のカテゴリ。admin UI で目立つタグ表示に使う。
    category: str = "general"


class BanAppealCreate(BaseModel):
    """誤 ban 申し立てフォーム (R42)。

    通常の inquiry より項目を絞り、攻撃者が大量送信できないよう厳しめ制限。
    実態は PublicInquiry に category="ban_appeal" で保存される。
    """
    model_config = {"extra": "forbid"}

    contact: str = Field(min_length=3, max_length=200)  # email / ハンドル
    recent_actions: str = Field(min_length=20, max_length=2000)  # 直近何をしたか
    website: Optional[str] = Field(default=None, max_length=100)  # honeypot




def _rewrite_preview_links(html_str: str) -> str:
    """プレビュー用にリンクを /public-preview/* へ書き換えた HTML 文字列を返す。"""
    html_str = html_str.replace('href="/"', 'href="/public-preview"')
    html_str = html_str.replace('href="/terms"', 'href="/public-preview/terms"')
    html_str = html_str.replace('href="/privacy"', 'href="/public-preview/privacy"')
    html_str = html_str.replace('href="/contact"', 'href="/public-preview/contact"')
    html_str = html_str.replace(
        '<link rel="canonical" href="https://shuttle-scope.com/">',
        '<link rel="canonical" href="https://shuttle-scope.com/"><meta name="robots" content="noindex,nofollow">',
    )
    return html_str


def _rewrite_preview_links_en(html_str: str) -> str:
    """EN プレビュー用にリンクを /public-preview/en/* へ書き換え、noindex を強制する。"""
    html_str = html_str.replace('href="/en"', 'href="/public-preview/en"')
    html_str = html_str.replace('href="/en/terms"', 'href="/public-preview/en/terms"')
    html_str = html_str.replace('href="/en/privacy"', 'href="/public-preview/en/privacy"')
    html_str = html_str.replace('href="/en/contact"', 'href="/public-preview/en/contact"')
    # canonical タグの直後に noindex を差し込む (canonical_path に関係なく強制)
    import re as _re
    html_str = _re.sub(
        r'(<link rel="canonical" href="https://shuttle-scope\.com[^"]*">)',
        r'\1<meta name="robots" content="noindex,nofollow">',
        html_str,
        count=1,
    )
    return html_str


def _public_login_href(request: Request, lang: str = "ja") -> str:
    # SPA の hash router は ?lang= を起動時の言語選択に使う (i18n.detectInitialLang)。
    # EN ページから来た場合は ?lang=en を付ける。
    if lang == "en":
        return "https://app.shuttle-scope.com/?lang=en#/login"
    return "https://app.shuttle-scope.com/#/login"


def should_serve_public_site(request: Request) -> bool:
    host = request.headers.get("host", "").split(":")[0].lower()
    return host in PUBLIC_HOSTS


def _render_home_str() -> str:
    """公開トップページ (旧 _V7_HOME_HTML) を Jinja テンプレートから描画する。

    内容は public/home.html.j2 に移管済み。変数注入はゼロのため全体を {% raw %} で
    囲んでおり、render 結果は旧定数とバイト同一になる。FileSystemLoader のキャッシュに
    任せ、起動時プリロードは行わない (テンプレ欠落時は get_template が分かりやすく送出)。"""
    return _jinja_env.get_template("public/home.html.j2").render()


def _inject_status_banner(home_html: str) -> str:
    """トップページ (public/home.html.j2) の beta-banner 直後 (hero の直前) に
    公開ステータスバナー partial を注入する。partial は base.html.j2 と共有の単一ソース。
    バナー描画失敗時はトップページが 500 にならないよう、無注入で返す (fail-open)。"""
    try:
        banner = _jinja_env.get_template("public/_status_banner.html.j2").render()
    except Exception as exc:  # noqa: BLE001
        logger.warning("status banner render failed: %s", exc)
        return home_html
    return home_html.replace('<section class="hero">', banner + '\n<section class="hero">', 1)


def render_public_home(request: Request) -> HTMLResponse:
    return HTMLResponse(_inject_status_banner(_render_home_str()))


def _render_status_str(request: Request, *, lang: str = "ja", preview: bool = False,
                       db: Optional[Session] = None) -> str:
    """公開ステータスページ (/status) を Jinja でレンダリングする。

    status dict は compute_public_status(db) を共有 (API /api/public/status と同一ロジック)。
    db 未指定 (プレビュー等) 時は operational の空状態でフォールバックする。"""
    if db is not None:
        status = compute_public_status(db)
        # 日次稼働履歴 (claude status 風バー) は重いので /status ページ描画時のみ付与する。
        try:
            from backend.services.status_monitor import compute_component_history
            hist = compute_component_history(db)
            for c in status.get("components", []):
                h = hist.get(c.get("key")) or {}
                c["history"] = h.get("days", [])
                c["uptime_pct"] = h.get("uptime_pct")
        except Exception:  # noqa: BLE001
            pass
    else:
        status = {
            "overall": "operational", "components": [], "active_incidents": [],
            "recent_incidents": [], "maintenance": [], "announcements": [], "checked_at": "",
        }
    canonical_path = "/en/status" if lang == "en" else "/status"
    context = {
        "request": request,
        "lang": lang,
        "canonical_path": canonical_path,
        "noindex": preview,
        "login_href": _public_login_href(request, lang=lang),
        "status": status,
    }
    resp = _public_templates.TemplateResponse(request, "public/status.html.j2", context)
    return resp.body.decode("utf-8")


def render_status_page(request: Request, db: Session, *, lang: str = "ja") -> HTMLResponse:
    return HTMLResponse(_render_status_str(request, lang=lang, db=db))


def _render_terms_str(request: Request, *, preview: bool = False) -> str:
    """PR2 (2026-05-26): Jinja2 テンプレートで /terms (JA) を描画する。

    既存挙動を維持するため canonical_path はデフォルト /terms。
    preview ルートは別途 _rewrite_preview_links で /public-preview/* に書き換えるため、
    canonical 自体は本番パスのまま (PR1 contact は preview canonical を切り替えていたが、
    既存の terms/privacy はそうしていなかったので無修正を選択)。
    """
    canonical_path = '/terms'
    context = {
        'request': request,
        'lang': 'ja',
        'canonical_path': canonical_path,
        'noindex': preview,
        'login_href': _public_login_href(request),
    }
    resp = _public_templates.TemplateResponse(request, 'public/terms.html.j2', context)
    return resp.body.decode('utf-8')


def render_terms_page(request: Request) -> HTMLResponse:
    return HTMLResponse(_render_terms_str(request))


def _render_privacy_str(request: Request, *, preview: bool = False) -> str:
    """PR2 (2026-05-26): Jinja2 テンプレートで /privacy (JA) を描画する。

    canonical_path / preview の取扱いは _render_terms_str と同じ方針。
    """
    canonical_path = '/privacy'
    context = {
        'request': request,
        'lang': 'ja',
        'canonical_path': canonical_path,
        'noindex': preview,
        'login_href': _public_login_href(request),
    }
    resp = _public_templates.TemplateResponse(request, 'public/privacy.html.j2', context)
    return resp.body.decode('utf-8')


def render_privacy_page(request: Request) -> HTMLResponse:
    return HTMLResponse(_render_privacy_str(request))


def _render_contact_str(request: Request, *, preview: bool = False) -> str:
    """PR1 (2026-05-26): Jinja2 テンプレートで /contact (JA) を描画する。

    既存挙動を維持するため、preview=True 時の canonical/noindex 切替と、
    submit_path (/api/public/contact) を context に渡す方式に置き換えた。
    """
    canonical_path = "/contact" if not preview else "/public-preview/contact"
    context = {
        "request": request,
        "lang": "ja",
        "submit_path": "/api/public/contact",
        "canonical_path": canonical_path,
        "noindex": preview,
        "login_href": _public_login_href(request),
    }
    # TemplateResponse は Response オブジェクトを返すので、body bytes を decode して
    # 既存の _rewrite_preview_links (str -> str) と互換にする。
    resp = _public_templates.TemplateResponse(request, "public/contact.html.j2", context)
    return resp.body.decode("utf-8")


def render_contact_page(request: Request, *, preview: bool = False) -> HTMLResponse:
    return HTMLResponse(_render_contact_str(request, preview=preview))


def render_public_preview_home(request: Request) -> HTMLResponse:
    return HTMLResponse(_rewrite_preview_links(_render_home_str()))


def _require_admin(request: Request) -> None:
    ctx = get_auth(request)
    if not ctx.is_admin:
        raise HTTPException(status_code=403, detail="admin role required")


def _client_ip(request: Request) -> str:
    """Round 258 R3 fix (VULN-3): CF-Connecting-IP は loopback (=cloudflared) 経由の
    リクエストのみで信用する。Cloudflare bypass / 直接 LAN アクセスでヘッダ偽造して
    レート制限を回避するパスを塞ぐ。"""
    from backend.utils.client_ip import trusted_client_ip
    return trusted_client_ip(request, default="unknown")


def _enforce_contact_rate_limit(request: Request) -> None:
    ip = _client_ip(request)
    now = datetime.utcnow()
    # 短期（15分窓）と長期（24時間窓）の二段階レート制限
    short_window = now - timedelta(minutes=15)
    long_window = now - timedelta(hours=24)
    all_recent = [ts for ts in _recent_contact_requests.get(ip, []) if ts >= long_window]
    short_recent = [ts for ts in all_recent if ts >= short_window]
    if len(short_recent) >= 2:
        raise HTTPException(status_code=429, detail="too many inquiries from the same address")
    if len(all_recent) >= 5:
        raise HTTPException(status_code=429, detail="too many inquiries from the same address")
    all_recent.append(now)
    _recent_contact_requests[ip] = all_recent


def _notify_inquiry(inquiry: PublicInquiry) -> None:
    # 優先順位:
    #   1. SS_NOTIFY_WEBHOOK_URL (settings.ss_notify_webhook_url) — 専用設定
    #   2. SS_ADMIN_NOTIFY_WEBHOOK_URL — 汎用 admin 通知 (auth_email と共用)
    # 2026-05-26: 「A 案 = 全部同じ webhook に流す」運用のため fallback 追加。
    # 別チャンネルに分けたくなったら SS_NOTIFY_WEBHOOK_URL を別途設定する。
    import os
    webhook = (settings.ss_notify_webhook_url or "").strip()
    if not webhook:
        webhook = (os.environ.get("SS_ADMIN_NOTIFY_WEBHOOK_URL", "") or "").strip()
    if not webhook:
        return
    # SSRF 対策を `validate_external_url` で統一:
    #  - http/https のみ (file://, ftp://, gopher:// 拒否)
    #  - 10/8, 172.16/12, 192.168/16, 127/8, 169.254/16 全プライベート IP 拒否
    #  - IPv4-mapped IPv6、短縮形 (127.1)、hex (0x7f000001)、decimal (2130706433) も
    #    DNS 解決と ipaddress 正規化で全て検出
    # 以前のブロックリストは個別ホスト名のみを見ていたため `10.0.0.1` / `127.1` が
    # すり抜け SSRF 可能だった (ラウンド16 で実確認)。
    from urllib.parse import urlparse
    parsed = urlparse(webhook)
    if parsed.scheme != "https":
        logger.warning("public inquiry webhook rejected: non-https scheme")
        return
    try:
        from backend.utils.safe_path import validate_external_url
        validate_external_url(webhook, field_name="ss_notify_webhook_url")
    except HTTPException as _exc:
        logger.warning("public inquiry webhook rejected: %s", _exc.detail)
        return
    except Exception as _exc:
        logger.warning("public inquiry webhook rejected: %s", _exc)
        return
    host = (parsed.hostname or "").lower()
    # 受信時刻を JST (UTC+9) で表示
    _JST = timezone(timedelta(hours=9))
    received_jst = datetime.now(tz=timezone.utc).astimezone(_JST).strftime("%Y-%m-%d %H:%M:%S JST")
    # GeoIP: ipapi.co (外部 API、失敗時は省略)
    ip_str = inquiry.ip_address or "unknown"
    geo_str = ""
    try:
        import ipaddress as _ipaddr
        try:
            ip_safe = str(_ipaddr.ip_address(ip_str))
        except (ValueError, TypeError):
            ip_safe = None
        if ip_safe is None:
            raise ValueError("invalid ip")
        geo_req = urllib.request.Request(
            f"https://ipapi.co/{ip_safe}/json/",
            headers={"User-Agent": "ShuttleScope/1.0"},
            method="GET",
        )
        # hardcoded https + IP validated via ipaddress above.
        geo_raw = urllib.request.urlopen(geo_req, timeout=3).read()  # nosec B310
        geo = json.loads(geo_raw)
        country = geo.get("country_name", "")
        region = geo.get("region", "")
        org = geo.get("org", "")
        geo_str = f"\ncountry: {country} / {region}\norg/ISP: {org}"
    except Exception:
        pass
    payload = {
        "text": (
            f"[{received_jst}] New ShuttleScope inquiry\n"
            f"IP: {ip_str}{geo_str}\n"
            f"UA: {(inquiry.user_agent or '-')[:120]}\n"
            "---\n"
            f"name: {inquiry.name}\n"
            f"organization: {inquiry.organization or '-'}\n"
            f"role: {inquiry.role or '-'}\n"
            f"contact: {inquiry.contact_reference or '-'}\n"
            f"message: {inquiry.message[:500]}"
        )
    }
    try:
        # Discord blocks the default Python-urllib User-Agent with 403.
        req = urllib.request.Request(
            webhook,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "User-Agent": "ShuttleScope-InquiryNotify/1.0 (+https://shuttle-scope.com)",
            },
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5).read()
    except Exception as exc:
        logger.warning("public inquiry webhook failed: %s", exc)



def _render_terms_str_en(request: Request) -> str:
    """PR3 (2026-05-26): Jinja 化。terms.html.j2 の lang='en' 分岐で描画。"""
    canonical_path = '/en/terms'
    context = {
        'request': request,
        'lang': 'en',
        'canonical_path': canonical_path,
        'noindex': False,
        'login_href': _public_login_href(request, lang='en'),
    }
    resp = _public_templates.TemplateResponse(request, 'public/terms.html.j2', context)
    return resp.body.decode('utf-8')



def _render_privacy_str_en(request: Request) -> str:
    """PR3 (2026-05-26): Jinja 化。privacy.html.j2 の lang='en' 分岐で描画。"""
    canonical_path = '/en/privacy'
    context = {
        'request': request,
        'lang': 'en',
        'canonical_path': canonical_path,
        'noindex': False,
        'login_href': _public_login_href(request, lang='en'),
    }
    resp = _public_templates.TemplateResponse(request, 'public/privacy.html.j2', context)
    return resp.body.decode('utf-8')



def _render_contact_str_en(request: Request) -> str:
    """PR3 (2026-05-26): Jinja 化。contact.html.j2 の lang='en' 分岐で描画。"""
    canonical_path = '/en/contact'
    context = {
        'request': request,
        'lang': 'en',
        'submit_path': '/api/public/contact',
        'canonical_path': canonical_path,
        'noindex': False,
        'login_href': _public_login_href(request, lang='en'),
    }
    resp = _public_templates.TemplateResponse(request, 'public/contact.html.j2', context)
    return resp.body.decode('utf-8')



def _serve_public_asset(filename: str, media_type: str):
    """backend/public/ 配下の静的ファイルを安全に配信する共通ハンドラ。"""
    path = _PUBLIC_ASSETS_DIR / filename
    if not path.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(str(path), media_type=media_type)


@router.get("/favicon.png")
async def favicon_png():
    return _serve_public_asset("favicon.png", "image/png")


@router.get("/favicon.ico")
async def favicon_ico():
    # real multi-size ICO (16/32/48 embedded)。Google crawler 等の strict 検証器
    # は ICO magic bytes を読むので、PNG を .ico として返してはいけない。
    return _serve_public_asset("favicon.ico", "image/x-icon")


@router.get("/favicon-16.png")
async def favicon_16():
    return _serve_public_asset("favicon-16.png", "image/png")


@router.get("/favicon-32.png")
async def favicon_32():
    return _serve_public_asset("favicon-32.png", "image/png")


@router.get("/favicon-48.png")
async def favicon_48():
    return _serve_public_asset("favicon-48.png", "image/png")


@router.get("/favicon-96.png")
async def favicon_96():
    return _serve_public_asset("favicon-96.png", "image/png")


@router.get("/favicon-192.png")
async def favicon_192():
    return _serve_public_asset("favicon-192.png", "image/png")


@router.get("/favicon-512.png")
async def favicon_512():
    return _serve_public_asset("favicon-512.png", "image/png")


@router.get("/apple-touch-icon.png")
async def apple_touch_icon_png():
    return _serve_public_asset("apple-touch-icon.png", "image/png")


@router.get("/apple-touch-icon-precomposed.png")
async def apple_touch_icon_precomposed():
    return _serve_public_asset("apple-touch-icon.png", "image/png")


@router.get("/og-image.png")
async def og_image_png():
    return _serve_public_asset("og-image.png", "image/png")


# トップページ hero の実アプリスクリーンショット (テーマ別 + retina 用 @2x)
@router.get("/hero-app-light.png")
async def hero_app_light_png():
    return _serve_public_asset("hero-app-light.png", "image/png")


@router.get("/hero-app-light@2x.png")
async def hero_app_light_2x_png():
    return _serve_public_asset("hero-app-light@2x.png", "image/png")


@router.get("/hero-app-dark.png")
async def hero_app_dark_png():
    return _serve_public_asset("hero-app-dark.png", "image/png")


@router.get("/hero-app-dark@2x.png")
async def hero_app_dark_2x_png():
    return _serve_public_asset("hero-app-dark@2x.png", "image/png")


@router.get("/public-preview")
async def public_preview(request: Request):
    return render_public_preview_home(request)


@router.get("/public-preview/terms")
async def public_preview_terms(request: Request):
    return HTMLResponse(_rewrite_preview_links(_render_terms_str(request)))


@router.get("/public-preview/privacy")
async def public_preview_privacy(request: Request):
    return HTMLResponse(_rewrite_preview_links(_render_privacy_str(request)))


@router.get("/public-preview/contact")
async def public_preview_contact(request: Request):
    return HTMLResponse(_rewrite_preview_links(_render_contact_str(request, preview=True)))


@router.get("/public-preview/status")
async def public_preview_status(request: Request, db: Session = Depends(get_db)):
    return HTMLResponse(_rewrite_preview_links(_render_status_str(request, lang="ja", preview=True, db=db)))


# EN プレビュールート (PR4): 既存 JA preview と同様 noindex + リンクを /public-preview/en/* に書き換える。
@router.get("/public-preview/en")
async def public_preview_en_home(request: Request):
    return HTMLResponse(_rewrite_preview_links_en(_render_home_str()))


@router.get("/public-preview/en/terms")
async def public_preview_en_terms(request: Request):
    return HTMLResponse(_rewrite_preview_links_en(_render_terms_str_en(request)))


@router.get("/public-preview/en/privacy")
async def public_preview_en_privacy(request: Request):
    return HTMLResponse(_rewrite_preview_links_en(_render_privacy_str_en(request)))


@router.get("/public-preview/en/contact")
async def public_preview_en_contact(request: Request):
    return HTMLResponse(_rewrite_preview_links_en(_render_contact_str_en(request)))


@router.get("/public-preview/en/status")
async def public_preview_en_status(request: Request, db: Session = Depends(get_db)):
    return HTMLResponse(_rewrite_preview_links_en(_render_status_str(request, lang="en", preview=True, db=db)))


@router.get("/terms")
async def terms_page(request: Request):
    return render_terms_page(request)


@router.get("/privacy")
async def privacy_page(request: Request):
    return render_privacy_page(request)


@router.get("/contact")
async def contact_page(request: Request):
    return render_contact_page(request)


@router.get("/status")
async def status_page_route(request: Request, db: Session = Depends(get_db)):
    return render_status_page(request, db, lang="ja")


# 英語ページ（ホームは同一HTML、URLが /en のまま残るのでJS側が英語モードで起動）
@router.get("/en")
async def en_home(request: Request):
    return render_public_home(request)


@router.get("/en/terms")
async def en_terms_page(request: Request):
    return HTMLResponse(_render_terms_str_en(request))


@router.get("/en/privacy")
async def en_privacy_page(request: Request):
    return HTMLResponse(_render_privacy_str_en(request))


@router.get("/en/contact")
async def en_contact_page(request: Request):
    return HTMLResponse(_render_contact_str_en(request))


@router.get("/en/status")
async def en_status_page_route(request: Request, db: Session = Depends(get_db)):
    return render_status_page(request, db, lang="en")


# ─── 稼働状況: 日次バーのドリルダウン (10分スロット詳細) ──────────────────────
# 公開ステータスページの 90 日バー (1 セグメント=1 日) をクリックした際に、その日の
# 10 分刻みの状態を返す公開エンドポイント。/api/public/* は anon 許可 (status と同様)。
# 公開してよい粗い up/down のみを返し、内部ホスト名/IP/メトリクス文言は一切出さない
# (HealthSample.metric / detail には CPU%/応答ms 等が入るため返却しない)。

_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SLOT_MINUTES = 10
_SLOTS_PER_DAY = 24 * 60 // _SLOT_MINUTES  # 144

# status_monitor と同じ語彙 (operational/degraded/down)。公開語彙はこの 4 値のみ。
_ST_OPERATIONAL, _ST_DEGRADED, _ST_DOWN, _ST_NODATA = "operational", "degraded", "down", "nodata"
# 日次バーと同じ「悪い方優先」の集約順位。1 スロット内に複数サンプルがある場合に使う。
_ST_RANK = {_ST_DOWN: 3, _ST_DEGRADED: 2, _ST_OPERATIONAL: 1}


def _compute_status_day_detail(db: Session, day: str, component: Optional[str] = None) -> dict:
    """指定日 (YYYY-MM-DD, JST 暦日) の health_samples を
    10 分スロット (1 日 144 個) へバケットし、各スロットの公開ステータス
    (operational/degraded/down/nodata) を返す。

    - component を指定するとそのコンポーネント (api/database/tunnel/gpu/worker) のみ。
      未指定なら全コンポーネントを「悪い方優先」で合成する (= 90日バー全体相当)。
      公開ページの各バーは component 別なので、クリックされたバーの component を渡す。
    - HealthSample.sampled_at は naive UTC (status_monitor が datetime.utcnow() で記録)。
      day は JST 暦日として解釈し、JST 00:00 を UTC に直した窓でスロット割り当てを行う
      (90 日バー compute_component_history と同じ JST 基準)。slot の時刻は UTC ISO で返し、
      表示の JST 変換はフロント側で行う (既存 status.html.j2 の time フォーマッタと同方針)。
    - 1 スロットに複数サンプルが入る場合は「悪い方優先」で集約する
      (日次バー compute_component_history と同じ方針)。
    - metric / detail は内部負荷情報なので返さない (公開は粗い状態のみ)。
    """
    # day は事前に正規表現で形式検証済みだが、2026-13-40 等の不正値を弾くため strptime で実在性も検証。
    try:
        d = datetime.strptime(day, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid date") from exc

    # day は JST 暦日。JST 00:00 を UTC に変換した窓 [start_utc, end_utc) で取得する。
    # (health_samples.sampled_at は naive UTC。90 日バー compute_component_history と同じ JST 基準。)
    jst = timedelta(hours=9)
    start_utc = datetime(d.year, d.month, d.day) - jst
    end_utc = start_utc + timedelta(days=1)
    from backend.services.status_monitor import severity_to_hex, _severity_from_status
    q = (
        db.query(HealthSample.sampled_at, HealthSample.status, HealthSample.severity)
        .filter(HealthSample.sampled_at >= start_utc, HealthSample.sampled_at < end_utc)
    )
    if component is not None:
        q = q.filter(HealthSample.component == component)
    rows = q.all()

    # スロット index -> 集約済みステータス (悪い方優先) + 最悪 severity。未観測は nodata。
    # 色は severity を補間する (90日バーと同じ連続グラデーション)。severity は内部の
    # CPU%/ms 等そのものではなく [0,1] の正規化値なので、公開しても生メトリクスは漏れない。
    slot_status: list[Optional[str]] = [None] * _SLOTS_PER_DAY
    slot_sev: list[float] = [0.0] * _SLOTS_PER_DAY
    for ts, st, sv in rows:
        if st not in _ST_RANK:
            # 想定外の値は operational 相当の最弱として扱わず無視 (公開語彙のみ採用)。
            continue
        # JST 暦日の開始 (start_utc) からの経過分で 10 分スロットへ割り当てる (ts は naive UTC)。
        idx = int((ts - start_utc).total_seconds() // 60) // _SLOT_MINUTES
        if idx < 0 or idx >= _SLOTS_PER_DAY:
            continue
        cur = slot_status[idx]
        if cur is None or _ST_RANK[st] > _ST_RANK[cur]:
            slot_status[idx] = st
        s = sv if sv is not None else _severity_from_status(st)
        if s > slot_sev[idx]:
            slot_sev[idx] = s

    slots = []
    counts = {_ST_OPERATIONAL: 0, _ST_DEGRADED: 0, _ST_DOWN: 0, _ST_NODATA: 0}
    for i in range(_SLOTS_PER_DAY):
        st = slot_status[i] or _ST_NODATA
        counts[st] += 1
        slot_start = start_utc + timedelta(minutes=i * _SLOT_MINUTES)
        slot = {
            # naive UTC ISO (オフセット無し)。フロントが既存フォーマッタで JST 表示する。
            "t": slot_start.isoformat(),
            "st": st,
        }
        if slot_status[i] is not None:
            slot["sev"] = round(slot_sev[i], 4)
            slot["color"] = severity_to_hex(slot_sev[i])
        slots.append(slot)
    # 未来日 / 未到来スロットの nodata は「障害」ではないことをフロントが区別できるよう、
    # 観測サンプルが 1 件も無い日は has_data=False を立てる。
    has_data = (counts[_ST_NODATA] < _SLOTS_PER_DAY)
    return {
        "day": d.isoformat(),
        "component": component,  # None = 全コンポーネント合成
        "slot_minutes": _SLOT_MINUTES,
        "slots": slots,
        "summary": counts,
        "has_data": has_data,
    }


@router.get("/api/public/status/day")
async def public_status_day(day: str, component: Optional[str] = None,
                            db: Session = Depends(get_db)):
    """公開ステータス: 指定日の 10 分刻み稼働詳細 (90 日バーのドリルダウン用)。

    認証不要 (/api/public/* は anon 許可)。
    - `day`: YYYY-MM-DD。形式不正/非実在日は 400。
    - `component`: 任意。api/database/tunnel/gpu/worker のいずれか。
      未知の値は 400 (列挙 probe 防止 + 不正フィルタ拒否)。未指定なら全合成。
    返すのは粗い状態 (operational/degraded/down/nodata) のみで、
    内部ホスト名/IP/負荷メトリクスは含めない。
    """
    if not isinstance(day, str) or not _DAY_RE.match(day):
        raise HTTPException(status_code=400, detail="invalid date format (expected YYYY-MM-DD)")
    if component is not None:
        # 既知のコンポーネントキーのみ許可 (status_monitor の定義に追従)。
        try:
            from backend.services.status_monitor import COMPONENT_KEYS
            allowed = set(COMPONENT_KEYS)
        except Exception:  # noqa: BLE001 — 監視未初期化でも公開ページは壊さない
            allowed = {"api", "database", "tunnel", "gpu", "worker"}
        if component not in allowed:
            raise HTTPException(status_code=400, detail="unknown component")
    return _compute_status_day_detail(db, day, component=component)


# /jp → / にリダイレクト
@router.get("/jp")
async def jp_redirect(request: Request):
    from fastapi.responses import RedirectResponse as _RR
    return _RR(url="/", status_code=301)


# /register, /login: public host (apex/www) では SPA を持たないため、
# app.shuttle-scope.com の SPA HashRouter (#/register, #/login) にリダイレクト。
# EN ページから来た場合は ?lang=en を付けて SPA 側で初期言語を英語に。
# SPA 側 (App.tsx) は ?lang= を i18n.changeLanguage に流す想定。
_APP_HOST = "https://app.shuttle-scope.com"


@router.get("/register")
async def register_redirect(request: Request):
    from fastapi.responses import RedirectResponse as _RR
    return _RR(url=f"{_APP_HOST}/#/register", status_code=302)


@router.get("/login")
async def login_redirect(request: Request):
    from fastapi.responses import RedirectResponse as _RR
    return _RR(url=f"{_APP_HOST}/#/login", status_code=302)


@router.get("/en/register")
async def en_register_redirect(request: Request):
    from fastapi.responses import RedirectResponse as _RR
    return _RR(url=f"{_APP_HOST}/?lang=en#/register", status_code=302)


@router.get("/en/login")
async def en_login_redirect(request: Request):
    from fastapi.responses import RedirectResponse as _RR
    return _RR(url=f"{_APP_HOST}/?lang=en#/login", status_code=302)


@router.post("/api/public/contact")
async def submit_public_contact(body: PublicInquiryCreate, request: Request, db: Session = Depends(get_db)):
    if body.website:
        raise HTTPException(status_code=400, detail="invalid submission")
    _enforce_contact_rate_limit(request)

    inquiry = PublicInquiry(
        name=body.name.strip(),
        organization=(body.organization or "").strip() or None,
        role=(body.role or "").strip() or None,
        contact_reference=(body.contact_reference or "").strip() or None,
        message=re.sub(r"[^\S\n]+\n", "\n", body.message.strip()),
        ip_address=_client_ip(request),
        user_agent=(request.headers.get("User-Agent") or "")[:400] or None,
    )
    db.add(inquiry)
    db.commit()
    db.refresh(inquiry)
    _notify_inquiry(inquiry)
    return {"success": True, "data": {"id": inquiry.id, "status": inquiry.status}}


# ─── R42: Ban appeal channel ──────────────────────────────────────────────
@router.post("/api/public/ban_appeal")
async def submit_ban_appeal(body: BanAppealCreate, request: Request, db: Session = Depends(get_db)):
    """誤 ban の申し立てを受け付ける。

    実装方針:
      - PublicInquiry に category="ban_appeal" で保存。admin 画面で目立つ
        タグ付けで表示される。
      - 攻撃者は通常この form を送らないので、送られて来た時点で「本物の
        false positive 候補」として扱う運用。
      - rate limit は通常の contact form と共通 (短時間連投を抑止)。
      - 入力は最小限 (contact + recent_actions) で、name は固定文字列。
    """
    if body.website:
        raise HTTPException(status_code=400, detail="invalid submission")
    _enforce_contact_rate_limit(request)

    ip = _client_ip(request)
    ua = (request.headers.get("User-Agent") or "")[:400] or None

    # message に WAF ban context (IP / UA / cf-ray) を埋め込んで運用側で
    # ban rule との突合せをしやすくする。生 UA は admin 画面で見える形で残す。
    cf_ray = (request.headers.get("cf-ray") or "")[:80]
    country = (request.headers.get("cf-ipcountry") or "?")[:8]
    composed = (
        f"[ban_appeal] from ip={ip} ray={cf_ray} country={country}\n"
        f"--- recent actions ---\n{body.recent_actions.strip()}"
    )

    inquiry = PublicInquiry(
        name="(ban appeal)",
        organization=None,
        role=None,
        contact_reference=body.contact.strip()[:200],
        message=composed,
        category="ban_appeal",
        ip_address=ip,
        user_agent=ua,
    )
    db.add(inquiry)
    db.commit()
    db.refresh(inquiry)
    _notify_inquiry(inquiry)
    return {"success": True, "data": {"id": inquiry.id, "status": inquiry.status}}


# ─── R42: Bilingual ban / appeal landing page ─────────────────────────────
_BAN_APPEAL_HTML = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>Access Blocked / アクセス遮断 — ShuttleScope</title>
<style>
  body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","MigMix 1P",sans-serif;background:#0b1220;color:#e6edf6;line-height:1.6}
  .wrap{max-width:680px;margin:0 auto;padding:48px 24px 80px}
  h1{font-size:28px;margin:0 0 8px;letter-spacing:.02em}
  h2{font-size:18px;margin:32px 0 12px;color:#9fc4ff;border-left:3px solid #4a7fcc;padding-left:10px}
  .lang-row{display:flex;gap:8px;margin:0 0 28px}
  .lang-btn{flex:1;text-align:center;padding:10px;border:1px solid #2a3a55;border-radius:4px;cursor:pointer;background:#121b2e;color:#cbd6e6;font-size:13px;user-select:none}
  .lang-btn.active{background:#1d2d4d;color:#fff;border-color:#4a7fcc}
  .card{background:#101a2c;border:1px solid #1f2c47;border-radius:6px;padding:24px;margin-bottom:20px}
  .muted{color:#8fa0b8;font-size:13px}
  label{display:block;margin:14px 0 6px;font-size:13px;color:#cbd6e6}
  input,textarea{width:100%;box-sizing:border-box;padding:10px 12px;background:#0a1426;border:1px solid #2a3a55;border-radius:4px;color:#e6edf6;font-size:14px;font-family:inherit}
  textarea{min-height:140px;resize:vertical}
  button[type=submit]{margin-top:18px;background:#2a5cb8;color:#fff;border:none;padding:12px 22px;border-radius:4px;font-size:14px;cursor:pointer;font-weight:600}
  button[type=submit]:hover{background:#3a6dd1}
  .hidden{display:none}
  .ok{color:#8fe6a0;margin-top:12px}
  .err{color:#ff9090;margin-top:12px}
  .ref{font-family:Consolas,monospace;font-size:12px;color:#6b7a92;margin-top:8px;word-break:break-all}
  .hp{position:absolute;left:-9999px}
</style>
</head>
<body>
<div class="wrap">

  <div class="lang-row">
    <div class="lang-btn active" data-lang="ja" onclick="setLang('ja')">日本語</div>
    <div class="lang-btn" data-lang="en" onclick="setLang('en')">English</div>
  </div>

  <!-- ─── 日本語 ─── -->
  <div id="ja-block">
    <h1>アクセスが遮断されました</h1>
    <p class="muted">このページは、ShuttleScope のセキュリティシステムにより自動的に通信が遮断された方向けの案内です。</p>

    <div class="card">
      <h2>何が起きたか</h2>
      <p>あなたのアクセスは、当サービスの異常検知 (canary endpoint や honeytoken の使用、典型的な侵入スキャナのパターンなど) に該当したため、自動的に Cloudflare 経由でブロックされました。</p>
      <p>通常のユーザーがこの画面を見ることは想定していません。</p>
    </div>

    <div class="card">
      <h2>誤ブロックだと思う場合</h2>
      <p>もしこれが誤検知であると思われる場合は、直前にあなたが行った操作 (URL / クリック / ツール / スクリプト) を具体的に記載して送信してください。攻撃者は通常この申請を行いません。本物の誤検知は手動で精査し、ブロックを解除します。</p>
      <p class="muted">送信内容と IP / User-Agent / Cloudflare Ray-ID は監査ログに記録されます。</p>

      <form id="form-ja" onsubmit="submitAppeal(event,'ja')">
        <label>連絡先 (メール / SNS ハンドル等)</label>
        <input name="contact" required minlength="3" maxlength="200" placeholder="you@example.com">

        <label>直前に行った操作 (URL や状況を具体的に)</label>
        <textarea name="recent_actions" required minlength="20" maxlength="2000" placeholder="例: https://shuttle-scope.com/ にアクセスし、お問い合わせフォームから送信したらこの画面になりました。"></textarea>

        <input class="hp" name="website" tabindex="-1" autocomplete="off">

        <button type="submit">申し立てを送信する</button>
        <div id="result-ja"></div>
      </form>
    </div>

    <p class="muted">継続的な不正アクセスや脅威行為と判定された場合、申し立ては受理されないことがあります。</p>
  </div>

  <!-- ─── English ─── -->
  <div id="en-block" class="hidden">
    <h1>Access Blocked</h1>
    <p class="muted">This page is shown to clients whose traffic has been automatically blocked by ShuttleScope's security system.</p>

    <div class="card">
      <h2>What happened</h2>
      <p>Your request matched one of our automated detections (canary endpoint hit, honeytoken usage, or a known intrusion-scanner pattern), and you were automatically blocked at the Cloudflare edge.</p>
      <p>Ordinary users are not expected to reach this page.</p>
    </div>

    <div class="card">
      <h2>If you believe this is a false positive</h2>
      <p>Please describe specifically what you were doing right before you were blocked (URLs, clicks, tools, scripts). Attackers will normally not file this appeal. Genuine false positives will be reviewed manually and unblocked.</p>
      <p class="muted">Your submission, IP address, User-Agent and Cloudflare Ray-ID will be stored in our audit log.</p>

      <form id="form-en" onsubmit="submitAppeal(event,'en')">
        <label>Contact (email / handle)</label>
        <input name="contact" required minlength="3" maxlength="200" placeholder="you@example.com">

        <label>Recent actions (URLs and context, be specific)</label>
        <textarea name="recent_actions" required minlength="20" maxlength="2000" placeholder="e.g. I opened https://shuttle-scope.com/ and submitted the contact form, then got this page."></textarea>

        <input class="hp" name="website" tabindex="-1" autocomplete="off">

        <button type="submit">Submit appeal</button>
        <div id="result-en"></div>
      </form>
    </div>

    <p class="muted">Appeals from sources showing repeated abusive behaviour may not be accepted.</p>
  </div>

</div>

<script>
function setLang(l){
  document.getElementById('ja-block').classList.toggle('hidden', l!=='ja');
  document.getElementById('en-block').classList.toggle('hidden', l!=='en');
  document.querySelectorAll('.lang-btn').forEach(b=>{
    b.classList.toggle('active', b.dataset.lang===l);
  });
}
async function submitAppeal(ev, lang){
  ev.preventDefault();
  const f = ev.target;
  const out = document.getElementById('result-'+lang);
  out.className=''; out.textContent='';
  const body = {
    contact: f.contact.value,
    recent_actions: f.recent_actions.value,
    website: f.website.value || null,
  };
  try{
    const r = await fetch('/api/public/ban_appeal', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify(body),
    });
    if(r.ok){
      out.className='ok';
      out.textContent = lang==='ja'
        ? '申し立てを受け付けました。内容を確認のうえ、必要に応じて連絡します。'
        : 'Your appeal has been received. We will review it and contact you if needed.';
      f.reset();
    } else {
      out.className='err';
      out.textContent = lang==='ja'
        ? '送信に失敗しました。時間をおいて再度お試しください。'
        : 'Submission failed. Please try again later.';
    }
  } catch(e){
    out.className='err';
    out.textContent = lang==='ja' ? '通信エラーが発生しました。' : 'Network error.';
  }
}
// ブラウザ言語で初期言語を決める
if((navigator.language||'').toLowerCase().startsWith('en')) setLang('en');
</script>
</body>
</html>"""


@router.get("/banned")
@router.get("/blocked")
@router.get("/appeal")
async def ban_appeal_page(request: Request):
    """誤 ban 申し立てページ (bilingual JP/EN)。

    Cloudflare の WAF Custom Error Page (1020 block 等) から
    https://shuttle-scope.com/appeal へリンクさせる運用を想定。
    本ページ自体は通常の origin で配信する (CF block 対象 IP からは
    edge で 403 が返るので、appeal はモバイル回線等の別 IP から行う前提)。
    """
    from fastapi.responses import HTMLResponse
    return HTMLResponse(_BAN_APPEAL_HTML)


@router.get("/api/public/inquiries")
async def list_public_inquiries(request: Request, db: Session = Depends(get_db)):
    _require_admin(request)
    items = db.query(PublicInquiry).order_by(PublicInquiry.created_at.desc()).all()
    return {
        "success": True,
        "data": [
            PublicInquiryOut(
                id=item.id,
                name=item.name,
                organization=item.organization,
                role=item.role,
                contact_reference=item.contact_reference,
                message=item.message,
                status=item.status,
                admin_note=item.admin_note,
                category=getattr(item, "category", "general") or "general",
                created_at=(
                    item.created_at.replace(tzinfo=timezone.utc)
                    .astimezone(timezone(timedelta(hours=9)))
                    .isoformat()
                    if item.created_at else ""
                ),
            ).model_dump()
            for item in items
        ],
    }


@router.get("/api/public/inquiries/unread-count")
async def public_inquiries_unread_count(request: Request, db: Session = Depends(get_db)):
    _require_admin(request)
    count = db.query(PublicInquiry).filter(PublicInquiry.status == "new").count()
    return {"success": True, "data": {"count": count}}


@router.patch("/api/public/inquiries/{inquiry_id}")
async def update_public_inquiry(inquiry_id: int, body: PublicInquiryUpdate, request: Request, db: Session = Depends(get_db)):
    _require_admin(request)
    inquiry = db.get(PublicInquiry, inquiry_id)
    if not inquiry:
        raise HTTPException(status_code=404, detail="inquiry not found")
    inquiry.status = body.status
    inquiry.admin_note = (body.admin_note or "").strip() or None
    db.commit()
    return {"success": True}


@router.delete("/api/public/inquiries/{inquiry_id}")
async def delete_public_inquiry(inquiry_id: int, request: Request, db: Session = Depends(get_db)):
    """単体削除。admin 専用。access_logs に削除を記録する。"""
    from backend.utils.access_log import log_access
    _require_admin(request)
    ctx = get_auth(request)
    inquiry = db.get(PublicInquiry, inquiry_id)
    if not inquiry:
        raise HTTPException(status_code=404, detail="inquiry not found")
    snapshot = {"id": inquiry.id, "name": inquiry.name, "status": inquiry.status}
    db.delete(inquiry)
    db.commit()
    log_access(
        db, "public_inquiry_deleted",
        user_id=ctx.user_id,
        resource_type="public_inquiry",
        resource_id=inquiry_id,
        details=snapshot,
        ip_addr=_client_ip(request),
    )
    return {"success": True, "data": {"deleted": 1}}


@router.post("/api/public/inquiries/bulk-delete")
async def bulk_delete_public_inquiries(
    body: PublicInquiryBulkDelete, request: Request, db: Session = Depends(get_db),
):
    """admin 専用。フィルタ条件に合致する通知を一括削除する。

    フィルタは AND で結合。少なくとも 1 つの条件（ids / statuses / 期間）が必要。
    """
    from backend.utils.access_log import log_access
    _require_admin(request)
    ctx = get_auth(request)

    q = db.query(PublicInquiry)
    has_filter = False

    if body.ids:
        q = q.filter(PublicInquiry.id.in_(body.ids))
        has_filter = True
    if body.statuses:
        allowed = {"new", "reviewed", "resolved"}
        invalid = [s for s in body.statuses if s not in allowed]
        if invalid:
            raise HTTPException(status_code=422, detail=f"invalid status: {invalid}")
        q = q.filter(PublicInquiry.status.in_(body.statuses))
        has_filter = True

    def _parse(dt_str: str) -> datetime:
        try:
            d = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
            if d.tzinfo is not None:
                d = d.astimezone(tz=None).replace(tzinfo=None)
            return d
        except ValueError:
            raise HTTPException(status_code=422, detail=f"invalid datetime: {dt_str}")

    if body.created_before:
        q = q.filter(PublicInquiry.created_at < _parse(body.created_before))
        has_filter = True
    if body.created_after:
        q = q.filter(PublicInquiry.created_at >= _parse(body.created_after))
        has_filter = True

    if not has_filter:
        raise HTTPException(status_code=422, detail="at least one filter is required")

    rows = q.all()
    deleted_ids = [r.id for r in rows]
    for r in rows:
        db.delete(r)
    db.commit()

    log_access(
        db, "public_inquiry_bulk_deleted",
        user_id=ctx.user_id,
        resource_type="public_inquiry",
        details={
            "deleted_count": len(deleted_ids),
            "deleted_ids": deleted_ids[:100],  # 巨大リストは切り詰める
            "filter": body.model_dump(exclude_none=True),
        },
        ip_addr=_client_ip(request),
    )
    return {"success": True, "data": {"deleted": len(deleted_ids), "ids": deleted_ids}}


# ─── Content Reports (DMCA / EU Art 14 / 著作権法 30/47-bis) ─────────────────
# 詳細手順: CONTENT_POLICY.md / private_docs/internal/NOTICE_AND_TAKEDOWN_PROCEDURE.md
# Notes:
#   - anonymous 受付可 (匿名性は GDPR Art 21 等の適切な権利行使に必要)
#   - rate limit 適用 (DoS 対策)
#   - statement_text 5000 文字上限 / honeypot あり
#   - admin triage / action は別 endpoint で行う

class ContentReportCreate(BaseModel):
    """違反コンテンツ通報の受付スキーマ。

    妥当な範囲で 17 USC 512(c)(3) / EU 14 / 著作権法 30 系の elements を
    受け取る。匿名通報も処理するため complainant_email は任意。
    """
    model_config = {"extra": "forbid"}

    # 通報対象 (どちらか一方は必須)
    subject_url: Optional[str] = Field(default=None, max_length=500)
    subject_match_id: Optional[int] = Field(default=None, ge=0)
    # 通報者情報 (匿名可、ただし connect-back 連絡には email 推奨)
    complainant_name: Optional[str] = Field(default=None, max_length=255)
    complainant_email: Optional[str] = Field(default=None, max_length=255)
    # 主張内容 (free-text、最低 20 文字、最大 5000)
    statement_text: str = Field(min_length=20, max_length=5000)
    # 法的根拠
    legal_basis: Optional[str] = Field(default=None, max_length=50)
    # honeypot (UI 表示しない隠しフィールド、bot 提出検知)
    website: Optional[str] = Field(default=None, max_length=200)


_VALID_LEGAL_BASIS = {
    "copyright", "data_protection", "defamation", "privacy",
    "image_rights", "trademark", "other",
}


@router.post("/api/public/content_report")
async def submit_content_report(
    body: ContentReportCreate, request: Request, db: Session = Depends(get_db)
):
    """違反コンテンツ通報を受け付ける。

    SLA は CONTENT_POLICY.md Section 7 のとおり:
      - 受領確認: 1 営業日 (本 API のレスポンスで完了)
      - 一次審査: 5 営業日
      - 措置完了: 14 日

    匿名通報も受け付ける (受付確認メール不可)。
    """
    # bot 検知 (honeypot)
    if body.website:
        raise HTTPException(status_code=400, detail="invalid submission")

    # rate limit (contact form 同等)
    _enforce_contact_rate_limit(request)

    # 通報対象 (URL or match_id) のいずれかが必要
    if not body.subject_url and body.subject_match_id is None:
        raise HTTPException(
            status_code=422,
            detail="subject_url または subject_match_id のいずれかが必要です",
        )

    # legal_basis enum
    if body.legal_basis is not None and body.legal_basis not in _VALID_LEGAL_BASIS:
        raise HTTPException(
            status_code=422,
            detail=f"invalid legal_basis: {body.legal_basis!r}",
        )

    # 文字列フィールドの control char / BIDI 拒否 (UI 表示偽装 + null byte 防御)。
    # statement_text は free-text なので改行・タブは許容、それ以外の control / BIDI を reject。
    # 識別子・短いフィールドは改行も含めて全 reject。
    from backend.utils.text_sanitize import reject_ctrl_and_bidi, reject_bidi_only
    reject_ctrl_and_bidi(body.subject_url, "subject_url", max_len=500)
    reject_ctrl_and_bidi(body.complainant_email, "complainant_email", max_len=255)
    reject_ctrl_and_bidi(body.complainant_name, "complainant_name", max_len=255)
    reject_bidi_only(body.statement_text, "statement_text", max_len=5000)

    report = ContentReport(
        subject_url=(body.subject_url or "").strip()[:500] or None,
        subject_match_id=body.subject_match_id,
        complainant_name=(body.complainant_name or "").strip()[:255] or None,
        complainant_email=(body.complainant_email or "").strip()[:255] or None,
        statement_text=body.statement_text.strip(),
        legal_basis=body.legal_basis,
        source_ip=_client_ip(request),
        triage_status="pending",
    )
    db.add(report)
    db.commit()
    db.refresh(report)

    # admin 通知 (audit_log + 受領 ID 返却)
    try:
        from backend.utils.access_log import log_access
        log_access(
            db, "content_report_received",
            resource_type="content_report",
            resource_id=report.id,
            details={
                "legal_basis": body.legal_basis,
                "has_subject_url": bool(body.subject_url),
                "has_subject_match_id": body.subject_match_id is not None,
                "is_anonymous": not body.complainant_email,
            },
            ip_addr=_client_ip(request),
        )
    except Exception:
        pass

    return {
        "success": True,
        "data": {
            "report_id": report.id,
            "received_at": report.received_at.isoformat() if report.received_at else None,
            "ack_message": (
                "通報を受領しました。CONTENT_POLICY.md Section 7 に従い、"
                "5 営業日以内に一次審査、14 日以内に措置を実施します。"
            ),
        },
    }


# ─── Admin: Content Report triage ────────────────────────────────────

class ContentReportTriageBody(BaseModel):
    """admin による triage 状態更新。"""
    model_config = {"extra": "forbid"}

    triage_status: str  # pending | upheld | rejected | awaiting_info | on_hold
    triage_note: Optional[str] = Field(default=None, max_length=5000)
    action_taken: Optional[str] = None
    # no_action | content_removed | access_restricted | account_suspended | pending_legal


_VALID_TRIAGE_STATUS = {
    "pending", "upheld", "rejected", "awaiting_info", "on_hold",
}
_VALID_ACTION = {
    "no_action", "content_removed", "access_restricted",
    "account_suspended", "pending_legal",
}


@router.get("/api/admin/content_reports")
async def list_content_reports(
    request: Request, db: Session = Depends(get_db)
):
    _require_admin(request)
    rows = db.query(ContentReport).order_by(ContentReport.received_at.desc()).all()
    out = []
    for r in rows:
        out.append({
            "id": r.id,
            "received_at": r.received_at.isoformat() if r.received_at else None,
            "subject_url": r.subject_url,
            "subject_match_id": r.subject_match_id,
            "complainant_name": r.complainant_name,
            "complainant_email": r.complainant_email,
            "legal_basis": r.legal_basis,
            "statement_excerpt": (r.statement_text or "")[:500],
            "triage_status": r.triage_status,
            "triaged_at": r.triaged_at.isoformat() if r.triaged_at else None,
            "action_taken": r.action_taken,
            "action_at": r.action_at.isoformat() if r.action_at else None,
            "counter_notice_received_at": (
                r.counter_notice_received_at.isoformat()
                if r.counter_notice_received_at else None
            ),
            "restored_at": r.restored_at.isoformat() if r.restored_at else None,
        })
    return {"success": True, "data": out}


@router.get("/api/admin/content_reports/{report_id}")
async def get_content_report(
    report_id: int, request: Request, db: Session = Depends(get_db)
):
    _require_admin(request)
    r = db.get(ContentReport, report_id)
    if not r:
        raise HTTPException(status_code=404, detail="content_report not found")
    return {
        "success": True,
        "data": {
            "id": r.id,
            "received_at": r.received_at.isoformat() if r.received_at else None,
            "subject_url": r.subject_url,
            "subject_match_id": r.subject_match_id,
            "complainant_name": r.complainant_name,
            "complainant_email": r.complainant_email,
            "legal_basis": r.legal_basis,
            "statement_text": r.statement_text,
            "source_ip": r.source_ip,
            "triage_status": r.triage_status,
            "triaged_at": r.triaged_at.isoformat() if r.triaged_at else None,
            "triaged_by_user_id": r.triaged_by_user_id,
            "triage_note": r.triage_note,
            "action_taken": r.action_taken,
            "action_at": r.action_at.isoformat() if r.action_at else None,
            "counter_notice_received_at": (
                r.counter_notice_received_at.isoformat()
                if r.counter_notice_received_at else None
            ),
            "counter_notice_text": r.counter_notice_text,
            "restored_at": r.restored_at.isoformat() if r.restored_at else None,
        },
    }


@router.patch("/api/admin/content_reports/{report_id}")
async def triage_content_report(
    report_id: int, body: ContentReportTriageBody,
    request: Request, db: Session = Depends(get_db),
):
    _require_admin(request)
    ctx = get_auth(request)
    r = db.get(ContentReport, report_id)
    if not r:
        raise HTTPException(status_code=404, detail="content_report not found")

    if body.triage_status not in _VALID_TRIAGE_STATUS:
        raise HTTPException(
            status_code=422, detail=f"invalid triage_status: {body.triage_status!r}"
        )
    if body.action_taken is not None and body.action_taken not in _VALID_ACTION:
        raise HTTPException(
            status_code=422, detail=f"invalid action_taken: {body.action_taken!r}"
        )

    # triage_note の control char / BIDI 拒否 (admin が後で UI で見るため)
    from backend.utils.text_sanitize import reject_bidi_only
    reject_bidi_only(body.triage_note, "triage_note", max_len=5000)

    now = datetime.utcnow()
    r.triage_status = body.triage_status
    r.triaged_at = now
    r.triaged_by_user_id = ctx.user_id
    if body.triage_note is not None:
        r.triage_note = body.triage_note.strip() or None
    if body.action_taken is not None:
        r.action_taken = body.action_taken
        r.action_at = now
    db.commit()

    try:
        from backend.utils.access_log import log_access
        log_access(
            db, "content_report_triaged",
            user_id=ctx.user_id,
            resource_type="content_report",
            resource_id=r.id,
            details={
                "triage_status": body.triage_status,
                "action_taken": body.action_taken,
            },
        )
    except Exception:
        pass

    return {"success": True, "data": {"id": r.id, "triage_status": r.triage_status}}
