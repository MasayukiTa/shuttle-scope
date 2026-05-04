# 2026-05-04 データ消失事故とリカバリー記録

## 事象

2026-05-04 16:11 頃、shuttle-scope のローカル試験環境で `/ultrareview 11` (PR #11 = 全リポ diff 合成 PR) を実行中、**gitignored 領域がすべて wipe された**。

## 影響範囲

| 項目 | 状態 | 規模 |
|---|---|---|
| `private_docs/` | 全削除 | SPEC, TASKS v1〜v5, PRD.docx, RESEARCH_ROADMAP, EPV/TrackNet 等 21 PDF |
| `shuttlescope/docs/validation/` | 219 件削除 | 4/6 以降の validation report |
| `shuttlescope/backend/db/*.db*` | 全削除 | live DB + WAL + SHM + 4/16 pre-vacuum (1.9GB) + 4/24 + 4/26 + compact = 計 2.2GB |
| `shuttlescope/backend/tracknet/weights/` | 全削除 | TrackNet TF/ONNX/OpenVINO 6 種 |
| `shuttlescope/backend/yolo/weights/yolov8n_openvino/` | 全削除 | OpenVINO IR 3 種 |
| `shuttlescope/backend/models/rtmpose_m_simcc.onnx` | 削除 | 54MB の pose 重み |
| `shuttlescope/.env.development*` | 全削除 | 環境設定 |
| 診断 .py 17 + ray_head_run.ps1 | 全削除 | cluster 起動・診断スクリプト |

## 原因

`/ultrareview` は内部で working tree のクリーンスナップショットを作成するため `git stash --include-untracked` または `git clean -fdx` 相当を実行する。これと「commit-tree で作った orphan ブランチ (PR #11 用) への checkout」が組み合わさり、untracked + ignored ファイルが連鎖的に削除された。`git checkout --orphan` 単独や通常の checkout だけなら起きない。

## 復旧経路と結果

| チャネル | 復旧件数 | 用途 |
|---|---|---|
| 本番 SSH (`ssh.shuttle-scope.com`) | ~700 ファイル / ~2.4GB | private_docs フル, DB バックアップ全種, weights, validation 219, etc. |
| Claude session jsonl (`~/.claude/projects/*.jsonl` の Read 結果抽出) | 39 ファイル | 本番に無かった 4/22-5/4 の最新 .md (5/4 当日 5 件含む) |
| Windows Previous Versions / Shadow Copy | 0 | 設定無効で利用不可 |

**完全復旧:** 本番が ~4/21 までスナップショット保持していたため、4/21 以前は本番から、4/21 以降の md は jsonl から復元。バイナリ (PRD.docx, DB, モデル重み) は jsonl 経由不可だが本番に残存。

**完全復旧不能:**
- 4/21〜5/4 のローカル専用更新で Claude が一度も Read していないファイル (unknown)
- HuggingFace cache (元々未使用、本番にも無し)
- 動画 (本番が canonical のため取得不要と判断、ローカル試験では SSH 経由で参照)

## 再発防止 (3 層)

### 1. .gitignore 追加 (今回適用済み)

inner `shuttlescope/.gitignore` に以下を追加:
```
backend/*.log
backend/*.log.prev
backend/supervisor.log
backend/data/worker.lock
backend/db/*.db-shm
backend/db/*.db-wal
backend/db/*.db.compact
backend/db/*.db.bak-*
backend/db/*.db.sqlite-backup-*
backend/models/rtmpose*.onnx
backend/models/rtmpose*.pt
backend/models/trt_cache/
.hypothesis/
.env.development.bak.*
.env.production.bak.*
```

### 2. 運用ルール

- `/ultrareview` 実行前に必ず以下を実行:
  ```
  TS=$(date +%s)
  cp -r private_docs /tmp/backup_private_docs_$TS
  cp -r shuttlescope/backend/db /tmp/backup_db_$TS
  cp -r shuttlescope/backend/tracknet/weights /tmp/backup_tracknet_$TS
  cp -r shuttlescope/backend/yolo/weights /tmp/backup_yolo_weights_$TS
  cp shuttlescope/.env.development* /tmp/backup_env_$TS/
  ```
- `git checkout --orphan` + `git commit-tree` で合成ブランチを作る前にも同じバックアップ
- shuttle-scope のような patent 関連リサーチデータを抱えるリポでは厳守

### 3. 自動バックアップ (TODO)

- Windows Task Scheduler に robocopy job を登録 (1 日 1 回 private_docs と DB を外付け SSD に sync)
- できれば本番への push 頻度も `~4/21` 止まりだったのを定期化

## 関連参照

- 今回の commit ハッシュ: 復旧本体は本ファイル含む validation MD の add 1 commit に集約
- PR #11 はクローズ済み (ultrareview 用 synthetic PR)
- Claude memory: `feedback_ultrareview_data_loss.md`, `project_2026-05-04_data_loss_incident.md`
