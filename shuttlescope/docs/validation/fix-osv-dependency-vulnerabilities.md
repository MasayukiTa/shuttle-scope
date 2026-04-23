# Fix: Scorecard Vulnerabilities alert (7 deps)

Date: 2026-04-23

## 問題

GitHub code-scanning の Scorecard Vulnerabilities (#1773, severity=high) が
OSV 由来の 7 件の依存脆弱性を検出。

| GHSA | パッケージ | 現 pin | 修正版 | 対応 |
|------|-----------|--------|--------|------|
| GHSA-6w46-j5rx-g56g | pytest | `>=8.4.0` | 9.0.3 | pin bump |
| GHSA-g3gw-q23r-pgqm | yt-dlp | `>=2025.1.15` | 2026.02.21 | pin bump |
| GHSA-w4rh-fgx7-q63m | ray | コメントアウト | 2.43.0 | コメント pin 更新 |
| GHSA-q279-jhrf-cc6v | ray | コメントアウト | 2.52.0 | コメント pin 更新 |
| GHSA-q5fh-2hc8-f6rq | ray | コメントアウト | 2.54.0 | コメント pin 更新 |
| GHSA-gx77-xgc2-4888 | ray | コメントアウト | **未修正** | osv-scanner.toml で ignore |
| GHSA-6wgj-66m2-xxp2 | ray | コメントアウト | **未修正** | osv-scanner.toml で ignore |

## 修正

- `backend/requirements.txt`
  - `pytest>=8.4.0` → `pytest>=9.0.3`
  - `yt-dlp>=2025.1.15` → `yt-dlp>=2026.02.21`
  - コメントアウト中の `ray>=2.9` → `ray>=2.54.0` にコメント pin 更新。
    production で ray を有効化する際に古い脆弱版を拾わせないため。
- `backend/osv-scanner.toml` 新規作成
  - 未修正 2 件 (`GHSA-gx77-xgc2-4888`, `GHSA-6wgj-66m2-xxp2`) を理由付きで ignore。
  - 両者とも ray cluster を trusted network に閉じて運用する前提で無害化可能。
    ray 公式も cluster は trusted network 前提と明記。

## 運用要件（未修正2件のリスク受容条件）

ray cluster を production で有効化する場合、以下を必ず満たすこと:

1. dashboard / jobs submission API は **プライベートサブネット / Tailscale / VPN** 経由のみで公開する
2. パブリック IP への 0.0.0.0 バインドは禁止
3. 修正版 ray が出たら `osv-scanner.toml` から ignore を削除して再評価

## 検証

- `pytest backend/tests/` が引き続き全通過すること（pytest 9.0.x 互換性確認）
- CI 上で Scorecard Vulnerabilities score が改善することを次回 CI で確認
