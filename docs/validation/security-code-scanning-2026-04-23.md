# Security: GitHub Alerts 対応 (2026-04-23)

対象: `private_docs/ShuttleScope_GITHUB_ALERTS_2026-04-23.md` の 3 Dependabot + 34 Code Scanning。

## 修正一覧（必須 + 推奨）

### Dependabot — 3件修正
- `@xmldom/xmldom` を 0.8.13+ に bump (`npm install @xmldom/xmldom@^0.8.13`)
  - CVE-2026-41672 / 41674 / 41675 いずれも該当バージョンで解消。

### Critical — 4件修正
- `backend/cluster/topology.py:212` command-line-injection
  - `ipaddress.ip_address(ip)` で ip を正規化してから `ping` の引数に渡すよう変更。
- `backend/cluster/topology.py:237` full-ssrf
  - ip を `ipaddress.ip_address` で正規化、port を `int` 変換し範囲チェック。URL 組立に正規化済みの値を使用。
- `backend/main.py:232` command-line-injection
  - `primary_ip` を `ipaddress.ip_address` で検証、`num_cpus` / `num_gpus` を `int` 強制。
- `backend/routers/cluster.py:284` command-line-injection
  - `body.node_ip` / `body.port` / `body.num_cpus` / `body.num_gpus` を型検証してから subprocess に渡すよう変更。

### High — 9件修正
- `backend/main.py:1138-1148` path-injection (x4)
  - asset_path をセグメント分割し、正規表現 `^[A-Za-z0-9_.\-]+$` と拡張子ホワイトリストで制限。resolve 後に `_assets_dir` 配下であることを検証。
- `backend/routers/sync.py:377` path-injection
  - 同期フォルダを基準に結合してから resolve、配下チェックを最優先。
- `backend/routers/video_import.py:96/98/105` path-injection (x3)
  - 拡張子ホワイトリスト、resolve 後の再チェック、NUL/制御文字拒否を追加。
- `src/components/video/WebViewPlayer.tsx:103` xss-through-dom
  - `new URL()` で http(s) のみ許可し、正規化後の URL を設定。

### Medium — 1件修正
- `backend/main.py:1178` url-redirection (SPA catch-all)
  - `://` / 逆スラッシュ / プロトコル相対 URL を拒否、文字集合を制限。

## 対応保留（既知リスクとして許容）

| 種別 | 件数 | 理由 |
|------|------|------|
| paramiko-missing-host-key-validation | 4 (`remote_tasks.py:677`, `cluster.py:588/642/692`) | クラスタ SSH はループバック/プライベート LAN 限定で使用。運用上 known_hosts を都度更新できないため AutoAddPolicy のまま許容。 |
| stack-trace-exposure | 14 (`analysis_research.py`, `cluster.py`, `db_maintenance.py`, `sync.py`, `tracknet.py`, `tunnel.py`) | 多くは pydantic validation message の再送出や内部エラー文言であり、実際のスタックは返さない。個別見直しは次回以降に段階的対応。 |
| disabling-electron-websecurity | 2 (`electron/main.ts:303/445`) | `localfile://` スキームでローカル動画を再生する設計上、現時点で webSecurity を有効化できない。デスクトップアプリ内でのみ発火。 |

## 検証
- `cd shuttlescope && npm run build`（`NODE_OPTIONS=--max-old-space-size=16384` 必須）
- バックエンドは import 成功 + `python -m pytest backend/tests` スモーク
- 実サーバー側は `git pull` 後に `/api/health` 200 を確認

## メモ
- `SS_PUBLIC_MODE=1` に依存する追加ゲーティングは今回行わない（ユーザー指示）。
