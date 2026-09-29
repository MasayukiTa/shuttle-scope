# 2026-05-07 ローカル並列再レビュー所見への対応

`private_docs/2026-05-04_local_parallel_rereview_findings.md` で再指摘された
PARTIAL / NOT FIXED / NEW の項目に対する修正記録。

## 完了項目

### 🚨 即時対処 (functional break / 即時バグ)
| ID | 内容 | 修正ファイル |
|---|---|---|
| NEW-A | SSH redaction が認証破壊。`SS_K10_SSH_PASSWORD` (worker 個別 `SS_<ID>_SSH_PASSWORD` も) env-var fallback を実装。REDACTED センチネルは無効値扱い | `backend/cluster/remote_tasks.py:951` |
| NEW-N2 | `require_player_self_or_privileged` が coach/analyst を全 403。`Depends(get_db)` 追加 + `can_access_player` 直呼び出しで team scope 判定 | `backend/utils/auth.py:600` |
| NEW-N1 | `HeavyAnalysisTimeoutMiddleware` の prefix mismatch。`_HEAVY_EXACT_PATHS` を `_build_player_forbidden_analysis_paths` と同様に各ルーターから動的収集、`/api/prediction/*` は wildcard 維持 | `backend/main.py:407` |
| camera ws #4 / NEW-N6 | operator role 認証を JWT claim ベースで強制 (admin/analyst/coach のみ)。`connect_device` / `connect_viewer` / `disconnect_operator` / `disconnect_viewer` を `_slock` で直列化、`disconnect_operator` を async 化 | `backend/main.py:1716`, `backend/ws/camera.py:104,124,137`, `backend/tests/test_websocket_signaling.py:548` |

### 🟡 cluster mode 移行前 / 構造的な穴
| ID | 内容 | 修正ファイル |
|---|---|---|
| NEW-B | `_claim_next` PostgreSQL race。dialect 判定で PG では `with_for_update(skip_locked=True)` 行ロック取得後に UPDATE。SQLite はそのまま conditional UPDATE | `backend/pipeline/jobs.py:37` |
| NEW-F | `dispatch_tracknet_inference` node-pin 漏れ。`target_ip` 引数追加 + ray.nodes() で head 除外 + `resources={node:ip}` 強制 | `backend/cluster/remote_tasks.py:1379` |
| NEW-D | `routers/cluster.py:detect_worker_hardware` の同期 SSH dispatch を `asyncio.to_thread + wait_for(100s)` 化 + handler を async 関数に | `backend/routers/cluster.py:488` |
| #4 | `ALLOW_LOOPBACK_NO_AUTH` env kill-switch (config.py + GlobalAuthMiddleware + `_ws_require_auth`) | `backend/config.py:24`, `backend/main.py:1147,1635` |

### 🟢 経時対処 (mitigation)
| ID | 内容 | 修正ファイル |
|---|---|---|
| Electron #2 部分緩和 / N1 | `enable-frame-capture` 孤児 IPC を削除し `capture-webview-frame` を「直近 5s 以内の物理 user gesture」フラグで守る | `electron/main.ts:660,1066` |
| Electron #6 | `mirror-broadcast` shape schema (type allowlist `video-src`/`overlay`/`cv-toggle`/`play-state`) | `electron/main.ts:572` |
| Electron N3 | `_ytLiveWindow` に `will-navigate` allowlist + `setWindowOpenHandler` deny | `electron/main.ts:773` |
| Electron N4 | dev CSP の発動条件を `app.isPackaged \|\| NODE_ENV !== 'development'` の AND に強化 | `electron/main.ts:1213` |
| NEW-Q | q_value Wilson CI に effective sample size `n_eff = (Σw)² / Σw²` を反映 | `backend/analysis/q_value_model.py:73,118,134` |
| pipeline #11 / NEW-C | `_FileLock.is_pid_alive` で PID 生存確認 + `start_job_runner` で stale lock を自動削除 (kill -9 worker の dual-deadlock 解消) | `backend/pipeline/worker.py:107`, `backend/pipeline/jobs.py:189` |
| NEW-E | `gpu_health._NVML_LOCK` を module top-level に移動 (lazy-init 競合解消) | `backend/services/gpu_health.py:11` |
| ws N4 | `broadcast` を `asyncio.gather` で並行化 (遅いクライアント 1 台が DB session を長時間保持しないよう) | `backend/ws/live.py:103` |
| NEW-N3 | prediction `_upsert_prematch_prediction` 呼び出しに actor の team_id を渡す (全スコープ書き込み防止) | `backend/routers/prediction.py:283` |

## 残課題

- pipeline #5 の **cross-process race** (API + worker が同時 nvml probe) は file-lock or DB advisory lock が必要 — 別 NORMAL TODO
- routers `_HEAVY_EXACT_PATHS` の動的収集対象が startup 時 1 回のみ。後から登録されるルーターは対象外 — 起動順保証は現状 OK だが、middleware 自体を per-request 動的化する案も検討余地あり

## 検証

- Python: 13 ファイル `py_compile` パス
- TypeScript: 既存 `npm install` を回したあと `npm run build` で要 verify
- 既存 pytest: `test_websocket_signaling.py:test_disconnect_operator_clears_reference` / `test_disconnect_unknown_session_safe` を `anyio.run` ベースに書き換え

## デプロイ後

- 本番 backend に `SS_K10_SSH_PASSWORD` (または `SS_<WID>_SSH_PASSWORD`) 環境変数を設定 (`.env.development` 推奨。SS_K10 だと worker_id=K10 にマッチ)
- `SS_ALLOW_LOOPBACK_NO_AUTH=0` を本番 `.env` に設定 (cloudflared 経由のため loopback 緩和は不要)
- backend 再起動でミドルウェア assert + lock 検証を反映
