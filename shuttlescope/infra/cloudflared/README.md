# Cloudflare Tunnel 運用手順 (ShuttleScope INFRA Phase C)

`config.yml` のテンプレートを埋めたあとのサービス化とゼロトラスト設定手順。

## 1. 共通: トンネル作成

```bash
cloudflared tunnel login
cloudflared tunnel create shuttlescope
# -> <UUID> と ~/.cloudflared/<UUID>.json が生成される
```

`infra/cloudflared/config.yml` の `<UUID>` と `credentials-file` を書き換える。
DNS はダッシュボードまたは CLI で:

```bash
cloudflared tunnel route dns shuttlescope app.example.com
cloudflared tunnel route dns shuttlescope ssh.example.com
```

## 2. Windows サービス化

管理者 PowerShell で:

```powershell
# 設定ファイルを既定パスにコピー (サービスはここを読む)
Copy-Item infra\cloudflared\config.yml $env:USERPROFILE\.cloudflared\config.yml

cloudflared.exe service install
Start-Service Cloudflared
Get-Service Cloudflared
```

ログ: `C:\Windows\System32\config\systemprofile\.cloudflared\` と Event Viewer。

## 3. Ubuntu サービス化

```bash
sudo cp infra/cloudflared/config.yml /etc/cloudflared/config.yml
sudo cloudflared service install
sudo systemctl enable --now cloudflared
sudo systemctl status cloudflared
journalctl -u cloudflared -f
```

## 4. Cloudflare Access (Zero Trust) 推奨設定

SSH / 管理系 hostname は必ず Access Application で保護する。

- `app.example.com`
  - Application type: Self-hosted
  - Policy: Email domain = 自社ドメイン, or Google SSO
  - Session duration: 24h
- `ssh.example.com`
  - Application type: SSH
  - Policy: 個別メール許可リスト + Require MFA
  - Browser rendering 有効化で Web からターミナル可

追加で以下を推奨:

- WAF: Rate limit 100 req/min / IP
- Bot Fight Mode: ON
- Always Use HTTPS: ON
- cloudflared 側は `--protocol http2` もしくは `quic` を環境に応じて固定

## 5. ヘルスチェックとの連携

`scripts/health_monitor.py` は `SS_HEALTH_URL` で向き先を切り替えられる。
外形監視を行う場合は `SS_HEALTH_URL=https://app.example.com/api/health` にして
別ホストから常時稼働させると良い (開発機では `log` Notifier でローカル確認のみ)。
