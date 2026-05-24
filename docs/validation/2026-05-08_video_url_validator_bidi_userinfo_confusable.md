# video_url validator: bidi / userinfo / confusable host reject

実施日: 2026-05-08
発見ラウンド: round179 N5

## 背景

`/api/matches` の create / update で受け取る `video_url` は、フロントエンドで anchor として render される (試合詳細画面の動画リンク等)。validator は既に以下を実装済:

- max length 500
- 制御文字 (CR/LF/Tab/NUL) reject
- スキーム allowlist (http/https のみ、javascript/data/file 等 reject)
- 内部/loopback/private IP reject (round65 / round176 系で導入)

しかし以下が抜けていた。

## Finding (round179 N5)

| ケース | 入力 | 結果 |
|---|---|---|
| ZWSP 埋め込み | `https://example​.com/x` (U+200B 含む) | 200 通過 |
| RTLO in path | `https://example.com/‮txt.mp4` (U+202E) | 200 通過 |
| userinfo redirect | `https://safe.com@evil.com/x.mp4` | 200 通過 |
| 全角 period | `https://safe．com/x.mp4` (U+FF0E) | 200 通過 |

実害:
- ZWSP/RTLO は anchor 表示時に文字列を欺く (拡張子偽装、host 偽装)
- userinfo は `@` 後ろが実 host になるため、`safe.com@evil.com` が `safe.com` への link に見える classic phishing
- 全角 period は `safe．com` が `safe.com` に視覚的に類似 (homograph 攻撃)

## 修正

`backend/routers/matches.py` の `_validate_match_enums` 内 video_url 検証に以下を追加:

1. `_BIDI_FORMAT_CHARS` (ZWSP/ZWNJ/ZWJ/LRE/RLE/PDF/LRO/RLO/LRI/RLI/FSI/PDI/BOM 等) を URL 内で reject
2. `urlparse(vu).username / password` が None でなければ reject
3. host 内の `．` (U+FF0E) / `。` (U+3002) / `｡` (U+FF61) を reject

`tournament` / `round` / `final_score` 等の他フィールド向けに既に同 `_BIDI_FORMAT_CHARS` が定義済 (round167 X5 修正で導入)。これを video_url にも適用する形。

## 仕様内に残す挙動

- IDN ドメイン (`https://例え.jp/`) は許可 (合法的な日本語ドメイン)
- punycode (`xn--r8jz45g.jp`) は許可
- 一般的なホモグラフ (Cyrillic 'а' 等) はトレードオフ大なので保留 (IDN を全 reject すると正規ユーザに不便)

## 検証

修正後 production deploy → round179 N5 を再実行し以下が 422 になることを確認:
- `vu_zwsp_embed` → 422 (format character)
- `vu_rtlo_in_path` → 422 (format character)
- `vu_at_redirect` → 422 (userinfo)
- `vu_unicode_dot` → 422 (confusable)

通過していい挙動:
- `vu_nonascii_domain` → 200 (IDN 許可)
- `vu_punycode` → 200 (punycode 許可)
