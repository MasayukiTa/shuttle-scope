# auth: reject Unicode whitespace in login id (fuzzy-match fix)

- 検出: 2026-05-24 攻撃 round 277 / 279
- 修正対象: `shuttlescope/backend/routers/auth.py`
- ステータス: ローカル patch 適用済み、本番 deploy + verify 待ち

## 問題

`/api/auth/login` で受け取る `username` / `identifier` の正規化に
Python 既定の `str.strip()` を使っており、Unicode whitespace
(U+00A0 NBSP, U+200B ZWSP, U+3000 IDEOGRAPHIC SPACE, U+FEFF BOM,
U+2007 FIGURE SPACE, U+205F MMSP, U+2001 EM QUAD 等) を含む入力が
DB lookup の前段で削除され、stored username と fuzzy 一致する。

例: `adminTakeuchi_` + U+00A0 → strip 後 `adminTakeuchi_` で admin
ユーザに解決される。正規 admin password を持つ攻撃者は当然認証
できるが、入力文字列の同一性が壊れることで:

- audit log の `details.username` には clean な値だけが残り、
  WAF / 外部監視層がパターン一致できない (rule bypass の余地)
- 入力 string-exact を前提とする将来の付随コードが split-brain
  状態に陥る (例: rate limit cache key に raw username を使う層)
- per-user lockout は User 行単位で集約されるため brute-force
  budget の bypass にはならない (要件確認済) が、定義として fuzzy
  match を残すと将来 regression の温床になる

## 修正内容

`backend/routers/auth.py`

1. `_reject_null_byte_in_id` を `_reject_invalid_chars_in_id` に
   改名し、unicodedata category Zs/Zl/Zp の文字 + ゼロ幅 (U+200B-D,
   U+2060, U+FEFF) を **422 で拒否** する Pydantic validator に拡張。
2. `_normalize_login_id` の strip を `_ASCII_WS = " \t\r\n\x0b\x0c"`
   に限定。Pydantic 層で reject されるはずだが多層防御として残す。

## 攻撃 round 結果

`shuttlescopeattacktest/round279_results.json` 末尾、BYPASS 7 件
(rate limit 429 で評価不能な variant が大量にあったため、実数は
さらに多い見込み):

- A-tail[U+0020 SPACE]
- A-tail[U+2001 EMQUAD]
- A-tail[U+205F MMSP]
- B-head[U+00A0 NBSP]
- B-head[U+2007 FIGSP]
- B-head[U+205F MMSP]
- E-identifier[NBSP]  (identifier field 経由でも同じ)

中間挿入 (`adminTake<NBSP>uchi_` 等) は全 401 = strip 系であり
collapse 系ではないことを確認。

## verify 手順 (deploy 後)

1. 攻撃 R277-A の variant を再実行 → 全 422 になることを確認:
   ```
   cd C:/Users/M118A8586/Desktop/50repo/shuttlescopeattacktest
   python round279_ws_normalize_full.py
   ```
   期待: BYPASS COUNT = 0
2. 正規 login が引き続き動作することを確認:
   - `adminTakeuchi_` + 正 password → 200
   - email login (例: 既存 test user の `xxx@example.com`) → 200
3. C0 制御文字 / NUL byte 拒否が回帰していないことを確認 (round 233 R7-A)

## 副作用検討

- 既存 user の username は全て ASCII で stored 想定 (register validator
  `_validate_login_id` が `[a-zA-Z0-9_-]` whitelist 適用済み) なので
  正規 login で 422 が出る user は存在しない
- email 用 identifier に whitespace を含む正規 case は RFC 5321/5322
  で禁止 (quoted-string ですら通常 reject) のため副作用なし
- `display_name` / `team_name` 等の人間表示フィールドは別 schema で
  validator 対象外。今回の変更で影響なし
