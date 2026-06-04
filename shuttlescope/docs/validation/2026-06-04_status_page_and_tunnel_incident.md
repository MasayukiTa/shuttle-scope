# ステータス/メンテ機能 + 2026-06-04 トンネル障害記録

## 1. ステータス/メンテ機能 (backend 完了, frontend は次段)
サーバ稼働状況・予定メンテ・障害インシデントを公開する機能。

### API
- `GET /api/public/status` — **公開(認証不要, `/api/public/*` allowlist)**。
  返却: `overall`(operational/degraded/down) + `active_incidents` + `recent_incidents` + `maintenance` + `checked_at`。
  overall 判定: 未解決に critical→down / major→degraded / minor のみ→degraded / 無→operational。
- `POST /api/status/incidents`・`PATCH /api/status/incidents/{id}` — **admin**。began_at/resolved_at/reason を運用者が記す。
- `POST /api/status/maintenance`・`PATCH /api/status/maintenance/{id}` — **admin**。「x月y日 AA時から BB時間」を告知。

### DB (migration 0039)
- `status_incidents`(title, reason, severity, component, status, began_at, resolved_at)
- `maintenance_windows`(title, body, scheduled_start, scheduled_end, status)

### 設計方針
- **死活の"時刻"は運用者記録**(began/resolved)。"理由"も手動(自動判定はしない)。v2 で heartbeat 自動 uptime。
- 公開ページ(Jinja `/status`) + トップバナーは本 API を読む = **次段(frontend)で実装**。

## 2. インシデント記録: 2026-06-04 Cloudflare トンネル全断
- **事象**: prod (MiniTakeuchi) への Cloudflare Access トンネルが間欠瞬断 → 完全断 (`bad handshake` 継続)。
- **切り分け**: クライアント internet は正常 (GitHub SSH OK)。**prod 側 cloudflared が edge との接続を喪失**。
- **メモリ**: 64GB 中 ~10GB 使用 = OOM ではない (ユーザ確認)。
- **推定原因**: 長期連続起動による cloudflared 劣化 + **GPU 動画生成ジョブが cloudflared を starve させたトリガー** (タイミング一致)。
- **影響**: SSH/deploy 検証/動画転送が全て不可。動画 (tracking_improved_30s) は prod 上に生成済み・無傷で復帰待ち。
- **復旧**: トンネルが唯一の遠隔路のため遠隔復旧不可 → **prod ローカルで cloudflared (or OS) 再起動が必要**。
- **再発防止**: ①cloudflared を auto-restart サービス + watchdog 化 ②重い GPU/CPU ジョブで cloudflared を starve させない (DMZ 機分離 / 優先度確保) ③本ステータス機能で可視化。
- **メモ**: 復帰後に「backend が最新 commit で稼働しているか」「cloudflared 健全性」を必ず検証する。

(本記録は将来の status_incidents 登録の手動ソースにもなる)
