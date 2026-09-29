# nginx reverse proxy (production)

ShuttleScope の本番では FastAPI (`127.0.0.1:8765`) の前段に nginx を立てて、
リクエスト単位のログ・レート制限・プローブ早期 404 を担う。Cloudflare
Tunnel の `app.shuttle-scope.com` ingress は最終的にこの nginx に向ける。

## 現状

- 本番ホスト: `MiniTakeuchi` (Windows 11 Pro)
- nginx: 1.31.0 (`C:\tools\nginx-1.31.0\`, Chocolatey 経由)
- サービス: `nginx` (NSSM ラッパー, AUTO_START)
- listen: 80 (Chocolatey デフォルト、未使用) / 8080 (ShuttleScope reverse proxy)
- 後段: `http://127.0.0.1:8765` (FastAPI / uvicorn)

## ファイル

| 用途 | 本番パス | repo 内コピー |
|------|---------|---------------|
| メイン config | `C:\tools\nginx-1.31.0\conf\nginx.conf` | (Chocolatey デフォルト + `include shuttlescope.conf;` 1 行追加のみ) |
| サイト config | `C:\tools\nginx-1.31.0\conf\shuttlescope.conf` | [`shuttlescope.conf`](./shuttlescope.conf) |
| backup | `C:\tools\nginx-1.31.0\conf\nginx.conf.bak.20260520` | — |

## 機能

`shuttlescope.conf` で実現していること:

- `set_real_ip_from 127.0.0.1` + `real_ip_header CF-Connecting-IP` ─ cloudflared
  経由でも実クライアント IP を `$remote_addr` で取れる。
- JSON 形式の `ss_main` アクセスログ (`logs/ss_access.log`)。Cloudflare の
  `cf-ray` / `cf-ipcountry` ヘッダも記録するので CF Logs と突き合わせ可能。
- `limit_req_zone`:
  - `login_zone`: 10 req/min/IP (`/api/auth/login` のみ)
  - `api_zone`: 10 req/s/IP (それ以外、burst 50)
- `limit_conn` 同時接続 50/IP
- 攻撃 probe path (`/.env`, `/wp-admin`, `/.git/*`, `/phpmyadmin`, `/actuator`
  ...) は nginx 段で 404 + `logs/ss_probe.log` に記録 (Python に到達させない)
- WebSocket pass-through (`/ws/`, `/api/ws/`)
- 4 GiB upload + 600s read/write timeout (video upload routes)

## 再現デプロイ手順 (新規ホスト)

```powershell
# 1. インストール
choco install nginx -y

# 2. site config を配置
Copy-Item .\infra\nginx\shuttlescope.conf C:\tools\nginx-1.31.0\conf\

# 3. nginx.conf の http {} 直下に 1 行追加
#    include shuttlescope.conf;

# 4. テスト
& C:\tools\nginx-1.31.0\nginx.exe -t -p C:\tools\nginx-1.31.0\ -c conf\nginx.conf

# 5. サービス化 (choco が NSSM で自動登録するはず)
Restart-Service nginx
```

## Cloudflare Tunnel 切替手順 (TODO — Round 2)

現在 `app.shuttle-scope.com → http://localhost:8765` (FastAPI 直)。これを
`http://localhost:8080` (nginx) に変更する:

1. `C:\Users\kiyus\Desktop\cloudflare-shuttle-scope\config.yml` の ingress
   セクションを編集。
2. `cloudflared` を Restart-Service (SSH は維持される)。
3. `https://app.shuttle-scope.com/api/health` で 200 を確認。

切替後は FastAPI を `127.0.0.1:8765` で listen 続けるが、外部 (Cloudflare 経由)
からは nginx 経由でしか到達できなくなる。

## トラブル対応

| 症状 | 対処 |
|------|------|
| `nginx -s reload` が無反応 | Windows nginx は reload 信号が安定しない。`Restart-Service nginx` を使う |
| `127.0.0.1:8080` が refused | `Get-NetTCPConnection -LocalPort 8080` で listen 確認、無ければ `logs\error.log` を見る |
| アクセスログが大きすぎる | `logs\ss_access.log` を logrotate 相当 (Scheduled Task で move + reopen) |
