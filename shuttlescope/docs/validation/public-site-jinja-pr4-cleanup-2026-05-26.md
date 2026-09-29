# Public site Jinja2 移行 PR4 (最終クリーンアップ) - 2026-05-26

## スコープ
公開サイト Jinja2 移行シリーズ (PR1〜PR4) の最終回。残置していた旧 f-string ベースの
inline HTML 生成関数群を削除し、EN プレビュー用ルートを追加した。

## 変更ファイル
- `shuttlescope/backend/routers/public_site.py` (本体)
- `shuttlescope/docs/validation/public-site-jinja-pr4-cleanup-2026-05-26.md` (本ドキュメント)

## 削除した dead code 一覧

| 関数 / 定数 | 旧行 | 用途 | 削除理由 |
|---|---|---|---|
| `_base_layout_str` | 128-247 | JA 旧 inline HTML レイアウト | PR1/2 で `_base_layout` (HTMLResponse 版) 共々 dead 化 |
| `_base_layout` | 250-251 | 上記の HTMLResponse 薄ラッパ | 呼び出し元なし |
| `_public_nav` | 267-281 | JA 旧 nav 生成 | `_render_home_body` 専用、それも dead |
| `_public_nav_en` | 284-301 | EN 旧 nav 生成 | `_render_*_str_en_legacy` 専用 |
| `_render_home_body` | 317-380 | 旧 JA home body 組み立て | PR0 以前から未参照 dead code |
| `_base_layout_str_en` | 1025-1094 | EN 旧 inline HTML レイアウト | PR3 で `_render_*_str_en_legacy` 専用に |
| `_render_terms_str_en_legacy` | 1113-1219 | EN /terms 旧実装 | PR3 残置、Jinja 版 `_render_terms_str_en` で代替済 |
| `_render_privacy_str_en_legacy` | 1236-1297 | EN /privacy 旧実装 | 同上 |
| `_render_contact_str_en_legacy` | 1315-1415 | EN /contact 旧実装 | 同上 |

加えて `_render_terms_str_en` の docstring から
「PR4 で `_base_layout_str_en` と共に削除予定」のメモを除去
(対象が削除されたため不要)。

## 行数推移
- 公開サイト: **2386 行 → 1674 行** (-712 行)
  - 上記 dead 関数削除で -約 754 行
  - EN プレビュー 4 ルート + EN preview link rewriter で +約 42 行
  - 差し引き -712 行

## 追加した EN preview ルート

| ルート | ハンドラ |
|---|---|
| `GET /public-preview/en` | `_rewrite_preview_links_en(_V7_HOME_HTML)` |
| `GET /public-preview/en/terms` | `_rewrite_preview_links_en(_render_terms_str_en(request))` |
| `GET /public-preview/en/privacy` | `_rewrite_preview_links_en(_render_privacy_str_en(request))` |
| `GET /public-preview/en/contact` | `_rewrite_preview_links_en(_render_contact_str_en(request))` |

`_rewrite_preview_links_en` は JA 版 `_rewrite_preview_links` と同様、
nav の `/en/*` リンクを `/public-preview/en/*` に置換し、canonical 直後に
`<meta name="robots" content="noindex,nofollow">` を強制挿入する。
canonical は本番パスのまま保持 (JA preview と同方針)。

## 既存挙動への影響範囲
- **影響なし** (純粋なクリーンアップ + 新規 EN preview ルート追加のみ)。
  - `_notify_inquiry` の `SS_ADMIN_NOTIFY_WEBHOOK_URL` fallback + Discord UA fix
    (2026-05-26 追加) は **無修正**。
  - `submit_public_contact` / `submit_ban_appeal` POST endpoint 無修正。
  - security ヘッダ / CSP / canonical / og:image いずれも本番ルートでは無変更
    (Jinja 版 `base.html.j2` 経由で従来通り出力)。
  - ban appeal ルート無修正。

## 検証

### syntax check
```
python -c "import ast; ast.parse(open('shuttlescope/backend/routers/public_site.py',encoding='utf-8').read())"
```
→ OK

### TestClient smoke (host: shuttle-scope.com)
全 16 ルート 200 + `<nav>` (`topbar`) + `<footer>` を確認:

| カテゴリ | ルート | 結果 |
|---|---|---|
| JA 本番 | `/contact`, `/privacy`, `/terms` | 200 nav footer |
| EN 本番 | `/en`, `/en/contact`, `/en/privacy`, `/en/terms` | 200 nav footer |
| JA preview | `/public-preview`, `/public-preview/{contact,privacy,terms}` | 200 nav footer |
| EN preview (新規) | `/public-preview/en`, `/public-preview/en/{contact,privacy,terms}` | 200 nav footer |

※ `/` (home) は本ルータ単体テストでは 404 になるが、これは本番では別の
host ベース middleware 経由で `_V7_HOME_HTML` を返すため。本 PR の修正対象外。

### grep 参照ゼロ確認
削除後、`_render_home_body|_base_layout_str|_base_layout\(|_public_nav\(|_public_nav_en|_render_*_str_en_legacy`
のコード参照は `shuttlescope/` 配下に存在しない (過去 PR の validation MD と
`terms.html.j2` 冒頭コメントの説明テキストのみ残置)。

### pytest
`backend/tests/test_public_site*.py` は preexisting の Python 3.10 collection
失敗あり、これは本 PR 修正範囲外。

## PR1〜PR4 累計効果

### 行数
- 公開サイトルータ本体: **約 2700 行台 → 1674 行**
- 切り出した Jinja テンプレ (`backend/templates/public/`):
  - `base.html.j2` 210 行
  - `contact.html.j2` 251 行
  - `privacy.html.j2` 164 行
  - `terms.html.j2` 257 行
  - 合計 **882 行**

### 最終テンプレディレクトリ構成
```
shuttlescope/backend/templates/public/
├── base.html.j2       # JA/EN 共通レイアウト (lang 分岐 + extra_head block)
├── contact.html.j2    # /contact + /en/contact + preview 系
├── privacy.html.j2    # /privacy + /en/privacy + preview 系
└── terms.html.j2      # /terms + /en/terms + preview 系
```

### PR 単位の役割
- **PR1** `3c2741f` /contact (JA) を Jinja 化、共通 nav/footer 部品化
- **PR2** `ceac1a8` /privacy + /terms (JA) を Jinja 化、`{% block extra_head %}` 導入
- **PR3** `0219566` EN バリアント 3 ページを Jinja 化、`_*_str_en_legacy` 残置
- **PR4** (本 PR) dead code 一括削除 + EN preview ルート追加

## ロールバック
本 PR は純粋に削除 + ルート追加のため、`git revert HEAD` で安全に戻せる。
