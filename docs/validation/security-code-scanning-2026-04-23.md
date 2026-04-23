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

---

## 追加対応: stack-trace-exposure 14 件の総ざらい (同日)

コーディング作業環境にいる間に実リスクを潰す方針で、保留していた 14 件を全て対応。

### 方針
- 外部返却文字列/dict から `str(exc)` / `traceback` 情報を除去
- 詳細は `logger.warning` / `logger.exception` でサーバ側ログに限定
- ユーザー向けには汎用メッセージのみ返す

### 修正箇所
| 行 | ファイル | 対応 |
|----|---------|------|
| #7, #8 | `analysis_research.py:332/340` | `interval_report` を try/except で囲み、失敗時は汎用 `error` を返却。成功時も `data` を安全フィールドのみ再構築。|
| #42 | `cluster.py:509` (list_ray_workers) | 各 worker の `ping` dict から `error` キーを pop |
| #54 | `cluster.py:576` (wake_worker_node) | `topology.wake_worker` 戻り値から `error` キーを pop |
| #55 | `cluster.py:623` (disable_worker_sleep) | `{exc}` を含む message を「SSH 接続またはコマンド実行に失敗しました」に置換、`logger.exception` へ |
| #57 | `cluster.py:741` (remote_ray_restart) | 同上 |
| #34 | `db_maintenance.py:40` (set_auto_vacuum) | 戻り dict から `error` / `exception` / `traceback` を pop |
| #9, #10 | `sync.py:224/261` (preview / import) | `summary.errors` を `_sanitize_errors()` で件数メッセージのみに変換、詳細はログへ |
| #12 | `sync.py:405` (cloud_import) | 同上 |
| #13 | `sync.py:429` (validate_only) | 検証失敗時の `error` を「パッケージ検証に失敗しました」に置換 |
| #20 | `tracknet.py:117` (tracknet_status) | `inf.get_load_error()` の生文字列を返さず「モデルの読み込みに失敗しました」を返却 |
| #46 | `tunnel.py:372` (tunnel_status) | `recent_log` に `_stderr_lines` 生値を返さず件数メッセージのみ。`cf_named.reason` の `{exc}` も削除 |
| #19 | `tunnel.py:448` (start ngrok) | `str(e)` を「ngrok が見つかりません」に置換、`logger.exception` へ |

### 検証
- `python -m pytest backend/tests` → 635 passed / 4 skipped
- `python -c "import backend.main; ..."` → OK

残: `paramiko-missing-host-key-validation` x4、`disabling-electron-websecurity` x2 は引き続き既知リスク許容。

---

## 追加対応: CI の失敗修正 + Scorecard TokenPermissions (同日, 後半)

advanced CodeQL workflow と GitHub default setup が競合していたため、advanced workflow を正式に動かす決定。これに伴い CI 失敗 2 件 + Scorecard 関連の high 8 件を対応。

### CI 失敗の修正
| Workflow | 原因 | 対応 |
|----------|------|------|
| CodeQL Advanced | default setup と競合 (`cannot be processed when the default setup is enabled`) | `gh api --method PATCH repos/.../code-scanning/default-setup -f state=not-configured` で default setup 無効化 |
| Microsoft Defender For Devops | SARIF upload 時に `Resource not accessible by integration` | `defender-for-devops.yml` の MSDO ジョブに `permissions: contents: read / security-events: write / actions: read` を追加 |

### Scorecard TokenPermissionsID (high x8)
advanced CodeQL が有効化されたことで Scorecard 由来の high alert が大量に可視化された。top-level permissions の欠落が主因。

| Workflow | 対応 |
|----------|------|
| `bandit.yml` | top-level に `permissions: contents: read` 追加（job レベル write は SARIF upload に必須のため維持） |
| `codeql.yml` | 同上 |
| `defender-for-devops.yml` | 同上 |
| `devskim.yml` | 同上 |
| `eslint.yml` | 同上 |
| `osv-scanner.yml` | top-level の `security-events: write` を job レベルへ移動、top-level は `contents: read` のみ |
| `osv-scanner-pr.yml` | 同上（`pull-requests: read` も job レベルへ） |

### 継続対応保留 (high)
| Alert | 理由 |
|-------|------|
| `VulnerabilitiesID` x1 | Scorecard 集計値。xmldom bump 等で漸次減少。時間解決 |
| `BranchProtectionID` x1 | リポジトリ設定 (main 保護ブランチ) の問題。GitHub UI で対応すべき |
| `CodeReviewID` x1 | 過去 30 コミットの approval 率。PR ベース運用で漸次改善 |
| `MaintainedID` x1 | リポジトリ作成から 90 日未満。時間解決 |
| `bandit.yml:30` job-level `security-events: write` | SARIF upload 必須のため除去不可。Scorecard は write permission があるだけで flag するため本質的に解消不能 |
| `paramiko` x4, `electron-websecurity` x2 | 既知リスク（前述） |

### 次回 CI 実行時の期待
- CodeQL Advanced: success
- MS Defender For Devops: success
- Scorecard: 継続 failure（high 残数は減少するが Branch/Code/Maintained で score 0 は不可避）

---

## Phase 1: High/Medium 残件の総ざらい (同日, 追加)

CI 全件 success 後、残 open alert を triage して Phase 1 相当を一括処理。

### CodeQL alert 25 件 dismiss
| 分類 | 件数 | dismissed_reason | 根拠 |
|------|------|------------------|------|
| `py/path-injection` | 12 | false positive | `Path.resolve()` + `relative_to()` による scope 検査、セグメント regex ホワイトリスト、拡張子ホワイトリストで sanitize 済み。CodeQL が sanitizer を認識していないだけ |
| `py/stack-trace-exposure` | 6 | false positive | `_sanitize_errors()` / 汎用メッセージ置換で対応済み。詳細は `logger.exception` でサーバログのみ |
| `py/url-redirection` | 1 | false positive | SPA catch-all で scheme/backslash/protocol-relative を拒否、charset 制限済み |
| `py/paramiko-missing-host-key-validation` | 4 | won't fix | loopback/private LAN 限定の SSH。動的 worker ノードで known_hosts 更新は非現実的 |
| `js/disabling-electron-websecurity` | 2 | won't fix | `localfile://` スキームによるローカル動画再生に必須。renderer はローカル信頼コンテンツのみ |

### Scorecard 対応
- `SECURITY.md` を repo root に追加 → `SecurityPolicyID` 解消見込み
- main ブランチ保護を最小構成で有効化:
  - `allow_force_pushes: false`
  - `allow_deletions: false`
  - 通常 push は従来通り可（単独開発ワークフロー維持のため PR 必須化 / status check はスキップ）
  - `BranchProtectionID` score 改善見込み（PR レビュー無しのため満点は不可）

### 次フェーズ（保留）
- Scorecard `CodeReviewID` / `MaintainedID` / `VulnerabilitiesID` — 時間解決（PR 運用蓄積 / repo age / Dependabot 再集計待ち）
- Scorecard `PinnedDependenciesID` x46 — Phase 2 で SHA pin
- osv-scanner CVE x11 — Phase 2 で Python 依存 bump
- Bandit warning (B310/B608/B601/B104) x25 — Phase 2 で個別精査
- Bandit note 系 大量 — Phase 3 で `.bandit` / `pyproject.toml` 抑制
