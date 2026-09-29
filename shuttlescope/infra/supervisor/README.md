# backend / tunnel supervisor (unattended-friendly)

12 日 / 連休等の無人運用に耐えるための backend supervisor + cloudflared Scheduled Task。

## 配置物

| ファイル | 役割 |
|---------|------|
| `backend_supervisor.ps1` | python (uvicorn) の常駐監視・自動再起動。Global Mutex で単一インスタンス保証 |
| `install_supervisor.ps1` | `ShuttleScopeBackend` Scheduled Task を `/SC ONSTART` で登録 |

## 起動経路

```
OS 起動
  └─ ShuttleScopeBackend (ONSTART) → backend_supervisor.ps1 → python.exe (.venv)
  └─ ShuttleScopeTunnel  (ONSTART) → cloudflared tunnel run shuttlescope
```

## クラッシュ復旧

- python が落ちる → supervisor が exponential backoff (5/10/30/60/120/300s) で再起動
- supervisor 自身が落ちる → Scheduled Task は instance を 1 つしか動かさないので手動 /Run が必要
  - `schtasks /Run /TN ShuttleScopeBackend`
- OS 再起動 → 両 task が ONSTART で自動立ち上がり

## SSH 越し再起動

```powershell
# 別 PC から
ssh shuttle-scope "powershell -NoProfile -Command 'Get-NetTCPConnection -LocalPort 8765 -State Listen | ForEach-Object { Stop-Process -Id `$_.OwningProcess -Force }; schtasks /Run /TN ShuttleScopeBackend'"
```

backend が落ちると supervisor が自動で次を spawn するため、kill だけでも復旧する。

## ログ位置

- `shuttlescope/backend/supervisor.log` — supervisor の起動・再起動ログ
- `shuttlescope/backend/backend.stdout.log` / `.stderr.log` — python (uvicorn) ログ
- 10MB 超で `.prev` に rotate (1 世代だけ保持)

## 環境変数 (supervisor が python に渡す)

| 変数 | 値 | 由来 |
|------|---|------|
| `API_PORT` | 8765 (`SS_BACKEND_PORT` で上書き可) | supervisor |
| `LAN_MODE` | true | supervisor (Electron の元実装に合わせる) |
| `ENVIRONMENT` | production | supervisor (`uvicorn reload` 抑制目的) |
| `PYTHONUNBUFFERED` | 1 | supervisor |
| `PYTHONUTF8` | 1 | supervisor |
| `PYTHONIOENCODING` | utf-8 | supervisor |
| `DATABASE_URL` 等 | `.env.development` から | pydantic-settings |

> ⚠️ 現状 `.env.development` で `ENVIRONMENT=development` が設定されていると uvicorn が reload mode で起動 (python が 2 プロセス見える)。動作には影響しないが、uvicorn worker 子プロセスがファイル変更で再起動するため git pull 時に注意。`.env` で `ENVIRONMENT=production` に上書きすると 1 プロセスになる。

## 既知の制限

- 1 サーバ 1 supervisor (Mutex `Global\ShuttleScopeBackendSupervisor`)
- supervisor の親プロセス (Task Scheduler / svchost) が死ぬと supervisor も道連れになる可能性
- cloudflared 自体のクラッシュ復旧は ONSTART Scheduled Task のみ — 12 日中の crash は再起動しない限り回復しない。本番では `cloudflared service install` (Windows Service 化) が望ましい
