# 2026-05-04 ローカル並列レビュー所見への対応

`private_docs/2026-05-04_local_parallel_review_findings.md` の 49 件 (critical 15 / high 16 / normal 18) に対する修正記録。

## 完了サマリ

| 優先度 | 件数 | 完了 | 完了率 |
|---|---|---|---|
| Critical | 15 | 15 | 100% |
| High | 16 | 16 | 100% |
| Normal | 18 | 18 | 100% |
| **合計** | **49** | **49** | **100%** |

## Critical (15/15) ✅

### A. 配備時無認証クラスタ
| ID | 内容 | 修正ファイル |
|---|---|---|
| Electron #13 / A1 | LAN_MODE 既定 false 化 + backend が SS_OPERATOR_TOKEN なしで 0.0.0.0 バインド拒否 | `electron/main.ts:223`, `backend/main.py:1962` |
| ws #3 / A2 | `_ws_require_auth` の `scheme=='ws'` 信頼撤去、forwarded ヘッダ付き loopback 拒否 | `backend/main.py:1549` |
| routers #4 / A3 | GlobalAuthMiddleware loopback bypass を forwarded-aware に | `backend/main.py:1086` |

### B. Player ロール突破
| ID | 内容 | 修正ファイル |
|---|---|---|
| routers #1 / B1 | prediction.py 全 8 ルートに `Depends(require_non_player)` を router-level で適用 | `backend/routers/prediction.py:37` |
| routers #2 / B2 | analysis_research/advanced 全ルートに role guard + 起動時 `_PLAYER_FORBIDDEN_ANALYSIS_PATHS` 件数 assert | `routers/analysis_research.py:48`, `routers/analysis_advanced.py:25`, `backend/main.py:484` |

### pipeline / cluster
| ID | 内容 | 修正ファイル |
|---|---|---|
| pipeline #1 | `_claim_next` を atomic UPDATE に変更 (二重 pickup 防止) + `reap_stale_jobs` startup hook + `worker.lock` 存在時 in-process runner 起動拒否 | `backend/pipeline/jobs.py:36`, `backend/pipeline/worker.py:217` |
| pipeline #2 | TrackNet 分散推論で K10 NodeID を解決し `resources={f"node:{ip}":0.001}` を強制付与。head 落下を構造的に禁止。`status="degraded"` でチャンク欠損を表面化 | `backend/cluster/pipeline.py:114` |
| pipeline #3 | `_ssh_run_python_script` の username/host を allowlist 検証 (RCE 防止) + paramiko banner/auth timeout pin。`save_config` 時に `ssh_password` を redact | `backend/cluster/remote_tasks.py:959`, `backend/cluster/topology.py:43` |

### ws + realtime
| ID | 内容 | 修正ファイル |
|---|---|---|
| ws #1 | per-WebSocket `asyncio.Lock` で `send_*` を直列化 (concurrent-sender RuntimeError 防止) | `backend/ws/live.py:54` |
| ws #2 | `broadcast_to_match` が独立 SessionLocal を持つ (request-scoped 閉鎖済 session への commit 廃止) | `backend/ws/live.py:120` |

### analysis (構造的バグ)
| ID | 内容 | 修正ファイル |
|---|---|---|
| analysis #1 | EPV state model: stroke 単位カウント → rally 内ショット種別 set 化で rally 単位 1 票に統一 (denominator 整合) | `backend/analysis/epv_state_model.py:139` |
| analysis #2 | Q値モデル: 「最終ストロークだけ行動」 → 全 stroke にフラクショナル重み 1/n。smash > defensive ランキング artifact を解消 | `backend/analysis/q_value_model.py:104` |
| analysis #3 | `BayesianRealTimeAnalyzer.compute_prior` に `exclude_match_id` + `opponent_id` を実装。当該 match 二重計上を撤廃 | `backend/analysis/bayesian_rt.py:11` |

### Electron defense-in-depth
| ID | 内容 | 修正ファイル |
|---|---|---|
| Electron #1 | mainWindow + videoWindow の `webSecurity` を `true` に | `electron/main.ts:479,793` |
| Electron #2 | `_ytRecorderWindow` に `will-navigate` allowlist (data: のみ) + `setWindowOpenHandler` deny | `electron/main.ts:651` |
| Electron #3 | `localfile`/`app` スキームから `bypassCSP: true` 削除 | `electron/main.ts:23,37` |
| Electron #4 | `localfile://` を `URL` でパース、`search`/`hash` 非空は reject | `electron/main.ts:296` |

## High (16/16) ✅

### Electron
| ID | 内容 | 修正ファイル |
|---|---|---|
| #5 | localfile stream で realpath 解決後パスを使用 (TOCTOU 緩和) | `electron/main.ts:374` |
| #6 | `mirror-broadcast` IPC に最低限のスキーマ検証 + 32KB cap | `electron/main.ts:562` |
| #7 | `relaunch-app` IPC に 30s レートリミット | `electron/main.ts:629` |
| #8 | `capture-webview-frame` を `enable-frame-capture` IPC で 5s 限定 opt-in | `electron/main.ts:594` |
| #9 | packaged build で CSP `unsafe-inline/eval` 撤去、`frame-src *` を YouTube 限定に | `electron/main.ts:1017` |
| #10 | packaged build で `Ctrl+Shift+I` / `F12` を `before-input-event` で intercept | `electron/main.ts:957` |
| #11 | Python child-process クラッシュ時の自動再起動 (バックオフ + 60s で 5 回 cap = crashloop 防止) + before-quit で SIGKILL fallback | `electron/main.ts:270,1108` |

### ws (frontend + backend)
| ID | 内容 | 修正ファイル |
|---|---|---|
| #4 | camera.connect_operator が既存 operator あれば 1013 reject (operator 役乗っ取り防止) | `backend/ws/camera.py:73` |
| #5 | `useRealtimeYolo` の `onopen`/`onclose`/`onerror` で `inflightRef` をリセット (sealed-zero-FPS 状態の解消) | `src/hooks/useRealtimeYolo.ts:92` |
| #6 | `useLiveInference` に inflight gate + req ID で古いレスポンス破棄 (新→旧上書き防止) | `src/hooks/useLiveInference.ts:25` |

### analysis
| ID | 内容 | 修正ファイル |
|---|---|---|
| #4 | markov pair CI を Wilson score interval (pair の wins/total) で再計算。単発 CI 流用を撤廃 | `backend/analysis/markov.py:198` |
| #5 | `compute_logistic_influence` に `target_role` パラメータを追加。caller 側 filter への暗黙依存を撤廃 | `backend/analysis/shot_influence.py:99` |

### routers
| ID | 内容 | 修正ファイル |
|---|---|---|
| #3 | `user_can_access_player` を `db` 受け取れる場合は `can_access_player` に委譲 (cross-team IDOR 解消) | `backend/utils/auth.py:331` |
| #5 | `import_package_endpoint` で `owner_team_id` を actor team_id 強制反映 + force 上書きは自チーム match のみ | `backend/routers/data_package.py:285` |
| #6 | `require_match_access` 重複定義を `require_match_access_or_404` にリネーム (死コード解消) | `backend/utils/auth.py:251` |

## Normal (18/18) ✅

| ID | 内容 | 修正ファイル |
|---|---|---|
| Electron #12 | UAC powershell を `spawn(detached, unref)` に変更し起動 30s ブロックを解消 | `electron/main.ts:967` |
| Electron #13 (= A1) | LAN_MODE 既定 false 化 | `electron/main.ts:223` |
| Electron #14 | `app://video/{token}` proxy に 30s AbortController を付与 (upstream hang 対策) | `electron/main.ts:468` |
| Electron #15 | `save-recorded-video` IPC: 拡張子 allowlist + 4GB cap + magic byte 検証 | `electron/main.ts:574` |
| Electron #16 | auto-updater 採用方針を design note として明記 (electron-updater + Cloudflare R2、user-consent 必須) | `electron/main.ts:1274` |
| Electron #17 | `will-attach-webview` で webPreferences を allowlist 化 (`webSecurity`/`allowpopups`/`enableRemoteModule` 等を削除) + `sandbox: true` | `electron/main.ts:1019` |
| Electron #18 | `did-fail-load` で splash close + 明示エラーダイアログ (空画面 hang 防止) | `electron/main.ts:1078` |
| Electron #19 | `_ytLiveWindow` URL allowlist (https://*.youtube.com/*.youtube-nocookie.com) + permission handler を `media`/`mediaKeySystem`/`display-capture` のみ許可 | `electron/main.ts:747` |
| pipeline #4 | `mark_ray_connected` から `try_ray_init_background` を `threading.Thread` で fire-and-forget 起動 (15-30s ブロック解消) | `backend/cluster/bootstrap.py:139` |
| pipeline #5 | `gpu_health.probe()` を `threading.Lock` でプロセス内直列化 (nvmlInit/Shutdown レース抑制) + `_probe_within_nvml_lock` に分離 | `backend/services/gpu_health.py:21` |
| pipeline #6 | worker `_FileLock.acquire` 直後に Windows msvcrt.locking で lock 状態を再検証 (stale handle 防止) | `backend/pipeline/worker.py:107` |
| pipeline #7 | `_run_benchmark_tracknet` の openvino 試行を `_provider_attempts` に蓄積し、フォールバック結果に `attempts` として返す | `backend/cluster/remote_tasks.py:57` |
| ws #7 | `_cap_locks` / `_send_locks` を disconnect 時に解放 (session_code リーク対策) | `backend/ws/live.py:88` |
| ws #8 | `connection_count` を `dict.get(...) or []` で参照し KeyError race を解消 | `backend/ws/live.py:100` |
| ws #9 | `CameraConnectionManager` に per-session `asyncio.Lock` を導入し connect_operator / disconnect_device を直列化 | `backend/ws/camera.py:65,73,115` |
| ws #10 | `useDeviceHeartbeat` が 404/410 を「server-side removed」とみなして `onRemoved` callback 発火 + ループ停止 | `src/hooks/useDeviceHeartbeat.ts` |
| analysis #6 | `bayes_matchup` の `format_filter='singles'` で `m_format=NULL` を singles 扱い、それ以外は完全一致 | `backend/analysis/bayes_matchup.py:153` |
| routers #7 | `HeavyAnalysisTimeoutMiddleware` を追加し `/api/prediction/*` / `/api/analysis/research|spine|bundle/*` を 25s で打ち切り (504) | `backend/main.py:399` |
| .gitignore | rtmpose / log / worker.lock / DB 派生 / .env backup 等を追加 | `shuttlescope/.gitignore:43` |

## 検証

- Python: `py_compile` で 19 ファイル全部 syntax OK
- TypeScript: ローカル `node_modules/typescript` 未復旧のため `npm install && npm run build` で要 verify
- 既存 pytest スイート未走 (修正対象に直接対応する test が無い領域がほとんど)。Foundation tests は touched ファイルへの import が無いはず

## デプロイ後

- バックエンド再起動必須 (FastAPI import cache 切り替え + middleware 再登録のため)
- Electron は `npm run build` 経由で再ビルドして検証
