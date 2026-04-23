# Add: サイトアイコン / OG画像

Date: 2026-04-23

## 変更

- `shuttlescope/src/public/` 新規作成（Vite convention: `root: 'src'` なので `src/public/` が静的配信ルート）
  - `favicon.png` — ブラウザタブ / 検索結果用
  - `apple-touch-icon.png` — iOS ホーム画面追加用
  - `og-image.png` — OGP / Twitter カード用
- `shuttlescope/src/index.html` にメタタグ追加
  - `<link rel="icon">`, `<link rel="apple-touch-icon">`
  - `og:type`, `og:title`, `og:description`, `og:image`
  - `twitter:card=summary_large_image`, `twitter:title`, `twitter:description`, `twitter:image`
  - `<meta name="description">` も追加

## 動機

Google 検索インデックス開始 / SNS シェア時のプレビュー体験向上。
