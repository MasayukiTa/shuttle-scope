# 2026-05-07 本番 ScheduledTask の supervisor + /RU SYSTEM 再構成

ユーザ要望「手動復旧せずに済むように本番環境を頑張って修復」に対する
作業ログと検証結果。本番への変更は SSH 経由のオペレーション (本リポジトリ
への直接コミットは生まれない) なので、ここに完全な手順を残す。

## 背景

2026-05-07 のデプロイ時に発覚:
- ScheduledTask `ShuttleScopeBackend` が `/RU kiyus` Interactive モードに戻り、
  PROD_ENV_SPEC.md / INCIDENT_AND_RECOVERY.md が想定していた `/RU SYSTEM` 状態と乖離。
- Action は `backend_daemon.ps1` (一発起動 / auto-respawn なし) で、
  supervisor 設計 (`backend_supervisor.ps1` / mutex + 自動 respawn ループ) は
  リポジトリには存在するが本番 task からは参照されていなかった。
- 結果、backend が落ちても自動復旧せず、SSH での手動復旧を要した
  (連休突入前の最大リスク)。

## 修復実施 (2026-05-07 13:00-13:14)

### 1. 旧タスク XML をバックアップ
- 保管: `サーバ C:\Users\kiyus\Desktop\schedtask_backup\ShuttleScopeBackend_20260507-130558.xml`
- ロールバック手順:
  ```powershell
  Unregister-ScheduledTask -TaskName ShuttleScopeBackend -Confirm:$false
  $xml = Get-Content '<backup path>' -Raw
  Register-ScheduledTask -TaskName ShuttleScopeBackend -Xml $xml
  ```

### 2. supervisor ステージ確認
- `C:\Users\kiyus\Desktop\backend_supervisor.ps1` (5123 bytes, 2026-04-30) と
  リポジトリ内 `shuttlescope/infra/supervisor/backend_supervisor.ps1` は完全一致
- 機能: mutex 風 port-in-use guard、60s health 待機、強制 kill on slow start、
  指数 backoff (5/10/30/60/120/300s)、ログローテ
- `PUBLIC_MODE=1 / HIDE_API_DOCS=1 / HIDE_STACK_TRACES=1` 環境変数を渡す

### 3. SYSTEM 権限の dry run 検証
- supervisor を SYSTEM コンテキストで invoke (Start-ScheduledTask)
- 既存 listener (orphan PID 48988) を検知して `supervisor exiting: port 8765 already in use`
  と log を出して即終了 → mutex 動作を SYSTEM 権限で確認 ✅

### 4. 新タスク登録
```powershell
$action    = New-ScheduledTaskAction -Execute 'powershell.exe' `
              -Argument '-NoProfile -ExecutionPolicy Bypass -File C:\Users\kiyus\Desktop\backend_supervisor.ps1'
$trigger   = New-ScheduledTaskTrigger -AtStartup
$trigger.Delay = 'PT30S'
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -RunLevel Highest -LogonType ServiceAccount
$settings  = New-ScheduledTaskSettingsSet `
              -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -DontStopOnIdleEnd `
              -ExecutionTimeLimit ([TimeSpan]::Zero) `
              -MultipleInstances IgnoreNew `
              -RestartCount 99 -RestartInterval (New-TimeSpan -Minutes 1)
Unregister-ScheduledTask -TaskName ShuttleScopeBackend -Confirm:$false
Register-ScheduledTask -TaskName ShuttleScopeBackend `
  -Action $action -Trigger $trigger -Principal $principal -Settings $settings `
  -Description 'ShuttleScope backend supervisor (mutex + auto-respawn)'
```

確認:
- `UserId: SYSTEM / RunLevel: Highest / LogonType: ServiceAccount` ✅
- Action = backend_supervisor.ps1 ✅

### 5. カットオーバー (orphan kill + supervisor 起動)
- orphan python kill → Start-ScheduledTask
- supervisor 起動 13:10:23 → spawn python 13:10:23 → health 200 received 13:10:36 (13s)
- 親プロセスチェーン確認:
  ```
  listener (system Python uvicorn worker)
    ← .venv/Scripts/python.exe backend/main.py (51180)
      ← powershell.exe backend_supervisor.ps1 (40672)
        ← svchost.exe -k netsvcs -p -s Schedule (2584, Task Scheduler service)
  ```

### 6. ライブフェイルオーバー試験 ✅ PASS
- `Stop-Process -Id <python parent>` 実行
- supervisor.log:
  ```
  13:11:26 python exited (code=-1) after long-watch
  13:11:26 restarting in 5s (failStreak=0)
  13:11:31 spawned python PID=9896
  13:11:43 python ready, entering long-watch mode
  ```
- 外部から health 200 復帰までの計測値 **17 秒**

### 7. Stop-ScheduledTask + Start-ScheduledTask 試験
意図せず判明した重要な挙動:
- `Stop-ScheduledTask` は supervisor (powershell) は kill するが、
  python の子プロセスは Job Object 連動が弱く orphan として生存
- 続いて `Start-ScheduledTask` すると新 supervisor は port-in-use で即 exit
- サービスは継続するが auto-respawn 経路が壊れた状態になる
- 復旧手順: 「orphan python kill → Start-ScheduledTask」をセットで実行する必要あり

**結論**: 通常の backend 再起動は **python kill のみ** を使う。
Stop+Start ScheduledTask はタスク定義の入れ替え時の緊急用 (本作業のような場面)
だけに限定し、必ず後で orphan cleanup + 再 trigger をセットで実行する。

### 8. 最新コミット (a49bde7) 反映 (frontend のみ)
ユーザ要望と直交するが、supervisor が安定したので最新コミットも反映:
- `git stash push shuttlescope/backend/config.py` で本番固有変更を退避
- `git pull --ff-only origin main` → HEAD = a49bde7
- `git stash pop` で config.py 復元 (auto-merge clean)
- `npm install --no-audit --no-fund` (1 package added, 3 changed; ip-address override 反映)
- `npm run build` (modules 2905, css 138.52KB, js 3842.99KB)
- 配信 HTML 確認: 新バンドル `index-CF00OUfb.js` / `index-B92e-hia.css` を参照済 ✅
- Backend 再起動は不要 (frontend 静的ファイルのみ変更)

## 最終状態 (検証時刻 2026-05-07 13:14)

| 項目 | 値 |
|---|---|
| Health | HTTP 200 `{"status":"ok"}` |
| ScheduledTask | `ShuttleScopeBackend` Running, /RU SYSTEM, supervisor.ps1 action |
| supervisor 親 PID | 18244 (powershell) → svchost (2584) → services.exe (1532) |
| backend python 親 | 43612 (.venv) → supervisor 18244 |
| listener | 47532 (uvicorn worker child of 43612) |
| python-multipart | 0.0.27 (CVE-2026-42561 fixed) |
| git HEAD | a49bde7 |
| frontend bundle | index-CF00OUfb.js / index-B92e-hia.css (a49bde7 build) |

## 残リスク (今回 scope 外)

### 🔴 最終リハーサル: OS 再起動試験 (未実施)
新タスクは ONSTART (Delay PT30S) で SYSTEM 権限で発火するため、
理論的にはログオフ状態でも OS 起動から ~1 分以内に backend が立ち上がる。
ただし PROD_ENV_SPEC.md §4 / INCIDENT_AND_RECOVERY.md §7 の最終リハ手順
(`Restart-Computer -Force`) は **物理アクセスできる時間帯にのみ実行する** ルール。

次回ユーザが物理アクセスできる時間帯に:
```powershell
# 1. SSH からは実行しない (物理コンソール推奨)
Restart-Computer -Force

# 2. 5 分待機後、外部 PC から:
curl https://app.shuttle-scope.com/api/health   # HTTP 200 期待
```
通らない場合は SSH で `Get-ScheduledTaskInfo`、`supervisor.log` tail、
`Get-Process python` で順次切り分け。

### 🟡 cloudflared service の復旧自動化 (既存 ✅、ただし要再確認)
INCIDENT_AND_RECOVERY.md §3 / §4 の Critical 1 に記載通り。
`Get-Service cloudflared` で StartType=Automatic を確認しておくこと。
ONSTART 試験時に同時に確認するとよい。

### 🟡 backend_supervisor.ps1 のリポジトリ管理
本番に置いてある `C:\Users\kiyus\Desktop\backend_supervisor.ps1` は
リポジトリ `shuttlescope/infra/supervisor/backend_supervisor.ps1` と完全一致 (2026-04-30 時点)。
将来 supervisor を更新する場合は repo を直して `Copy-Item` で配布する運用を維持する。

## 関連

- `Desktop/shuttlescope_ssh/PROD_ENV_SPEC.md` (改訂済、冒頭に 2026-05-07 注記追加)
- `Desktop/shuttlescope_ssh/INCIDENT_AND_RECOVERY.md` (§9 を追記)
- `Desktop/shuttlescope_ssh/README.md` (内容変更なし、運用手順は INCIDENT.md §9 を参照)
- `shuttlescope/infra/supervisor/backend_supervisor.ps1` (canonical 版)
