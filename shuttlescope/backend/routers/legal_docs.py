"""legal_docs.py — repo root の PRIVACY.md / TERMS_OF_SERVICE.md / DATA_CONTRIBUTION_TERMS.md
を取得して HTML render するエンドポイント群。

エンドポイント:
  GET /legal/privacy           — PRIVACY.md (full version)
  GET /legal/terms             — TERMS_OF_SERVICE.md (full version)
  GET /legal/data_contribution — DATA_CONTRIBUTION_TERMS.md
  GET /en/legal/privacy        — 同上 (英語、現状同じ .md を再利用)
  GET /en/legal/terms
  GET /en/legal/data_contribution

OnboardingConsentPage の iframe はこの /legal/* を読む。public_site.py の
/privacy /terms はトップページ用の **簡易版** なのでそちらは残す
(リンク先を分ける = 用途分離)。

セキュリティ:
  - 認証不要 (公開法務文書)
  - render される md は repo 内に commit 済みのもののみ。path traversal の
    余地なし (path 固定)。
  - middleware で X-Frame-Options: SAMEORIGIN + CSP frame-ancestors 'self'
    を /legal/* に適用 (main.py 側で対応)。
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import markdown as _md
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["legal-docs"])

# repo root を解決 (backend/routers/ から 3 つ上が repo root)
_REPO_ROOT = Path(__file__).resolve().parents[3]

# allowed slug -> .md filename (path traversal の余地を作らない whitelist)
_DOC_MAP: dict[str, str] = {
    "privacy": "PRIVACY.md",
    "terms": "TERMS_OF_SERVICE.md",
    "data_contribution": "DATA_CONTRIBUTION_TERMS.md",
}

# 同じドキュメントの英語版があれば差し替える (今は同一 .md を再利用)。
_DOC_MAP_EN: dict[str, str] = {
    "privacy": "PRIVACY.md",
    "terms": "TERMS_OF_SERVICE.md",
    "data_contribution": "DATA_CONTRIBUTION_TERMS.md",
}


def _render_markdown_page(slug: str, lang: str = "ja") -> str:
    table = _DOC_MAP_EN if lang == "en" else _DOC_MAP
    fname = table.get(slug)
    if not fname:
        raise HTTPException(status_code=404, detail=f"unknown legal doc: {slug!r}")
    md_path = _REPO_ROOT / fname
    if not md_path.is_file():
        raise HTTPException(status_code=500, detail=f"md file missing: {fname}")
    try:
        md_text = md_path.read_text(encoding="utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"read failed: {e}") from None

    html_body = _md.markdown(
        md_text,
        extensions=["extra", "sane_lists", "toc"],
        output_format="html5",
    )

    title = {
        "privacy": "Privacy Notice" if lang == "en" else "プライバシーポリシー",
        "terms": "Terms of Service" if lang == "en" else "利用規約",
        "data_contribution":
            "Data Contribution Terms" if lang == "en" else "データ提供規約",
    }.get(slug, slug)

    # スタンドアロン HTML — popup iframe で表示するので body だけで十分。
    # font-family は OS-native + 印刷でも読める stack を選ぶ。
    # CSP / X-Frame-Options は middleware で別途付与される。
    return f"""<!DOCTYPE html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{
    margin: 0;
    padding: 16px 20px 48px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                 "Hiragino Sans", "Yu Gothic UI", "Meiryo", sans-serif;
    font-size: 14px;
    line-height: 1.7;
    color: #222;
    background: #fff;
    max-width: 920px;
  }}
  @media (prefers-color-scheme: dark) {{
    body {{ color: #e5e7eb; background: #111827; }}
    a {{ color: #93c5fd; }}
    code {{ background: #1f2937; color: #f3f4f6; }}
    blockquote {{ border-left-color: #374151; color: #9ca3af; }}
  }}
  h1 {{ font-size: 22px; margin-top: 0; border-bottom: 2px solid #d1d5db; padding-bottom: 6px; }}
  h2 {{ font-size: 18px; margin-top: 28px; border-bottom: 1px solid #e5e7eb; padding-bottom: 4px; }}
  h3 {{ font-size: 15px; margin-top: 22px; }}
  h4 {{ font-size: 14px; margin-top: 18px; color: #374151; }}
  p {{ margin: 10px 0; }}
  ul, ol {{ padding-left: 22px; }}
  li {{ margin: 4px 0; }}
  code {{ background: #f3f4f6; padding: 1px 5px; border-radius: 3px; font-size: 12.5px; }}
  pre {{ background: #f3f4f6; padding: 10px; border-radius: 4px; overflow-x: auto; }}
  table {{ border-collapse: collapse; margin: 10px 0; width: 100%; }}
  th, td {{ border: 1px solid #d1d5db; padding: 6px 10px; text-align: left; }}
  th {{ background: #f3f4f6; }}
  blockquote {{ border-left: 4px solid #d1d5db; padding-left: 10px; margin: 10px 0; color: #6b7280; }}
  hr {{ border: none; border-top: 1px solid #e5e7eb; margin: 20px 0; }}
  /* 印刷時もコントラストを担保 */
  @media print {{
    body {{ color: #000; background: #fff; padding: 0; }}
  }}
</style>
</head>
<body>
{html_body}
</body>
</html>
"""


@router.get("/legal/privacy", response_class=HTMLResponse)
def legal_privacy_ja() -> HTMLResponse:
    return HTMLResponse(_render_markdown_page("privacy", "ja"))


@router.get("/legal/terms", response_class=HTMLResponse)
def legal_terms_ja() -> HTMLResponse:
    return HTMLResponse(_render_markdown_page("terms", "ja"))


@router.get("/legal/data_contribution", response_class=HTMLResponse)
def legal_dct_ja() -> HTMLResponse:
    return HTMLResponse(_render_markdown_page("data_contribution", "ja"))


@router.get("/en/legal/privacy", response_class=HTMLResponse)
def legal_privacy_en() -> HTMLResponse:
    return HTMLResponse(_render_markdown_page("privacy", "en"))


@router.get("/en/legal/terms", response_class=HTMLResponse)
def legal_terms_en() -> HTMLResponse:
    return HTMLResponse(_render_markdown_page("terms", "en"))


@router.get("/en/legal/data_contribution", response_class=HTMLResponse)
def legal_dct_en() -> HTMLResponse:
    return HTMLResponse(_render_markdown_page("data_contribution", "en"))
