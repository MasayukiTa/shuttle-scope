"""Public website pages and inquiry endpoints for shuttle-scope.com."""

from __future__ import annotations

import html
import json
import logging
import re
import urllib.request
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.config import settings
from backend.db.database import get_db
from backend.db.models import PublicInquiry
from backend.utils.auth import get_auth

logger = logging.getLogger(__name__)
router = APIRouter(tags=["public-site"])

PUBLIC_HOSTS = {"shuttle-scope.com", "www.shuttle-scope.com"}
_recent_contact_requests: dict[str, list[datetime]] = {}


class PublicInquiryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    organization: Optional[str] = Field(default=None, max_length=160)
    role: Optional[str] = Field(default=None, max_length=80)
    contact_reference: Optional[str] = Field(default=None, max_length=200)
    message: str = Field(min_length=10, max_length=4000)
    website: Optional[str] = Field(default=None, max_length=100)


class PublicInquiryUpdate(BaseModel):
    status: str = Field(pattern="^(new|reviewed|resolved)$")
    admin_note: Optional[str] = Field(default=None, max_length=4000)


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


def _base_layout_str(title: str, body: str, *, canonical_path: str = "/", noindex: bool = False) -> str:
    """HTML 文字列を返す。HTMLResponse へのラップは呼び出し元で行う。"""
    robots = '<meta name="robots" content="noindex,nofollow">' if noindex else ""
    canonical = f"https://shuttle-scope.com{canonical_path}"
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <meta name="description" content="ShuttleScope is a badminton analysis and review platform for structured match, player, and coaching workflows.">
  <link rel="canonical" href="{canonical}">
  {robots}
  <style>
    :root {{
      --bg: #f5f8fc;
      --panel: rgba(255,255,255,.88);
      --text: #11314d;
      --muted: #4f6478;
      --line: #d5e3f2;
      --brand: #0f5ea8;
      --brand-soft: #dcecff;
      --accent: #0d7b83;
      --danger: #b33f3f;
      --shadow: 0 20px 60px rgba(18, 54, 90, 0.10);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--text);
      font-family: "Segoe UI", "Hiragino Sans", "Yu Gothic UI", sans-serif;
      background:
        radial-gradient(circle at top right, rgba(13,123,131,.16), transparent 26%),
        radial-gradient(circle at top left, rgba(15,94,168,.16), transparent 24%),
        linear-gradient(180deg, #f9fbfe 0%, var(--bg) 100%);
    }}
    a {{ color: var(--brand); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .shell {{ max-width: 1120px; margin: 0 auto; padding: 24px; }}
    .topbar {{
      display: flex; align-items: center; justify-content: space-between; gap: 16px;
      margin-bottom: 28px;
    }}
    .brand {{
      font-size: 1.2rem; font-weight: 800; letter-spacing: .02em; color: var(--text);
    }}
    .brand span {{ color: var(--brand); }}
    .nav {{ display: flex; gap: 18px; flex-wrap: wrap; font-size: .95rem; color: var(--muted); }}
    .hero, .panel {{
      background: var(--panel);
      border: 1px solid rgba(213, 227, 242, 0.9);
      border-radius: 24px;
      box-shadow: var(--shadow);
      backdrop-filter: blur(14px);
    }}
    .hero {{ padding: 48px; margin-bottom: 24px; }}
    .eyebrow {{
      display: inline-flex; align-items: center; gap: 8px; padding: 6px 12px; border-radius: 999px;
      background: var(--brand-soft); color: var(--brand); font-size: .85rem; font-weight: 700;
      margin-bottom: 18px;
    }}
    h1 {{ margin: 0 0 16px; font-size: clamp(2rem, 4vw, 3.3rem); line-height: 1.05; }}
    h2 {{ margin: 0 0 14px; font-size: 1.5rem; }}
    h3 {{ margin: 0 0 10px; font-size: 1.05rem; }}
    p, li {{ color: var(--muted); line-height: 1.85; }}
    .hero-actions {{ display: flex; gap: 14px; flex-wrap: wrap; margin-top: 26px; }}
    .btn {{
      display: inline-flex; align-items: center; justify-content: center;
      min-height: 44px; padding: 0 18px; border-radius: 999px; font-weight: 700;
      border: 1px solid transparent;
    }}
    .btn-primary {{ background: linear-gradient(135deg, var(--brand), #1679d1); color: white; }}
    .btn-secondary {{ background: white; border-color: var(--line); color: var(--text); }}
    .grid {{ display: grid; gap: 20px; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); }}
    .panel {{ padding: 28px; }}
    .meta-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px; }}
    .meta-item {{ padding: 16px 18px; border-radius: 18px; background: rgba(220,236,255,.45); border: 1px solid var(--line); }}
    .footer {{ padding: 24px 0 36px; color: var(--muted); font-size: .9rem; }}
    .legal h2 {{ margin-top: 30px; }}
    .legal ul, .legal ol {{ padding-left: 22px; }}
    .notice {{
      border-left: 4px solid var(--accent);
      background: rgba(13,123,131,.07);
      padding: 14px 16px;
      border-radius: 12px;
      margin: 16px 0;
    }}
    .warning {{
      border-left-color: var(--danger);
      background: rgba(179,63,63,.07);
    }}
    label {{ display: block; font-size: .92rem; font-weight: 700; margin-bottom: 8px; }}
    input, textarea, select {{
      width: 100%; border: 1px solid var(--line); border-radius: 14px; background: white;
      padding: 12px 14px; font: inherit; color: var(--text);
    }}
    textarea {{ min-height: 180px; resize: vertical; }}
    .form-grid {{ display: grid; gap: 18px; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); }}
    .small {{ font-size: .88rem; }}
    .hidden-field {{ position: absolute; left: -9999px; width: 1px; height: 1px; overflow: hidden; }}
    .result {{ margin-top: 16px; font-size: .95rem; }}
    @media (max-width: 720px) {{
      .shell {{ padding: 16px; }}
      .hero, .panel {{ padding: 22px; border-radius: 20px; }}
      .topbar {{ align-items: flex-start; flex-direction: column; }}
    }}
  </style>
</head>
<body>
{body}
</body>
</html>"""


def _base_layout(title: str, body: str, *, canonical_path: str = "/", noindex: bool = False) -> HTMLResponse:
    return HTMLResponse(_base_layout_str(title, body, canonical_path=canonical_path, noindex=noindex))


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


def _public_nav(login_href: str) -> str:
    return f"""
    <div class="topbar">
      <div class="brand">Shuttle<span>Scope</span></div>
      <div class="nav">
        <a href="/">概要</a>
        <a href="/terms">利用規約</a>
        <a href="/privacy">プライバシーポリシー</a>
        <a href="/contact">お問い合わせ</a>
        <a href="{login_href}">ログイン</a>
      </div>
    </div>
    """


def _public_login_href(request: Request) -> str:
    return "https://app.shuttle-scope.com/login"


def should_serve_public_site(request: Request) -> bool:
    host = request.headers.get("host", "").split(":")[0].lower()
    return host in PUBLIC_HOSTS


def _render_home_body(request: Request) -> str:
    login_href = _public_login_href(request)
    return f"""
    <div class="shell">
      {_public_nav(login_href)}
      <section class="hero">
        <div class="eyebrow">Badminton Analysis Platform</div>
        <h1>試合・映像・コンディション情報を、<br>現場で扱いやすい形に整理する ShuttleScope</h1>
        <p>
          ShuttleScope は、バドミントンの試合レビュー、映像確認、選手データ整理、
          チーム内での分析共有を支援するためのソフトウェアです。
          現場での確認と継続的な振り返りを両立できるよう、
          情報を見やすく束ねることを重視しています。
        </p>
        <div class="hero-actions">
          <a class="btn btn-primary" href="{login_href}">アプリに進む</a>
          <a class="btn btn-secondary" href="/contact">お問い合わせ</a>
        </div>
      </section>

      <section class="grid" style="margin-bottom:20px;">
        <div class="panel">
          <h3>映像と試合レビュー</h3>
          <p>試合や練習映像をもとに、レビューや振り返りを行いやすい形で扱えるよう設計されています。</p>
        </div>
        <div class="panel">
          <h3>選手・チーム情報の整理</h3>
          <p>選手情報、試合履歴、観察メモなどを横断して参照し、日常の分析業務を支えます。</p>
        </div>
        <div class="panel">
          <h3>分析共有の支援</h3>
          <p>コーチ・分析担当・選手で見たい情報が異なる前提で、役割に応じた確認をしやすくします。</p>
        </div>
      </section>

      <section class="panel" style="margin-bottom:20px;">
        <h2>ShuttleScope が想定している利用シーン</h2>
        <div class="meta-grid">
          <div class="meta-item"><strong>チーム内レビュー</strong><p>試合直後や週次の振り返りで、映像とメモをまとめて確認。</p></div>
          <div class="meta-item"><strong>分析担当の整理作業</strong><p>分散しがちな試合・選手情報を一か所にまとめ、比較しやすくする。</p></div>
          <div class="meta-item"><strong>選手向け共有</strong><p>共有する情報の粒度を調整しながら、必要な内容を必要な相手に届ける。</p></div>
          <div class="meta-item"><strong>継続的な観察</strong><p>コンディションやレビュー記録を積み重ね、単発で終わらない振り返りにする。</p></div>
        </div>
      </section>

      <section class="panel" style="margin-bottom:20px;">
        <h2>データの扱いについて</h2>
        <p>
          ShuttleScope では、利用目的に応じて試合映像、レビュー情報、選手に関する入力情報などを扱う場合があります。
          具体的な取扱方針は <a href="/privacy">プライバシーポリシー</a> を、
          利用条件は <a href="/terms">利用規約</a> をご確認ください。
        </p>
        <div class="notice">
          本サイトはサービス概要と案内を掲載する公開サイトです。実際のアプリ利用は別ドメインの
          <a href="{login_href}">アプリ本体</a> で行います。
        </div>
      </section>

      <div class="footer">
        <div>ShuttleScope</div>
        <div><a href="/terms">利用規約</a> ・ <a href="/privacy">プライバシーポリシー</a> ・ <a href="/contact">お問い合わせ</a></div>
      </div>
    </div>
    """


_V7_HOME_HTML = r"""<!DOCTYPE html>
<html lang="ja" data-theme="light">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ShuttleScope — バドミントン試合分析プラットフォーム</title>
<meta name="description" content="ストローク単位の記録から試合構造を統計的に可視化するバドミントン分析ワークベンチ。コーチ・アナリスト・選手それぞれの役割に応じた分析レイヤーを提供します。">
<link rel="canonical" href="https://shuttle-scope.com/">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=MigMix+1P:wght@400;700&family=Barlow+Condensed:wght@400;500;600;700;800&display=swap" rel="stylesheet">
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
.logo-mark{width:26px;height:26px;background:var(--blue);border-radius:5px;display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:800;color:#fff;letter-spacing:0;transition:background .25s}
.nav-links{display:flex;align-items:center;gap:28px;list-style:none}
.nav-links a{font-size:13px;color:var(--t2);text-decoration:none;transition:color .15s}
.nav-links a:hover{color:var(--t1)}
.nav-right{display:flex;align-items:center;gap:8px}
.theme-toggle{width:34px;height:34px;border:1px solid var(--bdr2);border-radius:6px;background:transparent;cursor:pointer;display:flex;align-items:center;justify-content:center;font-size:15px;line-height:1;transition:background .15s,border-color .15s;color:var(--t2)}
.theme-toggle:hover{background:var(--blue-lt);border-color:var(--blue)}
.btn-login{font-family:'MigMix 1P',sans-serif;font-size:12px;font-weight:700;padding:7px 18px;border:1px solid var(--bdr2);border-radius:5px;color:var(--t2);background:transparent;text-decoration:none;transition:all .15s}
.btn-login:hover{color:var(--t1);border-color:var(--blue);background:var(--blue-lt)}
.hamburger{display:none;flex-direction:column;justify-content:center;gap:4px;width:36px;height:36px;cursor:pointer;background:none;border:none;padding:4px}
.hamburger span{display:block;height:1.5px;background:var(--t2);transition:transform .2s,opacity .2s;border-radius:2px}
.hamburger.open span:nth-child(1){transform:translateY(5.5px) rotate(45deg)}
.hamburger.open span:nth-child(2){opacity:0}
.hamburger.open span:nth-child(3){transform:translateY(-5.5px) rotate(-45deg)}
.mobile-menu{display:none;position:fixed;top:58px;left:0;right:0;z-index:190;background:var(--surface);border-bottom:1px solid var(--bdr);flex-direction:column;box-shadow:0 4px 16px rgba(0,0,0,0.08)}
.mobile-menu.open{display:flex}
.mobile-menu a{font-size:14px;color:var(--t2);text-decoration:none;padding:14px 24px;border-bottom:1px solid var(--bdr);transition:color .15s,background .15s}
.mobile-menu a:hover{color:var(--t1);background:var(--blue-lt)}

.hero{position:relative;background:var(--hero-bg);padding:100px 40px 80px;overflow:hidden}
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

@media(max-width:767px){
  nav{padding:0 16px}.nav-links{display:none}.btn-login{display:none}.hamburger{display:flex}
  .hero{padding:76px 20px 96px}.hero-inner{grid-template-columns:1fr;gap:0}.hero-panel{display:none}
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
  .hero{padding:80px 28px 64px}.hero-inner{grid-template-columns:1fr 300px;gap:36px}
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
  <a class="logo" href="/"><div class="logo-mark">S</div>ShuttleScope</a>
  <ul class="nav-links">
    <li><a href="#features">機能</a></li>
    <li><a href="#usecases">利用シーン</a></li>
    <li><a href="/privacy">プライバシーポリシー</a></li>
    <li><a href="/contact">お問い合わせ</a></li>
  </ul>
  <div class="nav-right">
    <button class="theme-toggle" id="theme-btn" title="テーマ切り替え">🌙</button>
    <a href="https://app.shuttle-scope.com/login" class="btn-login">ログイン</a>
    <button class="hamburger" id="ham" aria-label="メニュー"><span></span><span></span><span></span></button>
  </div>
</nav>

<nav class="mobile-menu" id="mmenu">
  <a href="#features">機能</a>
  <a href="#usecases">利用シーン</a>
  <a href="/privacy">プライバシーポリシー</a>
  <a href="/contact">お問い合わせ</a>
  <a href="https://app.shuttle-scope.com/login" style="color:var(--blue);font-weight:700">ログイン →</a>
</nav>

<section class="hero">
  <div class="hero-inner">
    <div>
      <h1 class="hero-h1 fa">試合をデータで説明する</h1>
      <p class="hero-tagline fb">直感に統計的な根拠を</p>
      <p class="hero-sub fc">ストローク単位の記録から試合構造を統計的に可視化するバドミントン分析ワークベンチです。コーチ・アナリスト・選手それぞれの役割に応じた分析レイヤーを提供します。</p>
      <p class="hero-sub" style="font-size:12px;opacity:.6;margin-top:-18px;margin-bottom:20px">ShuttleScope is a sports data analysis platform for badminton match analysis. It provides statistical visualization and performance analysis tools for coaches, analysts, and players.</p>
      <div class="hero-tags fd">
        <span class="htag">ストローク分析</span>
        <span class="htag">統計モデル</span>
        <span class="htag">戦術可視化</span>
        <span class="htag">コンディション追跡</span>
      </div>
      <div class="hero-actions fd">
        <a href="https://app.shuttle-scope.com/login" class="btn-cta">アプリに進む <span class="cta-arrow">›</span></a>
        <a href="/contact" class="btn-ghost">お問い合わせ</a>
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
      <h2 class="sec-h2">分析を支える3つの機能</h2>
      <p class="sec-sub">アノテーション・統計解析・役割別アクセスが一体になった設計です。</p>
    </div>
    <div class="feat-grid">
      <div class="feat-card reveal d1">
        <div class="feat-no">01 / ANNOTATION</div>
        <div class="feat-icon"><svg viewBox="0 0 17 17" fill="none" stroke="var(--blue)" stroke-width="1.6"><polygon points="3,2.5 13.5,8.5 3,14.5"/></svg></div>
        <div class="feat-h">ストローク単位のアノテーション</div>
        <p class="feat-p">ラリーをストローク単位で記録します。配球位置・球種・着地点を逐次入力することで、統計モデルの精度が上がります。</p>
      </div>
      <div class="feat-card reveal d2">
        <div class="feat-no">02 / ANALYSIS</div>
        <div class="feat-icon"><svg viewBox="0 0 17 17" fill="none" stroke="var(--blue)" stroke-width="1.6"><circle cx="8.5" cy="5.5" r="2.5"/><path d="M3 14.5c0-3.1 2.4-5.5 5.5-5.5s5.5 2.4 5.5 5.5"/></svg></div>
        <div class="feat-h">統計モデルによる試合解析</div>
        <p class="feat-p">Markov モデル・EPV・コートヒートマップ・疲労指標により試合構造を多角的に可視化します。記録が増えるほど分析の解像度が上がります。</p>
      </div>
      <div class="feat-card reveal d3">
        <div class="feat-no">03 / ROLES</div>
        <div class="feat-icon"><svg viewBox="0 0 17 17" fill="none" stroke="var(--blue)" stroke-width="1.6"><circle cx="3" cy="8.5" r="1.8"/><circle cx="14" cy="4" r="1.8"/><circle cx="14" cy="13" r="1.8"/><line x1="4.7" y1="7.6" x2="12.3" y2="4.9"/><line x1="4.7" y1="9.4" x2="12.3" y2="12.1"/></svg></div>
        <div class="feat-h">役割に応じた分析レイヤー</div>
        <p class="feat-p">コーチ・アナリスト・選手で参照できる情報の粒度が異なります。それぞれの判断に必要なデータを、適切な形で届けます。</p>
      </div>
    </div>
  </div>
</section>

<section class="sec sec-uc" id="usecases">
  <div class="sec-wrap">
    <div class="reveal">
      <div class="sec-kicker">Analysis Capabilities</div>
      <h2 class="sec-h2">試合から読み取れること</h2>
      <p class="sec-sub">ストロークを記録するたびに統計モデルが更新され、試合の構造が可視化されます。</p>
    </div>
    <div class="uc-grid">
      <div class="uc-card reveal d1"><div class="uc-badge">01</div><div><div class="uc-h">ラリー構造の分析</div><p class="uc-p">どのパターンで得点・失点しているかをラリー単位で可視化します。コートヒートマップと配球傾向から試合の構造が見えます。</p></div></div>
      <div class="uc-card reveal d2"><div class="uc-badge">02</div><div><div class="uc-h">得点期待値の算出</div><p class="uc-p">Markov モデルと EPV により各局面の優位性を数値化します。「なんとなく苦しかった」を統計的な根拠に変えます。</p></div></div>
      <div class="uc-card reveal d1"><div class="uc-badge">03</div><div><div class="uc-h">戦術傾向の可視化</div><p class="uc-p">配球パターン・反実仮想分析・セット間比較により、勝敗に影響した戦術要因を特定します。</p></div></div>
      <div class="uc-card reveal d2"><div class="uc-badge">04</div><div><div class="uc-h">コンディションとの相関</div><p class="uc-p">体調指標とパフォーマンスデータを重ねて分析します。疲労が試合展開に与える影響をシーズン単位で追跡できます。</p></div></div>
    </div>
  </div>
</section>

<section class="sec-data">
  <div class="sec-wrap reveal">
    <div class="sec-kicker">Data Policy</div>
    <p class="data-body">ShuttleScope では利用目的に応じて試合映像・レビュー情報・選手に関する入力情報を扱う場合があります。具体的な取扱方針は <a href="/privacy">プライバシーポリシー</a> を、利用条件は <a href="/terms">利用規約</a> をご確認ください。</p>
  </div>
</section>

<section class="sec-fcta reveal">
  <div class="sec-kicker" style="justify-content:center">Get Started</div>
  <h2 class="fcta-h">記録が増えるほど見えてくるものがある</h2>
  <p class="fcta-sub">アカウントをお持ちの方はそのままログインできます。</p>
  <a href="https://app.shuttle-scope.com/login" class="btn-cta" style="font-size:16px;padding:16px 40px">アプリを開く <span class="cta-arrow">›</span></a>
</section>

<footer>
  <a class="footer-logo" href="/"><div class="logo-mark">S</div>ShuttleScope</a>
  <ul class="footer-links">
    <li><a href="/terms">利用規約</a></li>
    <li><a href="/privacy">プライバシーポリシー</a></li>
    <li><a href="/contact">お問い合わせ</a></li>
  </ul>
  <span class="footer-copy">© 2026 ShuttleScope</span>
</footer>

<div class="mob-bar">
  <a href="https://app.shuttle-scope.com/login" class="btn-cta">アプリに進む <span class="cta-arrow">›</span></a>
  <a href="https://app.shuttle-scope.com/login" class="mob-bar-login">ログイン</a>
</div>

<script>
const html=document.documentElement;
const btn=document.getElementById('theme-btn');
const saved=localStorage.getItem('ss-theme');
if(saved){html.dataset.theme=saved;btn.textContent=saved==='dark'?'☀':'🌙'}
btn.addEventListener('click',()=>{
  const next=html.dataset.theme==='dark'?'light':'dark';
  html.dataset.theme=next;btn.textContent=next==='dark'?'☀':'🌙';
  localStorage.setItem('ss-theme',next);
});
const ham=document.getElementById('ham'),mm=document.getElementById('mmenu');
ham.addEventListener('click',()=>{ham.classList.toggle('open');mm.classList.toggle('open')});
mm.querySelectorAll('a').forEach(a=>a.addEventListener('click',()=>{ham.classList.remove('open');mm.classList.remove('open')}));
const obs=new IntersectionObserver(e=>{
  e.forEach(x=>{if(x.isIntersecting){x.target.classList.add('vis');obs.unobserve(x.target)}});
},{threshold:0.1});
document.querySelectorAll('.reveal').forEach(el=>obs.observe(el));
</script>
</body>
</html>"""


def render_public_home(request: Request) -> HTMLResponse:
    return HTMLResponse(_V7_HOME_HTML)


def _render_terms_str(request: Request) -> str:
    login_href = _public_login_href(request)
    body = f"""
    <div class="shell legal">
      {_public_nav(login_href)}
      <section class="panel">
        <h1>ShuttleScope 利用規約</h1>
        <p class="small">最終更新日: 2026-04-21</p>
        <p>本規約は、ShuttleScope の提供条件および利用に関する基本事項を定めるものです。</p>

        <h2>1. 適用</h2>
        <p>本規約は、ShuttleScope のウェブサイト、アプリケーション、および関連機能の利用に適用されます。</p>

        <h2>2. サービス内容</h2>
        <p>
          ShuttleScope は、バドミントンに関する試合レビュー、映像確認、選手情報整理、分析共有その他これらに関連する
          機能を提供します。提供機能は、予告なく追加、変更、停止されることがあります。
        </p>

        <h2>3. 利用者の責任</h2>
        <ul>
          <li>利用者は、自己の責任においてアカウント情報および利用環境を適切に管理するものとします。</li>
          <li>利用者は、法令、所属組織のルール、第三者との契約等を遵守したうえで本サービスを利用するものとします。</li>
          <li>第三者の権利を侵害するデータ、またはそのおそれのあるデータを無断で取り扱ってはなりません。</li>
        </ul>

        <h2>4. 禁止事項</h2>
        <ul>
          <li>本サービスの運営を妨害する行為</li>
          <li>不正アクセス、認証回避、脆弱性探索その他これらに類する行為</li>
          <li>違法または公序良俗に反する目的での利用</li>
          <li>第三者の個人情報、映像、記録等を不適切に共有または公開する行為</li>
          <li>本サービスまたは関連資料を誤解を招く形で転載、再配布、営業利用する行為</li>
        </ul>

        <h2>5. データと権利</h2>
        <p>
          利用者が本サービスに入力、保存、またはアップロードしたデータに関する権利は、法令または別段の定めがない限り、
          当該利用者または正当な権利者に帰属します。利用者は、本サービスの提供、保守、改善、障害対応その他合理的に必要な範囲で、
          当該データが取り扱われることに同意するものとします。
        </p>

        <h2>6. 免責</h2>
        <ul>
          <li>本サービスは、特定の成果、成績向上、分析結果の完全性または正確性を保証するものではありません。</li>
          <li>利用者は、表示内容や分析結果を最終判断の補助情報として利用するものとします。</li>
          <li>通信障害、端末障害、外部サービス障害、保守作業等により本サービスが利用できない場合があります。</li>
        </ul>

        <h2>7. サービス変更・停止</h2>
        <p>運営上または技術上必要がある場合、本サービスの全部または一部を変更、停止、終了することがあります。</p>

        <h2>8. 規約変更</h2>
        <p>本規約は必要に応じて改定されることがあります。改定後の規約は、本サイトまたは関連画面で公表された時点から適用されます。</p>

        <h2>9. お問い合わせ</h2>
        <p>本サービスに関するお問い合わせは、<a href="/contact">お問い合わせフォーム</a> から受け付けます。</p>
      </section>
    </div>
    """
    return _base_layout_str("ShuttleScope | 利用規約", body, canonical_path="/terms")


def render_terms_page(request: Request) -> HTMLResponse:
    return HTMLResponse(_render_terms_str(request))


def _render_privacy_str(request: Request) -> str:
    login_href = _public_login_href(request)
    body = f"""
    <div class="shell legal">
      {_public_nav(login_href)}
      <section class="panel">
        <h1>ShuttleScope プライバシーポリシー</h1>
        <p class="small">最終更新日: 2026-04-21</p>
        <p>本ポリシーは、ShuttleScope における情報の取扱いについて定めるものです。</p>

        <h2>1. 取得する情報</h2>
        <ul>
          <li>アカウント識別情報、表示名、チーム関連情報など、利用に必要な情報</li>
          <li>試合、映像、レビュー、観察メモ、コンディション入力等、利用者が入力またはアップロードする情報</li>
          <li>利用ログ、アクセス時刻、IP アドレス、ブラウザまたは端末に関する基本情報</li>
          <li>お問い合わせフォームを通じて送信された氏名、所属、連絡手段、本文その他の記載内容</li>
        </ul>

        <h2>2. 利用目的</h2>
        <ul>
          <li>本サービスの提供、認証、運用、保守のため</li>
          <li>試合レビュー、分析共有、コンディション確認その他の機能提供のため</li>
          <li>障害対応、セキュリティ確保、不正利用防止のため</li>
          <li>お問い合わせへの対応および連絡のため</li>
          <li>サービス改善、品質向上、機能検討のため</li>
        </ul>

        <h2>3. 第三者提供</h2>
        <p>法令に基づく場合、利用者の同意がある場合、または業務委託その他正当な理由がある場合を除き、取得した情報を第三者へ提供しません。</p>

        <h2>4. 委託・外部サービス</h2>
        <p>
          本サービスでは、運用上必要な範囲でクラウド、トンネル、ホスティング、通知等の外部サービスを利用する場合があります。
          その場合でも、必要最小限の範囲で情報を取り扱うよう努めます。
        </p>

        <h2>5. 保管と安全管理</h2>
        <ul>
          <li>認証、アクセス制御、運用管理その他合理的な安全管理措置を講じます。</li>
          <li>保存期間は、利用目的、運用上の必要性、法令上の要請等を考慮して定めます。</li>
          <li>不要となった情報は、合理的な方法で削除または匿名化するよう努めます。</li>
        </ul>

        <h2>6. お問い合わせ情報の取扱い</h2>
        <p>
          お問い合わせフォームから送信された情報は、問い合わせ対応、運用連絡、迷惑行為防止のために利用します。
          返信のための連絡手段が記載されている場合、その内容を確認および回答の目的で利用することがあります。
        </p>

        <h2>7. 開示・訂正等</h2>
        <p>保有情報の開示、訂正、削除その他の申出については、法令および合理的な運用範囲に従って対応を検討します。</p>

        <h2>8. ポリシー変更</h2>
        <p>本ポリシーは必要に応じて改定されることがあります。改定後の内容は、本サイトまたは関連画面に掲載した時点で効力を生じます。</p>

        <h2>9. お問い合わせ窓口</h2>
        <p>本ポリシーに関するお問い合わせは、<a href="/contact">お問い合わせフォーム</a> をご利用ください。</p>
      </section>
    </div>
    """
    return _base_layout_str("ShuttleScope | プライバシーポリシー", body, canonical_path="/privacy")


def render_privacy_page(request: Request) -> HTMLResponse:
    return HTMLResponse(_render_privacy_str(request))


def _render_contact_str(request: Request, *, preview: bool = False) -> str:
    login_href = _public_login_href(request)
    submit_path = "/api/public/contact"
    body = f"""
    <div class="shell">
      {_public_nav(login_href)}
      <section class="panel" style="margin-bottom:20px;">
        <h1>お問い合わせ</h1>
        <p>
          ShuttleScope に関する導入相談、機能確認、公開サイト内容に関する連絡は、以下のフォームから送信できます。
          返信が必要な場合は、本文または連絡先欄にご希望の連絡手段をご記入ください。
        </p>
        <div class="notice">
          このフォームはメール送信ではなく、ShuttleScope 側の管理画面で確認できる問い合わせとして保存されます。
        </div>
      </section>

      <section class="panel">
        <form id="contact-form">
          <div class="form-grid">
            <div>
              <label for="name">お名前</label>
              <input id="name" name="name" maxlength="120" required>
            </div>
            <div>
              <label for="organization">所属・チーム名</label>
              <input id="organization" name="organization" maxlength="160">
            </div>
            <div>
              <label for="role">立場</label>
              <select id="role" name="role">
                <option value="">選択してください</option>
                <option value="player">選手</option>
                <option value="coach">コーチ</option>
                <option value="analyst">分析担当</option>
                <option value="team_staff">チームスタッフ</option>
                <option value="other">その他</option>
              </select>
            </div>
            <div>
              <label for="contact_reference">返信先や連絡手段</label>
              <input id="contact_reference" name="contact_reference" maxlength="200" placeholder="任意: 連絡先や希望する連絡手段">
            </div>
          </div>

          <div style="margin-top:18px;">
            <label for="message">お問い合わせ内容</label>
            <textarea id="message" name="message" required minlength="10" maxlength="4000"></textarea>
          </div>

          <div class="hidden-field" aria-hidden="true">
            <label for="website">website</label>
            <input id="website" name="website" tabindex="-1" autocomplete="off">
          </div>

          <div style="margin-top:18px; display:flex; gap:12px; flex-wrap:wrap;">
            <button class="btn btn-primary" type="submit">送信する</button>
            <a class="btn btn-secondary" href="/">トップへ戻る</a>
          </div>
          <div id="contact-result" class="result" aria-live="polite"></div>
        </form>
      </section>
    </div>
    <script>
      const form = document.getElementById('contact-form');
      const result = document.getElementById('contact-result');
      form.addEventListener('submit', async (event) => {{
        event.preventDefault();
        result.textContent = '送信中です...';
        const payload = Object.fromEntries(new FormData(form).entries());
        try {{
          const res = await fetch('{submit_path}', {{
            method: 'POST',
            headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify(payload),
          }});
          const data = await res.json().catch(() => ({{}}));
          if (!res.ok) {{
            throw new Error(data.detail || '送信に失敗しました。');
          }}
          form.reset();
          result.textContent = 'お問い合わせを受け付けました。内容を確認のうえ対応します。';
        }} catch (error) {{
          result.textContent = error.message || '送信に失敗しました。時間をおいて再度お試しください。';
        }}
      }});
    </script>
    """
    return _base_layout_str(
        "ShuttleScope | お問い合わせ",
        body,
        canonical_path="/contact" if not preview else "/public-preview/contact",
        noindex=preview,
    )


def render_contact_page(request: Request, *, preview: bool = False) -> HTMLResponse:
    return HTMLResponse(_render_contact_str(request, preview=preview))


def render_public_preview_home(request: Request) -> HTMLResponse:
    return HTMLResponse(_rewrite_preview_links(_V7_HOME_HTML))


def _require_admin(request: Request) -> None:
    ctx = get_auth(request)
    if not ctx.is_admin:
        raise HTTPException(status_code=403, detail="admin role required")


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _enforce_contact_rate_limit(request: Request) -> None:
    ip = _client_ip(request)
    now = datetime.utcnow()
    window = now - timedelta(minutes=15)
    recent = [ts for ts in _recent_contact_requests.get(ip, []) if ts >= window]
    if len(recent) >= 5:
        raise HTTPException(status_code=429, detail="too many inquiries from the same address")
    recent.append(now)
    _recent_contact_requests[ip] = recent


def _notify_inquiry(inquiry: PublicInquiry) -> None:
    webhook = (settings.ss_notify_webhook_url or "").strip()
    if not webhook:
        return
    payload = {
        "text": (
            "New ShuttleScope inquiry\n"
            f"name: {inquiry.name}\n"
            f"organization: {inquiry.organization or '-'}\n"
            f"role: {inquiry.role or '-'}\n"
            f"contact: {inquiry.contact_reference or '-'}\n"
            f"message: {inquiry.message[:500]}"
        )
    }
    try:
        req = urllib.request.Request(
            webhook,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5).read()
    except Exception as exc:
        logger.warning("public inquiry webhook failed: %s", exc)


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


@router.get("/terms")
async def terms_page(request: Request):
    return render_terms_page(request)


@router.get("/privacy")
async def privacy_page(request: Request):
    return render_privacy_page(request)


@router.get("/contact")
async def contact_page(request: Request):
    return render_contact_page(request)


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
        message=re.sub(r"\s+\n", "\n", body.message.strip()),
        ip_address=_client_ip(request),
        user_agent=(request.headers.get("User-Agent") or "")[:400] or None,
    )
    db.add(inquiry)
    db.commit()
    db.refresh(inquiry)
    _notify_inquiry(inquiry)
    return {"success": True, "data": {"id": inquiry.id, "status": inquiry.status}}


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
                created_at=item.created_at.isoformat() if item.created_at else "",
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
