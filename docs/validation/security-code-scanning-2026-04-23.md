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
- Bandit warning (B310/B608/B601/B104) x25 — Phase 2c で個別精査
- Bandit note 系 大量 — Phase 3 で `.bandit` / `pyproject.toml` 抑制

---

## Phase 2a+2b: Scorecard SHA pin + osv-scanner CVE 修正 (同日)

### 2a: GitHub Actions を SHA pin（Scorecard `PinnedDependenciesID` x46 対応）
全 workflow の `uses: <repo>@<tag>` を `uses: <repo>@<SHA> # <tag>` に変換。Dependabot による自動更新を継続可能。

| Action | 固定 SHA |
|--------|---------|
| `actions/checkout` v6 | `de0fac2e4500dabe0009e67214ff5f5447ce83dd` |
| `actions/setup-node` v6 | `48b55a011bda9f5d6aeb4c2d9c7362e8dae4041e` |
| `actions/setup-python` v5 | `a26af69be951a213d495a4c3e4e4022e16d87065` |
| `actions/setup-dotnet` v4 | `67a3573c9a986a3f9c594539f4ab511d57bb3ce9` |
| `actions/upload-artifact` v7 | `043fb46d1a93c77aae656e7c1c64a875d1fc6a0a` |
| `github/codeql-action/*` v4 | `95e58e9a2cdfd71adc6e0353d5c52f41a045d225` |
| `microsoft/security-devops-action` v1.6.0 | `e94440350ed10e2806d47cd0d7504a2c51abdbe9` |
| `microsoft/DevSkim-Action` v1 | `4b5047945a44163b94642a1cecc0d93a3f428cc6` |
| `google/osv-scanner-action/*` v1.7.1 | `1f1242919d8a60496dd1874b24b62b2370ed4c78` |

対象 workflow: `bandit.yml`, `ci.yml`, `codeql.yml`, `defender-for-devops.yml`, `desktop-package-smoke.yml`, `devskim.yml`, `eslint.yml`, `osv-scanner.yml`, `osv-scanner-pr.yml`, `scorecard.yml`, `tracknet-smoke.yml` の計 11 ファイル。

### 2b: Python 依存バージョン bump（osv-scanner CVE x11 対応）
`shuttlescope/backend/requirements.txt` のフロア値を上げる。既にランタイム最新はインストール済みだが OSV-Scanner は宣言上の最小を基準に判定するため floor bump で解消。

| パッケージ | 変更 | 解消 CVE |
|-----------|------|---------|
| `scikit-learn` | `>=1.3.0` → `>=1.5.0` | CVE-2024-5206 |
| `yt-dlp` | `>=2024.3.10` → `>=2025.1.15` | CVE-2024-22423 / CVE-2024-38519 / CVE-2026-26331 / GHSA-3v33-3wmw-3785 |
| `pytest` | `>=8.0.0` → `>=8.4.0` | CVE-2025-71176 |
| `python-jose[cryptography]` | `>=3.3.0` → `>=3.4.0` | CVE-2024-33663 / CVE-2024-33664 |

---

## Phase 2c + Phase 3: Bandit / DevSkim 残 medium/low 全件処理 (同日)

Phase 2b 後も残っていた Bandit warning / note、DevSkim error / note を全件 triage して一括 dismiss + 設定ファイルで再発抑制。

### Phase 2c: Bandit warning (29) + DevSkim error (8) の per-alert dismiss
| Tool | Rule | 件数 | dismissed_reason | 根拠 |
|------|------|------|------------------|------|
| Bandit | B310 (urlopen) | 13 | false positive | maintenance script 内のハードコード URL、外部入力なし |
| Bandit | B608 (SQL string) | 7 | false positive | 動的テーブル名は schema introspection / PRAGMA 由来で外部入力なし |
| Bandit | B601 (paramiko shell) | 4 | won't fix | クラスタ IP は事前検証済み。既 dismiss の paramiko 方針を踏襲 |
| Bandit | B507 (ssh_no_host_key) | 4 | won't fix | 同上、既 dismiss の paramiko 方針と同じ |
| Bandit | B104 (0.0.0.0 bind) | 1 | false positive | `main.py:1219` `LAN_MODE` ゲート時のみ、intentional |
| Bandit | B324 (weak hash) | 1 | false positive | 非セキュリティ cache key / TOTP RFC 6238 |
| DevSkim | DS126858 (weak hash) | 3 | false positive | `auth.py` SHA1 は RFC 6238 TOTP 必須、`response_cache.py` は cache key |
| DevSkim | DS148264 (weak RNG) | 4 | used in tests | test data generator / seed script、暗号用途なし |
| DevSkim | DS187371 (weak cipher) | 1 | false positive | `electron/main.ts` 該当行は DRM permission-handler のコメント |

### Phase 3: Bandit note (1525) + DevSkim note (83) の bulk dismiss + 設定抑制
| Tool | Rule | 件数 | dismissed_reason | 根拠 |
|------|------|------|------------------|------|
| Bandit | B101 | 1243 | used in tests | tests / 試作スクリプトの assert |
| Bandit | B110 | 115 | won't fix | best-effort cleanup の try/except/pass |
| Bandit | B311 | 96 | used in tests | test data generator / seed の random、非暗号 |
| Bandit | B603 | 30 | won't fix | subprocess は固定 argv、`shell=True` 無し |
| Bandit | B404 | 17 | won't fix | subprocess import 監査済 |
| Bandit | B607 | 12 | won't fix | 部分 PATH 解決、operator-controlled env |
| Bandit | B105 | 9 | false positive | サンプル/テスト用文字列リテラル、真の認証情報ではない |
| Bandit | B112 | 3 | won't fix | best-effort ループの try/except/continue |
| DevSkim | DS162092 | 71 | won't fix | localhost dev 参照 / コメント内の HTTP URL |
| DevSkim | DS137138 | 9 | won't fix | ドキュメント/参照文字列、実行可能な credential ではない |
| DevSkim | DS176209 | 3 | won't fix | maintenance script 内の文字列リテラル |

### 再発抑制設定の追加
新規ファイルで以降のスキャンから note tier を抑制。
- `.bandit`（リポジトリルート）: `skips = B101,B110,B311,B603,B404,B607,B105,B112` / `exclude = tests,.venv,node_modules,out`
- `.devskim.json`（リポジトリルート）: DS162092 / DS137138 / DS176209 を `ignores`
- `.github/workflows/bandit.yml` の `shundor/python-bandit-scan` 起動時に `skips` / `excluded_paths` を渡すよう更新

### 残存 (既知/時間解決)
| Alert | 理由 |
|-------|------|
| Scorecard `CodeReviewID` / `MaintainedID` / `VulnerabilitiesID` / `FuzzingID` / `CIIBestPracticesID` / `SecurityPolicyID` | 時間解決 or 本 POC に適用困難（fuzzing・CII badge は単独開発では現実的でない） |
| `paramiko-missing-host-key-validation` x4, `electron-websecurity` x2 | 既知リスクとして許容（前述） |
| osv-scanner CVE x11 | Phase 2b で floor bump 済み。次回 push スキャン後に自動 close 想定 |

### 検証
- `cd shuttlescope && npm run build`（`NODE_OPTIONS=--max-old-space-size=16384` 必須）
- `.\backend\.venv\Scripts\python -m pytest backend/tests`
- push 後の GitHub Actions 全 success を確認

