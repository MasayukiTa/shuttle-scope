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
from backend.db.models import PublicInquiry, ContentReport
from backend.routers.status_page import compute_public_status
from backend.utils.auth import get_auth

logger = logging.getLogger(__name__)
router = APIRouter(tags=["public-site"])

PUBLIC_HOSTS = {"shuttle-scope.com", "www.shuttle-scope.com"}
_recent_contact_requests: dict[str, list[datetime]] = {}

# サイトアイコン / OG 画像を backend/public/ から配信（shuttle-scope.com からも Electron SPA からも利用）
_PUBLIC_ASSETS_DIR = Path(__file__).resolve().parent.parent / "public"

# PR1 (2026-05-26): public site の段階的 Jinja2 化用テンプレートディレクトリ。
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


_V7_HOME_HTML = r"""<!DOCTYPE html>
<html lang="ja" data-theme="light">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ShuttleScope — バドミントン試合分析プラットフォーム</title>
<meta name="description" content="ストローク単位の記録から試合構造を統計的に可視化するバドミントン分析ワークベンチ。コーチ・アナリスト・選手それぞれの役割に応じた分析レイヤーを提供します。">
<link rel="canonical" href="https://shuttle-scope.com/">
<link rel="icon" type="image/png" href="/favicon.png">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<meta property="og:type" content="website">
<meta property="og:url" content="https://shuttle-scope.com/">
<meta property="og:title" content="ShuttleScope — バドミントン試合分析プラットフォーム">
<meta property="og:description" content="ストローク単位の記録から試合構造を統計的に可視化するバドミントン分析ワークベンチ。">
<meta property="og:image" content="https://shuttle-scope.com/og-image.png">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="ShuttleScope">
<meta name="twitter:description" content="ストローク単位の記録から試合構造を統計的に可視化するバドミントン分析ワークベンチ。">
<meta name="twitter:image" content="https://shuttle-scope.com/og-image.png">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=MigMix+1P:wght@400;700&family=Barlow+Condensed:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<!-- Material Symbols CDN は廃止: theme トグルはインライン SVG に置換済み (外部依存/プライバシー/未ロード時の生テキスト化を排除) -->
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}

:root,[data-theme="light"]{
  --bg:#f0f3f8;--surface:#ffffff;--surf2:#f7f9fc;--surf3:#eef1f7;
  --hero-bg:#0c1f3f;--hero-bg2:#102646;--hero-t1:#e8f0fb;--hero-t2:#c0d6ee;--hero-bdr:rgba(255,255,255,0.08);
  --navy:#0c2555;--blue:#1059c8;--blue2:#1a6fe0;--blue-lt:#e8f0fd;--blue-md:rgba(16,89,200,0.10);--grn:#007a56;
  --t1:#0b1929;--t2:#445e7a;--t3:#8fa5be;
  --bdr:#dce4ef;--bdr2:#c8d4e6;
  --nav-bg:rgba(255,255,255,0.96);--nav-bdr:#dce4ef;--nav-shadow:0 1px 0 #dce4ef;
  --feat-bg:#ffffff;--feat-hover:#e8f0fd;
  --card-bg:#ffffff;--card-bdr:#dce4ef;
  --data-bg:#ffffff;--fcta-bg:#f0f3f8;
  --footer-bg:#0c2555;--footer-t:#dae8f8;--footer-lt:rgba(255,255,255,0.65);--footer-cp:rgba(255,255,255,0.42);
}

[data-theme="dark"]{
  --bg:#07101d;--surface:#0d1829;--surf2:#111f33;--surf3:#162840;
  --hero-bg:#040d18;--hero-bg2:#07101d;--hero-t1:#daeafb;--hero-t2:#a8c4e0;--hero-bdr:rgba(255,255,255,0.07);
  --navy:#0c2555;--blue:#3380ee;--blue2:#4490ff;--blue-lt:rgba(51,128,238,0.12);--blue-md:rgba(51,128,238,0.12);--grn:#00a874;
  --t1:#d4e4f8;--t2:#6a8daf;--t3:#3d5a76;
  --bdr:rgba(255,255,255,0.07);--bdr2:rgba(255,255,255,0.12);
  --nav-bg:rgba(7,16,29,0.94);--nav-bdr:rgba(255,255,255,0.07);--nav-shadow:none;
  --feat-bg:#0d1829;--feat-hover:#111f33;
  --card-bg:#0d1829;--card-bdr:rgba(255,255,255,0.07);
  --data-bg:#0d1829;--fcta-bg:#07101d;
  --footer-bg:#040c17;--footer-t:#b0c8e4;--footer-lt:rgba(255,255,255,0.55);--footer-cp:rgba(255,255,255,0.36);
}

body,nav,.hero-panel,.feat-card,.uc-card,.sec-data,.sec-fcta{transition:background-color 0.25s ease,border-color 0.25s ease,color 0.2s ease}
html{scroll-behavior:smooth}
body{font-family:'MigMix 1P','Noto Sans JP',sans-serif;background:var(--bg);color:var(--t1);line-height:1.65;overflow-x:hidden;-webkit-font-smoothing:antialiased}
::-webkit-scrollbar{width:6px}::-webkit-scrollbar-track{background:var(--bg)}::-webkit-scrollbar-thumb{background:var(--bdr2);border-radius:3px}

nav{position:fixed;top:0;left:0;right:0;z-index:200;height:58px;display:flex;align-items:center;justify-content:space-between;padding:0 40px;background:var(--nav-bg);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);border-bottom:1px solid var(--nav-bdr);box-shadow:var(--nav-shadow)}
.logo{font-family:'Barlow Condensed',sans-serif;font-size:20px;font-weight:700;letter-spacing:.06em;color:var(--t1);text-decoration:none;display:flex;align-items:center;gap:8px}
.logo-mark{width:26px;height:26px;background:#fff;border-radius:5px;display:flex;align-items:center;justify-content:center;overflow:hidden;transition:background .25s}
.logo-mark img{width:100%;height:100%;object-fit:contain;display:block}
.nav-links{display:flex;align-items:center;gap:28px;list-style:none}
.nav-links a{font-size:13px;color:var(--t2);text-decoration:none;transition:color .15s}
.nav-links a:hover{color:var(--t1)}
.nav-right{display:flex;align-items:center;gap:8px}
.theme-toggle{width:34px;height:34px;border:1px solid var(--bdr2);border-radius:6px;background:transparent;cursor:pointer;display:flex;align-items:center;justify-content:center;font-size:15px;line-height:1;transition:background .15s,border-color .15s;color:var(--t2)}
.theme-toggle svg{width:17px;height:17px;display:block}
/* light テーマ時は月(=dark へ切替), dark テーマ時は太陽(=light へ切替)を表示 */
[data-theme="light"] .theme-toggle .ic-sun{display:none}
[data-theme="dark"] .theme-toggle .ic-moon{display:none}
.theme-toggle:hover{background:var(--blue-lt);border-color:var(--blue)}
.lang-toggle{width:34px;height:34px;border:1px solid var(--bdr2);border-radius:6px;background:transparent;cursor:pointer;display:flex;align-items:center;justify-content:center;font-family:'Barlow Condensed',sans-serif;font-size:12px;font-weight:700;letter-spacing:.06em;color:var(--t2);transition:background .15s,border-color .15s,color .15s}
.lang-toggle:hover{background:var(--blue-lt);border-color:var(--blue);color:var(--blue)}
html[lang=en] .ja{display:none}
html[lang=ja] .en{display:none}
.btn-login{font-family:'MigMix 1P',sans-serif;font-size:12px;font-weight:700;padding:7px 18px;border:1px solid var(--bdr2);border-radius:5px;color:var(--t2);background:transparent;text-decoration:none;transition:all .15s}
.btn-login:hover{color:var(--t1);border-color:var(--blue);background:var(--blue-lt)}
.hamburger{display:none;flex-direction:column;justify-content:center;gap:4px;width:36px;height:36px;cursor:pointer;background:none;border:none;padding:4px}
.hamburger span{display:block;height:1.5px;background:var(--t2);transition:transform .2s,opacity .2s;border-radius:2px}
.hamburger.open span:nth-child(1){transform:translateY(5.5px) rotate(45deg)}
.hamburger.open span:nth-child(2){opacity:0}
.hamburger.open span:nth-child(3){transform:translateY(-5.5px) rotate(-45deg)}
/* mobile-menu は <nav> なので nav{} の backdrop-filter/半透明背景を継承する。
   開いた時に背景が透けて文字が読めない問題を防ぐため、不透明背景を明示し
   継承した backdrop-filter を打ち消す (light/dark それぞれ指定)。 */
.mobile-menu{display:none;position:fixed;top:58px;left:0;right:0;z-index:190;background:#ffffff !important;backdrop-filter:none !important;-webkit-backdrop-filter:none !important;border-bottom:1px solid var(--bdr);flex-direction:column;box-shadow:0 10px 28px rgba(0,0,0,0.22)}
[data-theme="dark"] .mobile-menu{background:#0d1829 !important}
.mobile-menu.open{display:flex}
.mobile-menu a{font-size:14px;color:var(--t1);text-decoration:none;padding:14px 24px;border-bottom:1px solid var(--bdr);transition:color .15s,background .15s}
.mobile-menu a:hover{color:var(--t1);background:var(--blue-lt)}

.hero{position:relative;background:var(--hero-bg);padding:60px 40px 80px;overflow:hidden}
.hero::before{content:'';position:absolute;top:-100px;right:-100px;width:560px;height:560px;background:radial-gradient(circle,rgba(26,111,224,0.16) 0%,transparent 65%);pointer-events:none;z-index:0}
.hero::after{content:'';position:absolute;inset:0;background-image:linear-gradient(rgba(255,255,255,0.022) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,0.022) 1px,transparent 1px);background-size:52px 52px;pointer-events:none;z-index:0}
.hero-inner{position:relative;z-index:1;max-width:1160px;margin:0 auto;display:grid;grid-template-columns:1fr 400px;gap:64px;align-items:center}
@keyframes blink{0%,100%{opacity:1}50%{opacity:0.25}}
h1.hero-h1{font-family:'MigMix 1P',sans-serif;font-size:clamp(28px,3.6vw,48px);font-weight:700;line-height:1.2;color:var(--hero-t1);margin-bottom:12px;letter-spacing:.01em}
.hero-tagline{font-family:'Barlow Condensed',sans-serif;font-size:clamp(20px,2.4vw,30px);font-weight:600;color:#6fb0ff;letter-spacing:.04em;margin-bottom:20px}
.hero-sub{font-size:14px;color:var(--hero-t2);line-height:1.9;max-width:480px;margin-bottom:28px}
.hero-tags{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:36px}
.htag{font-family:'MigMix 1P',sans-serif;font-size:11px;color:rgba(220,235,255,0.92);border:1px solid rgba(255,255,255,0.18);background:rgba(255,255,255,0.07);padding:4px 10px;border-radius:3px;letter-spacing:.02em}
.hero-actions{display:flex;align-items:center;gap:14px;flex-wrap:wrap}
.btn-cta{display:inline-flex;align-items:center;gap:10px;font-family:'MigMix 1P',sans-serif;font-size:15px;font-weight:700;padding:14px 32px;background:var(--blue2);color:#fff;border:none;border-radius:6px;text-decoration:none;cursor:pointer;letter-spacing:.03em;transition:background .15s,transform .15s,box-shadow .2s;box-shadow:0 2px 14px rgba(26,111,224,0.35)}
.btn-cta:hover{background:#1a78f5;transform:translateY(-1px);box-shadow:0 4px 22px rgba(26,111,224,0.45)}
.btn-cta:active{transform:translateY(0);box-shadow:none}
.cta-arrow{width:20px;height:20px;border-radius:50%;border:1.5px solid rgba(255,255,255,0.5);display:flex;align-items:center;justify-content:center;font-size:12px;transition:transform .15s}
.btn-cta:hover .cta-arrow{transform:translateX(3px)}
.btn-ghost{font-size:13px;color:var(--hero-t2);text-decoration:none;padding:6px 2px;border-bottom:1px solid rgba(138,170,207,0.3);transition:color .15s,border-color .15s}
.btn-ghost:hover{color:var(--hero-t1);border-color:var(--hero-t2)}

.hero-panel{background:var(--surface);border-radius:12px;overflow:hidden;box-shadow:0 8px 32px rgba(0,0,0,0.30),0 2px 8px rgba(0,0,0,0.16)}
.panel-titlebar{display:flex;align-items:center;gap:6px;padding:9px 14px;background:var(--surf2);border-bottom:1px solid var(--bdr)}
.pdot{width:8px;height:8px;border-radius:50%}
.panel-title-text{margin-left:6px;font-family:'Barlow Condensed',sans-serif;font-size:10px;font-weight:600;color:var(--t3);letter-spacing:.09em;text-transform:uppercase}
.panel-body{padding:14px 16px 16px}
.p-match-label{font-family:'Barlow Condensed',sans-serif;font-size:10px;font-weight:600;letter-spacing:.10em;color:var(--t3);text-transform:uppercase;margin-bottom:10px}
.p-score-row{display:flex;align-items:center;margin-bottom:14px}
.p-team{flex:1}.p-team-name{font-size:11px;color:var(--t2);margin-bottom:3px}
.p-team-score{font-family:'Barlow Condensed',sans-serif;font-size:38px;font-weight:800;color:var(--t1);line-height:1}
.p-team-score.win{color:var(--blue)}
.p-vs{font-family:'Barlow Condensed',sans-serif;font-size:14px;color:var(--t3);padding:0 10px}
.p-divider{height:1px;background:var(--bdr);margin:0 0 12px}
.p-kpi-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-bottom:14px}
.p-kpi{background:var(--surf2);border:1px solid var(--bdr);border-radius:6px;padding:9px 6px;text-align:center}
.p-kpi-val{font-family:'Barlow Condensed',sans-serif;font-size:18px;font-weight:700;color:var(--t1);line-height:1;margin-bottom:3px}
.p-kpi-lbl{font-size:9px;color:var(--t3);letter-spacing:.06em;font-family:'Barlow Condensed',sans-serif}
.p-chart-head{font-family:'Barlow Condensed',sans-serif;font-size:10px;font-weight:600;letter-spacing:.09em;color:var(--t3);text-transform:uppercase;margin-bottom:8px}
.bar-row{display:flex;align-items:center;gap:8px;margin-bottom:5px}
.bar-name{font-size:10px;color:var(--t2);min-width:64px}
.bar-track{flex:1;height:5px;background:var(--surf3);border-radius:3px;overflow:hidden}
.bar-fill{height:100%;border-radius:3px;background:var(--blue);transition:background .25s}
.bar-fill.lo{background:var(--bdr2)}
.bar-pct{font-family:'Barlow Condensed',sans-serif;font-size:10px;color:var(--t2);min-width:28px;text-align:right}
.panel-foot{padding:9px 14px;border-top:1px solid var(--bdr);display:flex;align-items:center;justify-content:space-between;background:var(--surf2)}
.panel-foot-txt{font-family:'Barlow Condensed',sans-serif;font-size:10px;color:var(--t3);letter-spacing:.05em}
.panel-live{display:flex;align-items:center;gap:5px;font-family:'Barlow Condensed',sans-serif;font-size:10px;color:var(--grn);font-weight:600}
.panel-live::before{content:'';width:6px;height:6px;border-radius:50%;background:var(--grn);animation:blink 1.8s ease infinite}

.sec{padding:80px 40px}.sec-wrap{max-width:1160px;margin:0 auto}
.sec-kicker{display:inline-flex;align-items:center;gap:8px;font-family:'Barlow Condensed',sans-serif;font-size:10px;font-weight:600;letter-spacing:.16em;text-transform:uppercase;color:var(--blue);margin-bottom:10px}
.sec-kicker::before{content:'';width:18px;height:2px;background:var(--blue)}
.sec-h2{font-family:'MigMix 1P',sans-serif;font-size:clamp(24px,2.8vw,34px);font-weight:700;color:var(--t1);line-height:1.3;margin-bottom:10px}
.sec-sub{font-size:14px;color:var(--t2);line-height:1.85;max-width:520px;margin-bottom:48px}

.sec-features{background:var(--feat-bg);border-top:1px solid var(--bdr);border-bottom:1px solid var(--bdr)}
.feat-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;background:var(--bdr);border:1px solid var(--bdr);border-radius:12px;overflow:hidden}
.feat-card{background:var(--feat-bg);padding:28px 24px 24px;position:relative;overflow:hidden;transition:background .15s}
.feat-card:hover{background:var(--feat-hover)}
.feat-card::after{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:var(--blue);transform:scaleX(0);transform-origin:left;transition:transform .25s ease}
.feat-card:hover::after{transform:scaleX(1)}
.feat-no{font-family:'Barlow Condensed',sans-serif;font-size:10px;font-weight:600;letter-spacing:.12em;color:var(--blue);background:var(--blue-md);border-radius:3px;padding:2px 8px;display:inline-block;margin-bottom:14px}
.feat-icon{width:38px;height:38px;border-radius:8px;background:var(--blue-md);border:1px solid rgba(16,89,200,0.15);display:flex;align-items:center;justify-content:center;margin-bottom:14px}
.feat-icon svg{width:17px;height:17px}
.feat-h{font-family:'MigMix 1P',sans-serif;font-size:15px;font-weight:700;color:var(--t1);margin-bottom:8px}
.feat-p{font-size:13px;color:var(--t2);line-height:1.8}

.sec-uc{background:var(--bg)}
.uc-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:12px}
.uc-card{background:var(--card-bg);border:1px solid var(--card-bdr);border-radius:12px;padding:24px;display:flex;gap:18px;transition:border-color .15s,box-shadow .15s}
.uc-card:hover{border-color:var(--blue2);box-shadow:0 2px 12px rgba(16,89,200,0.10)}
.uc-badge{font-family:'Barlow Condensed',sans-serif;font-size:10px;font-weight:700;letter-spacing:.10em;color:var(--blue);background:var(--blue-md);border-radius:3px;padding:3px 8px;white-space:nowrap;height:fit-content;margin-top:2px}
.uc-h{font-family:'MigMix 1P',sans-serif;font-size:14px;font-weight:700;color:var(--t1);margin-bottom:6px}
.uc-p{font-size:12px;color:var(--t2);line-height:1.8}

.sec-data{background:var(--data-bg);border-top:1px solid var(--bdr);border-bottom:1px solid var(--bdr);padding:56px 40px}
.data-body{font-size:13px;color:var(--t2);line-height:1.85;max-width:640px}
.data-body a{color:var(--blue);text-decoration:none}
.data-body a:hover{text-decoration:underline}

.sec-fcta{background:var(--fcta-bg);padding:88px 40px;text-align:center;border-top:1px solid var(--bdr)}
.fcta-h{font-family:'MigMix 1P',sans-serif;font-size:clamp(26px,3vw,38px);font-weight:700;color:var(--t1);margin-bottom:12px}
.fcta-sub{font-size:14px;color:var(--t2);margin-bottom:32px}

footer{background:var(--footer-bg);padding:24px 40px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;transition:background .25s}
.footer-logo{font-family:'Barlow Condensed',sans-serif;font-size:17px;font-weight:700;letter-spacing:.05em;color:var(--footer-t);text-decoration:none;display:flex;align-items:center;gap:8px}
.footer-logo .logo-mark{background:rgba(255,255,255,0.12);font-size:12px}
.footer-links{display:flex;gap:20px;list-style:none}
.footer-links a{font-size:11px;color:var(--footer-lt);text-decoration:none}
.footer-links a:hover{color:var(--footer-t)}
.footer-copy{font-size:11px;color:var(--footer-cp)}

.reveal{opacity:0;transform:translateY(14px);transition:opacity .5s ease,transform .5s ease}
.reveal.vis{opacity:1;transform:translateY(0)}
.d1{transition-delay:.06s}.d2{transition-delay:.12s}.d3{transition-delay:.18s}
.fa{animation:fu .55s ease both}.fb{animation:fu .55s .08s ease both}.fc{animation:fu .55s .16s ease both}
.fd{animation:fu .55s .24s ease both}.fe{animation:fu .55s .32s ease both}
@keyframes fu{from{opacity:0;transform:translateY(16px)}to{opacity:1;transform:translateY(0)}}

.mob-bar{display:none}

.beta-banner{background:linear-gradient(135deg,#0a4d8c 0%,#0c6e6e 100%);padding:14px 40px;margin-top:58px}
.beta-banner-inner{max-width:1160px;margin:0 auto;display:flex;align-items:center;justify-content:center;gap:14px;flex-wrap:wrap;text-align:center}
.beta-badge{font-family:'Barlow Condensed',sans-serif;font-size:11px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:rgba(255,255,255,0.92);background:rgba(255,255,255,0.14);border:1px solid rgba(255,255,255,0.24);border-radius:4px;padding:3px 10px;white-space:nowrap;flex-shrink:0}
.beta-text{font-size:13px;color:rgba(255,255,255,0.86);line-height:1.7;margin:0}
.beta-text strong{color:#ffffff;font-weight:700}
.beta-text a{color:#a8d8f8;text-decoration:none;border-bottom:1px solid rgba(168,216,248,0.38);transition:color .15s,border-color .15s}
.beta-text a:hover{color:#fff;border-bottom-color:rgba(255,255,255,0.55)}

@media(max-width:767px){
  .beta-banner{padding:12px 16px}.beta-text{font-size:12px}
  nav{padding:0 16px}.nav-links{display:none}.btn-login{display:none}.hamburger{display:flex}
  .hero{padding:40px 20px 96px}.hero-inner{grid-template-columns:1fr;gap:0}.hero-panel{display:none}
  h1.hero-h1{font-size:clamp(26px,7.5vw,36px)}.hero-tagline{font-size:clamp(16px,5vw,22px)}
  .hero-sub{font-size:13px;margin-bottom:20px}.hero-actions{flex-direction:column;align-items:stretch}
  .hero-tags{margin-bottom:28px;gap:6px}.htag{font-size:10px;padding:3px 8px}
  .btn-cta{width:100%;justify-content:center;font-size:15px;padding:15px}.btn-ghost{display:none}
  .sec{padding:52px 20px}.sec-sub{margin-bottom:28px}.feat-grid{grid-template-columns:1fr}
  .uc-grid{grid-template-columns:1fr}.uc-card{padding:18px 16px;gap:12px}
  .sec-data{padding:44px 20px}.sec-fcta{padding:56px 20px 100px}
  footer{padding:20px 16px;flex-direction:column;padding-bottom:84px}
  .mob-bar{display:flex;position:fixed;bottom:0;left:0;right:0;z-index:300;padding:10px 14px;background:rgba(255,255,255,0.97);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);border-top:1px solid var(--bdr);box-shadow:0 -2px 12px rgba(0,0,0,0.08);gap:10px;align-items:center;transition:background .25s}
  [data-theme="dark"] .mob-bar{background:rgba(7,16,29,0.97);box-shadow:0 -2px 12px rgba(0,0,0,0.32)}
  .mob-bar .btn-cta{flex:1;justify-content:center;font-size:15px;padding:13px}
  .mob-bar-login{font-family:'MigMix 1P',sans-serif;font-size:12px;font-weight:700;padding:12px 16px;border:1px solid var(--bdr2);border-radius:6px;color:var(--t2);background:var(--surface);text-decoration:none;white-space:nowrap;transition:all .15s}
  .mob-bar-login:hover{color:var(--t1);border-color:var(--blue)}
}
@media(min-width:768px) and (max-width:1023px){
  nav{padding:0 28px}.nav-links{gap:18px}.nav-links li:nth-child(3){display:none}
  .hero{padding:44px 28px 64px}.hero-inner{grid-template-columns:1fr 300px;gap:36px}
  h1.hero-h1{font-size:clamp(26px,4vw,38px)}.sec{padding:64px 28px}
  .sec-data{padding:48px 28px}.sec-fcta{padding:64px 28px}footer{padding:22px 28px}
}
@media(min-width:1024px){
  .hamburger{display:none}.mob-bar{display:none}.mobile-menu{display:none!important}
}
</style>
</head>
<body>

<nav>
  <a class="logo" href="/"><div class="logo-mark"><img src="/favicon.png" alt=""></div>ShuttleScope</a>
  <ul class="nav-links">
    <li><a href="#features"><span class="ja">機能</span><span class="en">Features</span></a></li>
    <li><a href="#usecases"><span class="ja">利用シーン</span><span class="en">Use Cases</span></a></li>
    <li><a href="/privacy"><span class="ja">プライバシーポリシー</span><span class="en">Privacy Policy</span></a></li>
    <li><a href="/contact"><span class="ja">お問い合わせ</span><span class="en">Contact</span></a></li>
    <li><a href="/status"><span class="ja">稼働状況</span><span class="en">Status</span></a></li>
  </ul>
  <div class="nav-right">
    <button class="theme-toggle" id="theme-btn" title="テーマ切り替え" aria-label="テーマ切り替え"><svg class="ic-moon" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 3a9 9 0 1 0 9 9c0-.46-.04-.92-.11-1.36a5.39 5.39 0 0 1-7.53-7.53A9.05 9.05 0 0 0 12 3z"/></svg><svg class="ic-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg></button>
    <button class="lang-toggle" id="lang-btn">EN</button>
    <a href="https://app.shuttle-scope.com/login" class="btn-login"><span class="ja">ログイン</span><span class="en">Login</span></a>
    <button class="hamburger" id="ham" aria-label="メニュー"><span></span><span></span><span></span></button>
  </div>
</nav>

<nav class="mobile-menu" id="mmenu">
  <a href="#features"><span class="ja">機能</span><span class="en">Features</span></a>
  <a href="#usecases"><span class="ja">利用シーン</span><span class="en">Use Cases</span></a>
  <a href="/privacy"><span class="ja">プライバシーポリシー</span><span class="en">Privacy Policy</span></a>
  <a href="/contact"><span class="ja">お問い合わせ</span><span class="en">Contact</span></a>
  <a href="/status"><span class="ja">稼働状況</span><span class="en">Status</span></a>
  <a href="https://app.shuttle-scope.com/#/register"><span class="ja">新規登録</span><span class="en">Register</span></a>
  <a href="https://app.shuttle-scope.com/login" style="color:var(--blue);font-weight:700"><span class="ja">ログイン →</span><span class="en">Login →</span></a>
</nav>

<div class="beta-banner">
  <div class="beta-banner-inner">
    <span class="beta-badge"><span class="ja">β 版</span><span class="en">BETA</span></span>
    <p class="beta-text">
      <span class="ja">ShuttleScope は <strong>2026年中、無償</strong>にてご利用いただけます。現在、β版にご協力いただける方を募集しております。ご賛同いただける方は、<a href="/contact">お問い合わせフォーム</a>よりご連絡ください。</span>
      <span class="en">ShuttleScope is available <strong>free of charge throughout 2026</strong>. We are currently seeking participants for our beta programme. If you are interested in joining, please reach out via the <a href="/en/contact">contact form</a>.</span>
    </p>
  </div>
</div>

<section class="hero">
  <div class="hero-inner">
    <div>
      <h1 class="hero-h1 fa"><span class="ja">試合をデータで説明する</span><span class="en">Explain the Match with Data</span></h1>
      <p class="hero-tagline fb"><span class="ja">直感に統計的な根拠を</span><span class="en">Back Your Instincts with Statistics</span></p>
      <p class="hero-sub fc"><span class="ja">ストローク単位の記録から試合構造を統計的に可視化するバドミントン分析ワークベンチです。コーチ・アナリスト・選手それぞれの役割に応じた分析レイヤーを提供します。</span><span class="en">ShuttleScope is a sports data analysis platform for badminton match analysis. It provides statistical visualization and performance analysis tools for coaches, analysts, and players.</span></p>
      <div class="hero-tags fd">
        <span class="htag"><span class="ja">ストローク分析</span><span class="en">Stroke Analysis</span></span>
        <span class="htag"><span class="ja">統計モデル</span><span class="en">Statistical Model</span></span>
        <span class="htag"><span class="ja">戦術可視化</span><span class="en">Tactical Viz</span></span>
        <span class="htag"><span class="ja">コンディション追跡</span><span class="en">Condition Tracking</span></span>
      </div>
      <div class="hero-actions fd">
        <a href="https://app.shuttle-scope.com/login" class="btn-cta"><span class="ja">アプリに進む</span><span class="en">Open App</span> <span class="cta-arrow">›</span></a>
        <a href="/contact" class="btn-ghost"><span class="ja">お問い合わせ</span><span class="en">Contact</span></a>
      </div>
    </div>
    <div class="hero-panel fd">
      <div class="panel-titlebar">
        <div class="pdot" style="background:#f87171"></div>
        <div class="pdot" style="background:#fbbf24"></div>
        <div class="pdot" style="background:#34d399"></div>
        <span class="panel-title-text">Match Review — 2026.04.19</span>
      </div>
      <div class="panel-body">
        <div class="p-match-label">第13節 第2試合 — WD</div>
        <div class="p-score-row">
          <div class="p-team"><div class="p-team-name">自チーム</div><div class="p-team-score win">2</div></div>
          <div class="p-vs">–</div>
          <div class="p-team" style="text-align:right"><div class="p-team-name">相手チーム</div><div class="p-team-score">1</div></div>
        </div>
        <div class="p-divider"></div>
        <div class="p-kpi-grid">
          <div class="p-kpi"><div class="p-kpi-val">74%</div><div class="p-kpi-lbl">1ST SRV</div></div>
          <div class="p-kpi"><div class="p-kpi-val">38</div><div class="p-kpi-lbl">RALLIES</div></div>
          <div class="p-kpi"><div class="p-kpi-val" style="color:var(--grn)">+7</div><div class="p-kpi-lbl">PTS DIFF</div></div>
        </div>
        <div class="p-chart-head">Rally length distribution</div>
        <div class="bar-row"><div class="bar-name">1–3 shots</div><div class="bar-track"><div class="bar-fill" style="width:72%"></div></div><div class="bar-pct">72%</div></div>
        <div class="bar-row"><div class="bar-name">4–8 shots</div><div class="bar-track"><div class="bar-fill" style="width:20%"></div></div><div class="bar-pct">20%</div></div>
        <div class="bar-row"><div class="bar-name">9+ shots</div><div class="bar-track"><div class="bar-fill lo" style="width:8%"></div></div><div class="bar-pct" style="color:var(--t3)">8%</div></div>
      </div>
      <div class="panel-foot">
        <span class="panel-foot-txt">ShuttleScope / Analyst</span>
        <span class="panel-live">LIVE SYNC</span>
      </div>
    </div>
  </div>
</section>

<section class="sec sec-features" id="features">
  <div class="sec-wrap">
    <div class="reveal">
      <div class="sec-kicker">Core Features</div>
      <h2 class="sec-h2"><span class="ja">分析を支える3つの機能</span><span class="en">Three Core Features</span></h2>
      <p class="sec-sub"><span class="ja">アノテーション・統計解析・役割別アクセスが一体になった設計です。</span><span class="en">Annotation, statistical analysis, and role-based access — unified in one platform.</span></p>
    </div>
    <div class="feat-grid">
      <div class="feat-card reveal d1">
        <div class="feat-no">01 / ANNOTATION</div>
        <div class="feat-icon"><svg viewBox="0 0 17 17" fill="none" stroke="var(--blue)" stroke-width="1.6"><polygon points="3,2.5 13.5,8.5 3,14.5"/></svg></div>
        <div class="feat-h"><span class="ja">ストローク単位のアノテーション</span><span class="en">Stroke-level Annotation</span></div>
        <p class="feat-p"><span class="ja">ラリーをストローク単位で記録します。配球位置・球種・着地点を逐次入力することで、統計モデルの精度が上がります。</span><span class="en">Record each rally stroke by stroke. Logging shot position, type, and landing zone improves the accuracy of statistical models.</span></p>
      </div>
      <div class="feat-card reveal d2">
        <div class="feat-no">02 / ANALYSIS</div>
        <div class="feat-icon"><svg viewBox="0 0 17 17" fill="none" stroke="var(--blue)" stroke-width="1.6"><circle cx="8.5" cy="5.5" r="2.5"/><path d="M3 14.5c0-3.1 2.4-5.5 5.5-5.5s5.5 2.4 5.5 5.5"/></svg></div>
        <div class="feat-h"><span class="ja">統計モデルによる試合解析</span><span class="en">Statistical Match Analysis</span></div>
        <p class="feat-p"><span class="ja">Markov モデル・EPV・コートヒートマップ・疲労指標により試合構造を多角的に可視化します。記録が増えるほど分析の解像度が上がります。</span><span class="en">Markov models, EPV, court heatmaps, and fatigue indicators visualize match structure from multiple angles. Resolution improves as more data is recorded.</span></p>
      </div>
      <div class="feat-card reveal d3">
        <div class="feat-no">03 / ROLES</div>
        <div class="feat-icon"><svg viewBox="0 0 17 17" fill="none" stroke="var(--blue)" stroke-width="1.6"><circle cx="3" cy="8.5" r="1.8"/><circle cx="14" cy="4" r="1.8"/><circle cx="14" cy="13" r="1.8"/><line x1="4.7" y1="7.6" x2="12.3" y2="4.9"/><line x1="4.7" y1="9.4" x2="12.3" y2="12.1"/></svg></div>
        <div class="feat-h"><span class="ja">役割に応じた分析レイヤー</span><span class="en">Role-based Analysis Layers</span></div>
        <p class="feat-p"><span class="ja">コーチ・アナリスト・選手で参照できる情報の粒度が異なります。それぞれの判断に必要なデータを、適切な形で届けます。</span><span class="en">Coaches, analysts, and players each see a different level of detail. The right data is delivered to the right person in the right form.</span></p>
      </div>
    </div>
  </div>
</section>

<section class="sec sec-uc" id="usecases">
  <div class="sec-wrap">
    <div class="reveal">
      <div class="sec-kicker">Analysis Capabilities</div>
      <h2 class="sec-h2"><span class="ja">試合から読み取れること</span><span class="en">What the Match Data Reveals</span></h2>
      <p class="sec-sub"><span class="ja">ストロークを記録するたびに統計モデルが更新され、試合の構造が可視化されます。</span><span class="en">Every stroke recorded updates the statistical model and makes match structure more visible.</span></p>
    </div>
    <div class="uc-grid">
      <div class="uc-card reveal d1"><div class="uc-badge">01</div><div><div class="uc-h"><span class="ja">ラリー構造の分析</span><span class="en">Rally Structure Analysis</span></div><p class="uc-p"><span class="ja">どのパターンで得点・失点しているかをラリー単位で可視化します。コートヒートマップと配球傾向から試合の構造が見えます。</span><span class="en">Visualize scoring and losing patterns at the rally level. Court heatmaps and shot tendency data reveal match structure.</span></p></div></div>
      <div class="uc-card reveal d2"><div class="uc-badge">02</div><div><div class="uc-h"><span class="ja">得点期待値の算出</span><span class="en">Expected Score Calculation</span></div><p class="uc-p"><span class="ja">Markov モデルと EPV により各局面の優位性を数値化します。「なんとなく苦しかった」を統計的な根拠に変えます。</span><span class="en">Markov models and EPV quantify the advantage at each stage. Turn "it felt tough" into statistical evidence.</span></p></div></div>
      <div class="uc-card reveal d1"><div class="uc-badge">03</div><div><div class="uc-h"><span class="ja">戦術傾向の可視化</span><span class="en">Tactical Pattern Visualization</span></div><p class="uc-p"><span class="ja">配球パターン・反実仮想分析・セット間比較により、勝敗に影響した戦術要因を特定します。</span><span class="en">Identify tactical factors that influenced the outcome through shot patterns, counterfactual analysis, and set comparisons.</span></p></div></div>
      <div class="uc-card reveal d2"><div class="uc-badge">04</div><div><div class="uc-h"><span class="ja">コンディションとの相関</span><span class="en">Correlation with Physical Condition</span></div><p class="uc-p"><span class="ja">体調指標とパフォーマンスデータを重ねて分析します。疲労が試合展開に与える影響をシーズン単位で追跡できます。</span><span class="en">Overlay condition indicators with performance data. Track the impact of fatigue on match flow across an entire season.</span></p></div></div>
    </div>
  </div>
</section>

<section class="sec-data">
  <div class="sec-wrap reveal">
    <div class="sec-kicker">Data Policy</div>
    <p class="data-body"><span class="ja">ShuttleScope では利用目的に応じて試合映像・レビュー情報・選手に関する入力情報を扱う場合があります。具体的な取扱方針は <a href="/privacy">プライバシーポリシー</a> を、利用条件は <a href="/terms">利用規約</a> をご確認ください。</span><span class="en">ShuttleScope may handle match footage, review information, and player input data depending on the purpose of use. See our <a href="/privacy">Privacy Policy</a> and <a href="/terms">Terms of Use</a> for details.</span></p>
  </div>
</section>

<section class="sec-fcta reveal">
  <div class="sec-kicker" style="justify-content:center">Get Started</div>
  <h2 class="fcta-h"><span class="ja">記録が増えるほど見えてくるものがある</span><span class="en">The More You Record, the More You See</span></h2>
  <p class="fcta-sub"><span class="ja">アカウントをお持ちの方はそのままログインできます。</span><span class="en">Existing accounts can log in directly.</span></p>
  <a href="https://app.shuttle-scope.com/login" class="btn-cta" style="font-size:16px;padding:16px 40px"><span class="ja">アプリを開く</span><span class="en">Open App</span> <span class="cta-arrow">›</span></a>
</section>

<footer>
  <a class="footer-logo" href="/"><div class="logo-mark"><img src="/favicon.png" alt=""></div>ShuttleScope</a>
  <ul class="footer-links">
    <li><a href="/terms"><span class="ja">利用規約</span><span class="en">Terms</span></a></li>
    <li><a href="/privacy"><span class="ja">プライバシーポリシー</span><span class="en">Privacy Policy</span></a></li>
    <li><a href="/contact"><span class="ja">お問い合わせ</span><span class="en">Contact</span></a></li>
    <li><a href="/status"><span class="ja">稼働状況</span><span class="en">Status</span></a></li>
    <li><a href="https://app.shuttle-scope.com/#/register"><span class="ja">新規登録</span><span class="en">Register</span></a></li>
  </ul>
  <span class="footer-copy">© 2026 ShuttleScope</span>
</footer>

<div class="mob-bar">
  <a href="https://app.shuttle-scope.com/login" class="btn-cta"><span class="ja">アプリに進む</span><span class="en">Open App</span> <span class="cta-arrow">›</span></a>
  <a href="/contact" class="mob-bar-login"><span class="ja">お問い合わせ</span><span class="en">Contact</span></a>
</div>

<script>
const html=document.documentElement;
// theme
const tbtn=document.getElementById('theme-btn');
// アイコン表示は data-theme に応じた CSS (.ic-sun/.ic-moon) が制御するため JS は data-theme の切替のみ。
const savedTheme=localStorage.getItem('ss-theme');
if(savedTheme){html.dataset.theme=savedTheme}
tbtn.addEventListener('click',()=>{
  const next=html.dataset.theme==='dark'?'light':'dark';
  html.dataset.theme=next;
  localStorage.setItem('ss-theme',next);
});
// lang — URL-based: /en = English, / = Japanese
const lbtn=document.getElementById('lang-btn');
let lang=location.pathname.startsWith('/en')?'en':'ja';
html.lang=lang;lbtn.textContent=lang==='ja'?'EN':'JA';
lbtn.addEventListener('click',()=>{location.href=lang==='ja'?'/en':'/'});
// Fix footer/nav links to language-appropriate equivalents
if(lang==='en'){
  document.querySelectorAll('a[href="/terms"]').forEach(a=>a.setAttribute('href','/en/terms'));
  document.querySelectorAll('a[href="/privacy"]').forEach(a=>a.setAttribute('href','/en/privacy'));
  document.querySelectorAll('a[href="/contact"]').forEach(a=>a.setAttribute('href','/en/contact'));
  document.querySelectorAll('a[href="/status"]').forEach(a=>a.setAttribute('href','/en/status'));
  // ブランド/ロゴ link を EN home (/en) に書き換える。
  // (デフォルトは / = JA home なので、EN モードのまま戻ると JA 側に飛んでしまう)
  document.querySelectorAll('a.logo, a.footer-logo, a.brand').forEach(a=>{
    if(a.getAttribute('href')==='/') a.setAttribute('href','/en');
  });
  // SPA への遷移 link に ?lang=en を付けて、起動時の言語選択
  // (i18n.detectInitialLang) で英語が選ばれるようにする。
  // - https://app.shuttle-scope.com/#/register  ← hash 形式: そのまま lang 付与
  // - https://app.shuttle-scope.com/login       ← path 形式: hash に変換 + lang 付与
  //   (backend の spa_catch_all は /login を /#/login に redirect するが、その際
  //    ?lang=en は脱落するので、最初から hash 形式に書き換えておく)
  document.querySelectorAll('a[href^="https://app.shuttle-scope.com/"]').forEach(a=>{
    const u=new URL(a.href);
    if(u.pathname && u.pathname!=='/'){u.hash='#'+u.pathname;u.pathname='/';}
    if(!u.searchParams.get('lang')){u.searchParams.set('lang','en');}
    a.setAttribute('href',u.toString());
  });
}
// hamburger
const ham=document.getElementById('ham'),mm=document.getElementById('mmenu');
ham.addEventListener('click',()=>{ham.classList.toggle('open');mm.classList.toggle('open')});
mm.querySelectorAll('a').forEach(a=>a.addEventListener('click',()=>{ham.classList.remove('open');mm.classList.remove('open')}));
// scroll reveal
const obs=new IntersectionObserver(e=>{
  e.forEach(x=>{if(x.isIntersecting){x.target.classList.add('vis');obs.unobserve(x.target)}});
},{threshold:0.1});
document.querySelectorAll('.reveal').forEach(el=>obs.observe(el));
</script>
</body>
</html>"""


def _inject_status_banner(home_html: str) -> str:
    """トップページ (_V7_HOME_HTML) の beta-banner 直後 (hero の直前) に
    公開ステータスバナー partial を注入する。partial は base.html.j2 と共有の単一ソース。
    バナー描画失敗時はトップページが 500 にならないよう、無注入で返す (fail-open)。"""
    try:
        banner = _jinja_env.get_template("public/_status_banner.html.j2").render()
    except Exception as exc:  # noqa: BLE001
        logger.warning("status banner render failed: %s", exc)
        return home_html
    return home_html.replace('<section class="hero">', banner + '\n<section class="hero">', 1)


def render_public_home(request: Request) -> HTMLResponse:
    return HTMLResponse(_inject_status_banner(_V7_HOME_HTML))


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
    return HTMLResponse(_rewrite_preview_links(_V7_HOME_HTML))


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
    return HTMLResponse(_rewrite_preview_links_en(_V7_HOME_HTML))


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
