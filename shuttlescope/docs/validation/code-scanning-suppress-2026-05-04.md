# Code Scanning Suppress Pass — 2026-05-04

## Background
GitHub Code Scanning (Bandit + DevSkim) で 61 件 open。
内訳: error 13 / warning 12 / note 36。

うち 13 errors と note 数件が `shuttlescope/scripts/security_ci/` の攻撃テスト群
(test_tls_headers.py 19 件 / 他) で**意図的な**弱 TLS / cert validation 無効化。
prod が拒否することを CI で検証する目的。

## Changes

### Bandit
- `.github/workflows/bandit.yml`: `excluded_paths` に `shuttlescope/scripts/security_ci` 追加。
- `.bandit`: 同様に `exclude` に追加。
- `backend/scripts/rotate_field_key.py` (B608 × 2): `# nosec B608` + 鍵テーブル/カラムは
  `TARGETS` 定数 (allow-list) 由来、値は bind parameter。
- `scripts/security_ci/_common.py` (B323): `_create_unverified_context()` は
  `SS_ATTACK_INSECURE=1` opt-in 時のみ。`# nosec B323` 付与。
- `backend/services/billing/stripe_provider.py` (B310): `_STRIPE_API_BASE` ハードコード https。
- `backend/services/billing/komoju_provider.py` (B310): Komoju API base ハードコード https。
- `backend/utils/turnstile.py` (B310): Cloudflare siteverify エンドポイントハードコード。
- `backend/services/mailer/mailchannels.py` (B310): URL を `startswith("https://")` で
  バリデート + suppress。
- `backend/routers/public_site.py` (B310): GeoIP 用 `inquiry.ip_address` を
  `ipaddress.ip_address()` で検証してから URL 組み立てるよう変更。

### DevSkim
- `scripts/security_ci/test_tls_headers.py`: ファイル冒頭に
  `# DevSkim: ignore DS169125,DS169126,DS440000,DS130822,DS106863,DS137138,DS162092` 付与。
- `scripts/security_ci/test_jwt_forgery.py`: `# DevSkim: ignore DS137138,DS162092`
- `scripts/security_ci/test_no_auth_endpoints.py` / `test_smuggling_methods.py`
  / `test_public_endpoints.py`: `# DevSkim: ignore DS137138,DS162092,DS176209`
- `backend/routers/sessions.py`: LAN mode と localhost fallback の `http://` URL に
  `# DevSkim: ignore DS137138` をインラインで付与。

### test_security_invariants.py B108
- 既に `.bandit` / workflow で `shuttlescope/backend/tests` 除外済。
- 残っている alert は前回 scan の残存。次回 push で消える見込み。

## Expected after next scan
- error 13 → **0** (test_tls_headers.py 全て suppress)
- warning 12 → **3 前後** (legit な B310 や B608/B108 残存ケース)
  - 残り 3 件は本番ロジックで個別精査するもの。今回 suppress した分は理由付き。
- note 36 → 大幅減 (DS162092 多数が suppress)

## Validation
- 各 suppress に **# nosec / # DevSkim: ignore** + 理由コメントを付与。
- Bandit / DevSkim とも次回 workflow run で再評価。
- 本番ロジックの仕様変更なし（B310 5 件中 4 件はコメントのみ。public_site の 1 件のみ
  IP 検証ロジック追加で実質安全強化）。

## Rollback
- ファイル単位の `# nosec` / `# DevSkim: ignore` 行をそれぞれ削除すれば元に戻る。
- workflow / .bandit の `excluded_paths` から `shuttlescope/scripts/security_ci` を
  削除すれば security_ci 系も再度スキャン対象になる。
