# Downloads 24h Archive Job — 2026-05-04

## Background
ユーザ要望: SSD 上の `./videos/` (yt-dlp DL 動画) を 24h 経過後に外付け SSD へ移し、
DB 紐付けを保ったままアノテーション画面から再生可能にする。

接続状態の確認:
- 当 Windows 機の現状ディスクは内蔵 NVMe Samsung 256GB (C:) のみ。
- USB 外付け SSD は未接続。ドライブレターは接続時に動的に割当（D / E / ...）。
- そのため実装は**ドライブレター非依存** (環境変数 `SS_LIVE_ARCHIVE_ROOT` 経由) で行う。

## What was implemented

### 1. 24h scanner (常駐ループ)
- `backend/services/downloads_archiver.py` 新規。
  - `./videos/` 配下の `mp4 / mkv / webm / mov / m4v` を mtime で判定。
  - 24h 以上経過したファイルを `{ARCHIVE_ROOT}/downloads/{YYYY}/{MM}/{prefix}{filename}` へ `shutil.move`。
    - `prefix = m{match_id}_` (DB に紐付け試合あり) / `orphan_` (なし)。
  - 移動成功時、`Match.video_local_path` を `localfile:///{absolute_path}` に書き換え。
- `backend/main.py` lifespan に `archive_loop()` を 30 分間隔の `asyncio.create_task` として登録。
- `SS_LIVE_ARCHIVE_ROOT` 未設定 / パス不在の場合は完全 no-op (既存 yt_live と同じキー)。

### 2. Stream endpoint extension
- `backend/routers/uploads.py::stream_video_for_match`:
  - 旧: `server://` プレフィックスのみサポート → アーカイブ移動後 404 になっていた。
  - 新: `localfile:///` も受理し、`assert_allowed_video_path` で
    `allowed_video_roots()` (= `./videos`, `ss_video_root`, `ss_live_archive_root`,
    `ss_video_extra_roots`) 内であることを確認。
  - これにより 24h 後にブラウザの `<video>` タグからもアーカイブ動画を再生できる。

### 3. Admin API
- `backend/routers/archive_ops.py` 新規。
  - `GET /api/archive/status` — `archive_root` 存在/設定状態 + `./videos/` 配下の集計
    (件数 / バイト数 / 24h 超 = 移動候補件数 / 24h 未満)。
  - `POST /api/archive/scan` — 即時スキャン (常駐ループとは独立)。
- 両エンドポイントとも `require_admin` ガード。

### 4. Tests
`backend/tests/test_downloads_archiver.py` 新規。5 件 pass。
- 24h 未満ファイルはスキップ
- 24h 超ファイルは移動 + `orphan_` プレフィックス
- `SS_LIVE_ARCHIVE_ROOT` 未設定時 no-op
- パス不在 (= 外付け未接続) 時は `missing_root: true` を返してスキップ
- 非動画拡張子 (`.txt`) は対象外

## Operational

### 設定方法 (外付け SSD 接続後)
```
# 環境変数 (バックエンドの起動 user / SYSTEM の環境)
setx SS_LIVE_ARCHIVE_ROOT "D:\shuttlescope_archive" /M
# または .env / settings.py 経由
```
- 未設定時は no-op、設定済みでパス不在時は warn ログのみ (既存 DL 動画は SSD に残る)。
- `youtube_live` と同じルートを共有。配下構成:
  ```
  D:\shuttlescope_archive\
    ├── youtube_live\          (既存: live 録画)
    └── downloads\{YYYY}\{MM}\ (新規: yt-dlp DL)
  ```

### 動作確認
```
GET  /api/archive/status   # archive_root_exists, videos_pending_archive を確認
POST /api/archive/scan     # 即時実行で結果検証
```

## Path-jail safety
- `assert_allowed_video_path` は `allowed_video_roots()` 内のパスのみ通す。
- 既存仕様により `ss_live_archive_root` は許可ルートに含まれている。
- アーカイブ後のパス (`localfile:///D:/shuttlescope_archive/downloads/...`) は
  そのまま許可ルート内であり、ストリーム配信が引き続き有効。

## Validation
- `pytest backend/tests/test_downloads_archiver.py` — 5/5 pass
- syntax check (`ast.parse`) — 全ファイル OK
- `pytest backend/tests/test_video_downloader.py` — 29/29 pass (regression なし)

## Known follow-ups
- フロントの `getVideoSrc` は `match.has_video_local` で判定済 → アーカイブ後も True、変更不要。
- match 33 等の旧 `localfile:///` (実体不在) は前回手動 NULL クリア済。
- 外付け SSD 接続後、`SS_LIVE_ARCHIVE_ROOT` を設定し再起動。`/api/archive/status` で `archive_root_exists: true` を確認後、`POST /api/archive/scan` で初回 sweep を推奨。
