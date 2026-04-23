# Changelog

This changelog records ShuttleScope's evolution from repository creation onward.
It is intentionally more detailed than a typical release changelog because the project is still moving quickly, and the history itself is useful context and motivation.

Read it together with:

- `README.md` for the current product scope and what is realistically usable now
- `shuttlescope/docs/validation/` for narrower validation notes and issue-by-issue verification

## How To Read This File

- Dates are grouped by development day.
- Entries are written at a product / workflow level, but they stay close to what was actually implemented.
- This is not a literal dump of `git log`, but it aims to preserve the meaningful shape of the work.

## 2026-04-23

### Phase B Authentication (B-1 〜 B-5) と Frontend 認証 UI

- Refresh token rotation + reuse 検知 + chain revoke (`POST /api/auth/refresh`, `/logout`)。access token は短命 (15分) 化し、refresh token は一度使用で revoke される rotation 方式。reuse 検出時は該当ユーザの全 refresh token を chain revoke。
- 15 分無操作による自動ログアウト (B-2) をフロント側に実装。
- Self-service のパスワード変更 (`POST /api/auth/password`) と admin による強制リセット (`POST /api/auth/admin/reset-password`)。リセット時は一時パスワード発行 + 既存 refresh token 全 revoke。
- 管理者向け audit log 一覧 API (`GET /api/auth/audit-logs`) と、フロント側の監査ログ閲覧ページ。
- 認証 UI (パスワード変更画面 / admin リセット / 監査ログページ) を追加。

### Router 単体テスト拡充 (Phase C2 / C3 / C4)

- `db_maintenance` / `settings` / `network_diag` ルーターに対する unit test を追加 (計 20+ ケース)。TestClient ベースで lifespan・依存注入を含む実環境に近いパスを検証。

### テスト安定化 (test pollution 根本対策)

- `backend/db/database.py::set_auto_vacuum_mode()` がインメモリ DB 上で `bind.dispose()` を呼んで StaticPool を破壊する問題を修正 (`:memory:` URL を no-op で早期 return)。これにより `test_db_maintenance` 以降の 103 errors / 30 failures が解消。
- `backend/config.settings` の singleton 差し替え (`cfg_mod.settings = cfg_mod.Settings()`) が `from backend.config import settings` を import 時にキャプチャしている router 群 (auth / network_diag 等) を古い instance に固定し、後続テストで BOOTSTRAP_ADMIN 関連の pollution を起こしていた問題を修正。`backend/benchmark/runner.py` と `backend/tests/test_benchmark_runner.py` を instance 置換から **in-place attribute 更新** に切り替え、`test_cv_factory` の `importlib.reload(backend.config)` も撤廃。
- `backend/routers/settings.py` の import 時 `engine` キャプチャと `create_settings_table()` 実行が `conftest.py::test_engine` fixture の engine patch より前に走っていた問題を修正。各リクエストで `_ensure_settings_table(db)` を冪等実行する方式に変更。
- `backend/routers/network_diag.py` を `_get_settings()` 経由の動的参照に書き換え、settings instance 差し替え時も LAN_MODE 切替が一貫するようにした。
- `backend/main.py` の lifespan を `bootstrap_database(None, app_settings.DATABASE_URL)` に変更し、`db_module.engine` を動的解決。
- 最終結果: `DATABASE_URL=sqlite:///:memory: pytest backend/tests/` が **670 passed, 4 skipped, 0 failed** (作業前: 30 failed + 103 errors)。CI (ubuntu-latest / windows-latest) 両方 green。

### OSV 依存脆弱性対応 (Scorecard #1773)

- `pytest>=8.4.0` → `>=9.0.3` (GHSA-6w46-j5rx-g56g)
- `yt-dlp>=2025.1.15` → `>=2026.02.21` (GHSA-g3gw-q23r-pgqm netrc command injection)
- `ray>=2.9` コメント pin → `>=2.54.0` に更新 (GHSA-w4rh-fgx7-q63m / q279-jhrf-cc6v / q5fh-2hc8-f6rq の 3 件を production install 時に回避)
- ray の未修正 CVE 2 件 (GHSA-gx77-xgc2-4888 token auth デフォルト無効 / GHSA-6wgj-66m2-xxp2 jobs API RCE) は `shuttlescope/backend/osv-scanner.toml` を新設して trusted network 運用前提で ignore 登録。運用要件 (dashboard / jobs API を外部公開しない等) は `docs/validation/fix-osv-dependency-vulnerabilities.md` に明文化。

### i18n 移行 (B1 / B2a / B3 / B4 / B5 相当)

- `AnnotatorPage`, `SettingsPage` (~35 箇所), `MatchListPage`, `UserManagementPage`, `CourtHeatModal`, `DoublesAnalysis` のハードコーディング日本語を `src/i18n/ja.json` のキーに移行。
- キー命名は `match.list.*`, `users.manage.*` など領域別に整理。

### Validation ドキュメント

- `shuttlescope/docs/validation/fix-set-auto-vacuum-memory-safe.md`
- `shuttlescope/docs/validation/fix-test-pollution-settings-singleton.md`
- `shuttlescope/docs/validation/fix-osv-dependency-vulnerabilities.md`

### Security Code Scanning Triage (Phase 1)

- Dismissed 25 CodeQL alerts with explicit rationale after verifying mitigations or accepting residual risk.
  - 19 false positives: `py/path-injection` x12 (sanitized via `Path.resolve()` + `relative_to()` scope check, segment whitelist regex, and extension whitelist), `py/stack-trace-exposure` x6 (sanitized via `_sanitize_errors()` and generic user-facing messages with `logger.exception` redirected to server logs), `py/url-redirection` x1 (SPA catch-all blocks scheme / backslash / protocol-relative URLs plus charset whitelist).
  - 6 won't-fix: `py/paramiko-missing-host-key-validation` x4 (cluster SSH is loopback / private LAN only and worker nodes rotate too aggressively for `known_hosts`), `js/disabling-electron-websecurity` x2 (the `localfile://` scheme for local video playback requires `webSecurity: false` inside the Electron shell).
- Added `SECURITY.md` at repository root so Scorecard `SecurityPolicyID` clears and external reporters have a documented reporting channel.
- Enabled minimum branch protection on `main` (force-push blocked, branch deletion blocked, no status-check gating) so solo-maintainer push from any device continues to work while Scorecard `BranchProtectionID` score improves.

### Scorecard Supply-Chain Hardening (Phase 2a)

- Pinned every third-party and first-party GitHub Action `uses:` reference to a commit SHA across all eleven workflows: `bandit.yml`, `ci.yml`, `codeql.yml`, `defender-for-devops.yml`, `desktop-package-smoke.yml`, `devskim.yml`, `eslint.yml`, `osv-scanner.yml`, `osv-scanner-pr.yml`, `scorecard.yml`, `tracknet-smoke.yml`.
  Version tags are preserved as trailing comments so Dependabot can continue to propose upgrades and humans can still read the intent at a glance.
  This resolves the 46 Scorecard `PinnedDependenciesID` alerts.

### Python Dependency CVE Bumps (Phase 2b)

- Raised declared floor versions in `shuttlescope/backend/requirements.txt` so OSV-Scanner (which reads the minimum pin) stops flagging already-patched CVEs:
  - `scikit-learn` `>=1.3.0` → `>=1.5.0` (CVE-2024-5206)
  - `yt-dlp` `>=2024.3.10` → `>=2025.1.15` (CVE-2024-22423 / CVE-2024-38519 / CVE-2026-26331 / GHSA-3v33-3wmw-3785)
  - `pytest` `>=8.0.0` → `>=8.4.0` (CVE-2025-71176)
  - `python-jose[cryptography]` `>=3.3.0` → `>=3.4.0` (CVE-2024-33663 / CVE-2024-33664)

### Bandit / DevSkim Total Triage (Phase 2c + Phase 3)

- Dismissed 37 Bandit warning / DevSkim error alerts per-alert with explicit rationale:
  - Bandit warnings (29): `B310` x13 (maintenance-script hardcoded URLs), `B608` x7 (SQL strings use introspected table names / PRAGMA, no external input), `B601` x4 (paramiko shell with pre-validated cluster IPs — same policy as already-dismissed paramiko findings), `B507` x4 (same paramiko policy), `B104` x1 (`0.0.0.0` bind gated by `LAN_MODE`), `B324` x1 (SHA1 used as non-security cache key).
  - DevSkim errors (8): `DS126858` x3 (SHA1 is RFC 6238 TOTP mandate in `auth.py`; SHA1 in `response_cache.py` is a cache key), `DS148264` x4 (random used in test data generators and seed scripts, not crypto), `DS187371` x1 (flagged line in `electron/main.ts` is a DRM permission-handler comment, not cipher code).
- Bulk-dismissed ~1608 Bandit note / DevSkim note alerts covering prototype noise tiers (`B101` assert, `B110` / `B112` try-pass/continue, `B311` test-data random, `B603` / `B404` / `B607` subprocess, `B105` sample strings, `DS162092` HTTP URL, `DS137138`, `DS176209`).
- Added scanner configuration to prevent the note tier from reappearing on new code:
  - `.bandit` at repo root with `skips = B101,B110,B311,B603,B404,B607,B105,B112` and `exclude` covering `tests`, `.venv`, `node_modules`, `out`.
  - `.devskim.json` at repo root with `ignores` for `DS162092` / `DS137138` / `DS176209`.
  - `.github/workflows/bandit.yml` updated to pass `skips` and `excluded_paths` to `shundor/python-bandit-scan` so the workflow matches local behavior.

### Validation

- Recorded the full triage and scope decisions in `shuttlescope/docs/validation/security-code-scanning-2026-04-23.md`, which tracks each dismissed rule with rationale and the remaining Scorecard / paramiko / electron-websecurity risks that stay intentionally accepted.

## 2026-04-22

### Code Scanning Response (Dependabot + CodeQL Critical / High)

- Bumped `@xmldom/xmldom` to `^0.8.13` to clear the three Dependabot advisories (CVE-2026-41672 / 41674 / 41675).
- Fixed critical command-line-injection and SSRF issues surfaced by CodeQL:
  - `backend/cluster/topology.py` now normalizes IP input through `ipaddress.ip_address()` before passing to `ping`, and coerces / range-checks ports before constructing URLs.
  - `backend/main.py` validates `primary_ip` and coerces `num_cpus` / `num_gpus` to `int` before invoking the Ray auto-start subprocess.
  - `backend/routers/cluster.py` validates `body.node_ip`, `body.port`, `body.num_cpus`, and `body.num_gpus` before any subprocess call.
- Fixed high-severity path-injection findings in asset, sync, and video-import routes:
  - `backend/main.py` `serve_assets` now decomposes the asset path, whitelists each segment against a conservative regex, resolves against the assets root, and verifies the final path stays inside `_assets_dir` before doing an extension whitelist check.
  - `backend/routers/sync.py` `cloud_import` resolves relative to the configured sync folder first, rejects paths outside the folder, and limits the extension to `.sspkg`.
  - `backend/routers/video_import.py` rejects URL-scheme paths and control characters, enforces an allowed-extension set both before and after `Path.resolve()` so symlink hops cannot bypass the check.
- Fixed the XSS-through-DOM finding in `src/components/video/WebViewPlayer.tsx` by parsing incoming URLs with `new URL()` and accepting only `http:` / `https:` before setting `wv.src`.
- Fixed the medium open-redirect finding in `backend/main.py` SPA catch-all by rejecting `://`, backslash, leading `/` or `\`, and restricting the remaining charset.

### Stack-Trace Exposure Total Cleanup

- While in a coding-focused environment, walked through all 14 `py/stack-trace-exposure` findings and redirected any `str(exc)` or traceback content to `logger.warning` / `logger.exception` on the server side while returning only generic, user-safe messages in responses.
  Touched routers: `analysis_research.py`, `cluster.py`, `db_maintenance.py`, `sync.py`, `tracknet.py`, `tunnel.py`.
- Backend smoke: `python -m pytest backend/tests` → `635 passed / 4 skipped`.

### CI Failure Recovery and Scorecard TokenPermissions

- Resolved the CodeQL Advanced / default-setup conflict by disabling GitHub's default Code Scanning setup (`gh api --method PATCH repos/.../code-scanning/default-setup -f state=not-configured`) so the advanced matrix workflow (`actions` + `javascript-typescript` + `python`) can run.
- Fixed Microsoft Defender For Devops SARIF upload failing with `Resource not accessible by integration` by adding explicit `security-events: write`, `contents: read`, and `actions: read` permissions to the `MSDO` job.
- Cleared eight Scorecard `TokenPermissionsID` high alerts by adding top-level `permissions: contents: read` to `bandit.yml`, `codeql.yml`, `defender-for-devops.yml`, `devskim.yml`, and `eslint.yml`, and by moving the write permissions from top-level to job-level in `osv-scanner.yml` and `osv-scanner-pr.yml`.

### Detailed Progress

- Bumped `@xmldom/xmldom` to `0.8.13+`.
- Added IP and port validation to cluster topology, cluster router, and Ray auto-start paths.
- Tightened static asset, sync import, and video import routes against path injection.
- Sanitized XSS-capable URL handling in the WebView player.
- Tightened SPA catch-all redirect handling against open-redirect patterns.
- Sanitized all 14 stack-trace-exposure responses across analysis, cluster, DB maintenance, sync, TrackNet, and tunnel routers.
- Switched from GitHub's default Code Scanning setup to the advanced matrix workflow.
- Added job-level SARIF permissions for the Microsoft Defender For Devops workflow.
- Declared minimal top-level workflow token permissions across security scanning workflows.

## 2026-04-21

### Public Landing Site v7

- Replaced the shuttle-scope.com top page with a full v7 design.
  New layout includes a fixed navigation bar with hamburger menu (mobile), a dark-navy hero section with an app mock panel, a three-column feature card row, a 2×2 analysis capabilities grid, a data policy section, a footer CTA, and a mobile sticky bottom bar.
- Added light / dark theme toggle via CSS custom properties persisted in localStorage.
- Added scroll-reveal animations using IntersectionObserver.
- Fixed all login / "アプリへ進む" link targets to `https://app.shuttle-scope.com/login`.
  Previously these pointed to the app root; they now go directly to the login screen.
- Preview route `/public-preview` continues to use link rewriting so internal development previews stay self-contained without affecting real login flow.

### Permission Scope Enforcement

- **User management** — role-scoped list, update, and create:
  - admin / analyst: full access to all users.
  - coach: can list and edit only users within their own team; cannot change roles.
  - player: can view and edit only their own account; restricted to `display_name` and password changes.
  - Frontend `UserManagementPage` now surfaces the appropriate UI controls per role instead of showing an "access denied" wall to non-admin roles.
- **Match result perspective** — practice match win / loss now reflects the viewing player's side:
  - `Match.result` is stored from player_a's perspective.
  - When the authenticated player is `player_b` or `partner_b`, `list_matches` now inverts `win` ↔ `loss` so each player sees their own outcome.
- **Data export / import auth (critical fix)** — `GET /api/export/package` and `POST /api/import/package` previously had no authentication checks.
  - Export now enforces the same `check_export_match_scope` scoping used by analysis endpoints (player / coach / analyst boundaries).
  - Import now requires analyst or admin role via `require_analyst`.

### Condition Analytics Role Restrictions Removed

- Removed the condition-analytics analyst-only gate that was blocking coach-role access to condition views.
  Coaches now receive the same condition analytics responses as analysts; player-facing restrictions remain in place.

### Admin Notification Inbox

- Added `NotificationInboxPage` so admin users can review inquiry submissions sent through the public contact form.
- Added backend coverage for the public-site test suite (`test_public_site`).

## 2026-04-20

### Admin Bootstrap Security

- Removed the fixed repository-visible bootstrap admin password and replaced it with environment-driven first-run admin provisioning.
- Added backend bootstrap-status reporting so the login screen can indicate whether initial admin creation is ready without exposing any secret value.
- Updated the login UI to prefill the bootstrap admin username and clearly warn when `BOOTSTRAP_ADMIN_PASSWORD` has not been configured yet.
- Added backend coverage for the bootstrap-status path and first admin creation on password login.

### Auth Flow Hardening and Session Cleanup

- Removed the lingering POC-era role switching path from the frontend so operators can no longer change analyst / coach / player context from Settings after login.
- Switched auth state persistence from long-lived local storage to session-scoped storage, making the app return to the login screen after the app or browser is fully closed.
- Added logout actions to the app shell and Settings so role changes now happen through explicit logout and re-login rather than client-side role mutation.
- Added a protected startup revalidation step through `/auth/me` so the frontend re-syncs its displayed role, user identity, and team context with the server-issued JWT before entering the main app.
- Extended auth responses to return `team_name`, which keeps coach-facing identity context aligned across login, startup restore, and account display.

### CI Stabilization and Benchmark Test Reliability

- Fixed CI installation failures by removing the assumption that `onnxruntime-gpu` is available in the base backend requirements on generic GitHub Actions runners.
- Reframed GPU ONNX Runtime as an environment-specific add-on, installed through machine setup scripts or targeted prep rather than forced into every CI or worker environment.
- Fixed benchmark test regressions so explicit mock mode is now respected during test execution instead of being silently disabled inside the runner.
- Aligned pipeline mock loading with the benchmark and smoke-test path, which removed false failures caused by real `ffmpeg` / runtime expectations in CI.

### Validation

- Verified the CI repair with a green GitHub Actions run on both `ubuntu-latest` and `windows-latest`.
- Re-ran local backend verification after the fixes:
  - backend tests: `624 passed, 4 skipped`
  - frontend tests: `84 passed`
  - production build: `npm run build` successful

### Detailed Progress

- Removed frontend `setRole`-based role mutation and the Settings role picker path.
- Moved token and auth-context persistence to session storage.
- Added explicit logout controls in the sidebar and account section.
- Added frontend auth revalidation using `/auth/me` before rendering protected routes.
- Returned `team_name` from backend auth login / me responses.
- Removed mandatory `onnxruntime-gpu` from generic backend dependency install flow.
- Updated benchmark runner behavior around tiny latency metrics and unavailable non-CPU devices.
- Preserved explicit `SS_CV_MOCK=1` behavior in benchmark execution.
- Updated video pipeline mock resolution so real mock implementations are used when available.

## 2026-04-19

### Cluster Routing and Remote Task Expansion

- Added Ray remote task support for distributed inference and analysis execution so GPU-heavy and CPU-heavy stages can now be routed more intentionally across machines.
- Expanded cluster bootstrap and topology handling so ShuttleScope can manage primary / worker behavior, remote task routing, and worker visibility with less manual editing.
- Strengthened the cluster settings surface so operators can inspect worker status, choose routing preferences, and tune load limits from the app rather than relying only on scripts.

### Benchmarking and Device Selection

- Expanded benchmark device detection across CPU, GPU, OpenVINO-capable paths, and Ray-aware environments.
- Added richer benchmark runner behavior including cancellation, backend overrides, YOLO as a benchmark target, and result handling better suited to mixed-device experiments.
- Raised the cluster inference concurrency limit and tuned benchmark / inference flow so experimentation on stronger local hardware is less artificially constrained.

### Worker Setup and Windows Operations

- Added `requirements_worker.txt` and `scripts/setup_k10_worker.ps1` so a second Windows machine can be prepared as a Ray worker with a narrower dependency surface than the full primary machine.
- Added and extended `scripts/fix_ray_firewall.ps1` to reduce the amount of manual Windows networking work needed to get distributed execution unstuck.
- Improved cluster worker setup details in `cluster.config.yaml`, backend bootstrap, and the Settings UI so practical worker onboarding is closer to a repeatable workflow.

### Model and Runtime Readiness

- Added a checked-in `backend/models/yolov8n.onnx` baseline asset so current YOLO-oriented flows have a default ONNX model available in-repo.
- Improved TrackNet inference fallback and backend selection behavior so OpenVINO / CPU / mock routes behave more predictably in mixed environments.

### Detailed Progress

- Added `backend/cluster/remote_tasks.py` and expanded cluster bootstrap / routing logic.
- Improved benchmark runner controls, target selection, backend override behavior, and cancellation support.
- Added YOLO benchmark target and corresponding frontend selector support.
- Added worker-specific requirements and a K10 worker setup script.
- Extended `ClusterSettingsPanel`, `SettingsPage`, and related i18n for cluster operations.
- Added `yolov8n.onnx` and refined TrackNet / benchmark integration behavior.

## 2026-04-18

### Role-Aware Local Authentication

- Added a proper local authentication surface instead of relying primarily on frontend role selection.
- Added backend auth routing for login, logout, current-user lookup, and role-specific login candidate lists.
- Added JWT utility handling and updated frontend auth state so the app now carries a signed backend-issued auth context rather than only local role headers.
- Added a dedicated `Login` page with role-specific flows for admin, analyst, coach, and player access.

### User and Access Management

- Added a `User Management` page so internal operators can manage role-bound local users instead of treating access as a purely implicit development concern.
- Extended the backend user model to support stronger role-linked account handling, including player-linked users and hashed credentials.
- Added access-log groundwork around auth actions so login and logout activity now has a backend audit trail.

### Protected Condition Views

- Tightened condition-data access so role-aware views expose different levels of detail instead of treating all readers as equivalent.
- Added field-sensitivity helpers and updated condition routing so coach / analyst access can be constrained to safer summaries while player self-view and privileged access remain distinct.
- Updated condition-related frontend screens and supporting hooks so the UI behaves correctly under the new protected-data responses rather than assuming unrestricted payloads.

### Prediction and Condition UX Alignment

- Updated prediction and condition pages, plus several analysis cards, so they degrade more safely when sensitive fields are unavailable under the current role.
- Refined frontend copy and i18n strings to match the new auth and protected-condition behavior.

### Validation

- Verified the auth and protected-condition update with:
  - backend tests: `624 passed, 4 skipped`
  - frontend tests: `84 passed`
  - production build: `npm run build` successful

### Detailed Progress

- Added backend auth router and JWT helpers.
- Added access-log and field-sensitivity utilities.
- Updated backend auth extraction and main app wiring.
- Tightened condition endpoint filtering.
- Added login and user-management pages.
- Updated frontend auth hook and API client to use backend-issued auth state.
- Refined prediction and condition views for role-aware payload differences.

## 2026-04-17

### Video Window Rendering Quality (Secondary Monitor)

- Fixed canvas overlay blur on high-DPI secondary monitors in the video extension window.
  `PlayerPositionOverlay` and `ShuttleTrackOverlay` were setting `canvas.width` / `canvas.height` to CSS logical pixels, causing the browser to upscale the canvas by `devicePixelRatio` and producing visibly blurred YOLO bounding boxes, shuttle trail dots, and label text.
  Both components now set canvas physical dimensions to `videoWidth ﾃ・dpr` / `videoHeight ﾃ・dpr`, apply `ctx.scale(dpr, dpr)` to keep drawing coordinates in logical pixels, and remove the `width` / `height` JSX attributes so sizing is managed entirely in the effect.
  On a 4K external monitor (`dpr = 2.0`), canvas resolution doubles from 1920 ﾃ・1080 to 3840 ﾃ・2160 physical pixels, utilizing the display's full native resolution while the main 1080p window remains unaffected.

### Multi-Monitor Selection UI

- Added monitor selection support for the secondary video window when three or more displays are connected.
  Previously `handleOpenVideoWindow` always picked the first non-primary display automatically, making it impossible to choose the target on a desktop with multiple external monitors.
  The fix adds a `selectedDisplayId` state (initialized from `getDisplays()` to the first non-primary monitor) and a `<select>` dropdown that appears only when two or more non-primary displays are detected.
  Single-monitor laptop setups (one external display) see no UI change; the dropdown only surfaces when a choice is meaningful.
  The `openVideoWindow` call now routes to the user-selected display ID, with a fallback to the first non-primary if the state is uninitialised.

### GPU Inference Backend 窶・Missing Pieces Completed (RTX 5060 Ti Preparation)

- Added `backend/cv/tracknet_openvino.py`: OpenVINO backend wrapper that adapts `tracknet/inference.py`'s `TrackNetInference` to the `TrackNetInferencer` Protocol.
  Implements chunked frame processing (300-frame chunks with a 2-frame overlap) so 30-minute match videos are not loaded entirely into RAM before inference starts.
  Frame indices are accumulated with a global offset to produce correct absolute timestamps across chunk boundaries.
- Extended `backend/cv/factory.py` with an OpenVINO intermediate tier.
  The new priority order is: Mock 竊・CUDA (torch + RTX) 竊・OpenVINO (iGPU / CPU, also works on K10) 竊・CPU (classical CV) 竊・Mock.
  Previously the OpenVINO inference path in `tracknet/inference.py` was entirely disconnected from the factory used by the pipeline.
- Added `backend/cv/tracknet_runner.py` and `backend/cv/mediapipe_runner.py`: thin runner modules that `cluster/tasks.py` was already referencing via `_safe_call` but which did not exist.
  Each module calls `factory.get_tracknet()` / `factory.get_pose()`, runs inference, and returns a status dict; the factory handles backend selection transparently so the same runner works on X1 AI (CUDA path) and K10 (CPU / OpenVINO path).
- Added `backend/pipeline/clips.py`: ffmpeg-based rally clip extractor.
  Detects `h264_nvenc` availability at first call and caches the result; uses NVENC when `SS_USE_GPU=1` and NVENC is present, falls back to `libx264` otherwise.
  K10 workers receive the CPU encode path automatically since `SS_USE_GPU=0` on that node.
- Added `backend/pipeline/statistics.py`, `backend/pipeline/cog.py`, and `backend/pipeline/shot_classifier.py`: lightweight K10-targeted entry points for statistics aggregation, centre-of-gravity calculation, and shot classification.
  Each delegates to the relevant `backend/cv/` implementation and returns `{"status": "skipped"}` gracefully when the underlying API is not yet implemented, preventing Ray task failures from aborting the full pipeline.
- Updated `backend/requirements.txt`: added `mediapipe>=0.10.14` and `pynvml>=11.4` as explicit entries so they are present in all environments rather than only after running the GPU setup script manually.
- Updated `scripts/setup_gpu.ps1` and `scripts/setup_gpu.sh`: both scripts now auto-download `pose_landmarker_lite.task` to `backend/cv/models/` after the pip installs, removing the manual download step that was previously required before `CudaPose` could initialise.
  The shell script uses `curl` with a `wget` fallback and prints a clear warning rather than failing hard if neither tool is available.

### Test Coverage Additions

- Added six test cases to `backend/tests/test_cv_factory.py` covering: `OpenVINOTrackNet` raising `ImportError` without openvino installed; the factory falling through to CPU / Mock when OpenVINO weights are absent; `tracknet_runner` / `mediapipe_runner` importability and callability; `pipeline/clips`, `statistics`, `cog`, `shot_classifier` importability; `extract_clips` returning `skipped` on `rally_bounds=None`; and `run_tracknet` not raising on a non-existent video path.
  All 11 active tests pass; 2 are correctly skipped when the relevant package (torch / openvino) is already installed.

### Detailed Progress

- Fixed Canvas DPI scaling in PlayerPositionOverlay and ShuttleTrackOverlay for high-DPI secondary monitors.
- Added multi-monitor selection dropdown to video extension UI (shown only with 2+ non-primary displays).
- Added tracknet_openvino.py with chunked frame processing and connected it to factory.py.
- Extended factory.py with CUDA 竊・OpenVINO 竊・CPU 竊・Mock priority chain.
- Added tracknet_runner.py and mediapipe_runner.py to complete the cluster/tasks.py call chain.
- Added pipeline/clips.py with automatic NVENC / libx264 selection.
- Added pipeline/statistics.py, cog.py, and shot_classifier.py as K10-targeted pipeline stubs.
- Updated requirements.txt with mediapipe and pynvml.
- Added MediaPipe model auto-download to setup_gpu.ps1 and setup_gpu.sh.
- Added six test cases to test_cv_factory.py covering new factory paths and module importability.

## 2026-04-16

### Analysis Bundles and Shared Data Flow
- Added analysis bundle foundations so review- and research-oriented screens can share a coordinated backend data layer instead of repeatedly pulling many small endpoints independently.
- Added response-cache groundwork, bundle parity verification scripts, and profiling scripts so performance work is now supported by explicit tooling rather than guesswork alone.
- Added shared review / research bundle contexts on the frontend so larger dashboard and review surfaces can be composed from a more stable data contract.
- Hardened Markov and research analytics persistence / interaction behavior while keeping the larger backend test suite green.

### Condition Tracking Platform
- Added a full condition tracking and analytics workflow, moving condition data from a side concept into a first-class product area.
- Added questionnaire handling, scoring, condition-specific analytics, and condition seeding utilities so the feature can be exercised on realistic internal data.
- Expanded the condition area with tagging, trend charts, volatility ranking, seasonality, PCA scatter, generic scatter, lag correlation, outlier week detection, tag comparison, post-match change views, and history detail flows.
- Added condition tag APIs and frontend tag-management views so condition analysis can now be organized and compared rather than treated as a flat list of entries.

### Expert Labeler and Secure Sync
- Added an expert labeler workflow with dedicated pages and backend routing so specialist labeling can sit alongside the main annotation workflow instead of living only in planning notes.
- Added clip-generation service groundwork to support the expert labeler flow.
- Strengthened package export / import and sync flows with more explicit auth-aware handling, moving cross-device package movement toward a safer internal workflow.

### Validation and Stability
- Continued the pattern of running build and full backend verification before large commits, keeping the codebase in a shippable internal state even while major features were landing.
- Preserved green backend coverage while introducing large new surfaces in conditions, expert labeling, bundles, and secure sync.
- Added benchmark-device and benchmark-runner test coverage so the new infrastructure-facing surfaces are not landing without backend guardrails.

### Device Benchmarking and DB Maintenance
- Added a benchmark execution foundation with device probing, synthetic benchmark targets, async job tracking, and a dedicated backend API for measuring available compute backends.
- Added a benchmark UI in Settings with device selection, target selection, progress polling, and result matrices so operator machines can be characterized inside ShuttleScope rather than only through ad hoc scripts.
- Added SQLite maintenance APIs and Settings controls for DB status, WAL / freelist visibility, incremental vacuum execution, and auto-vacuum mode changes.
- Moved the SQLite bootstrap path toward `auto_vacuum=INCREMENTAL` and added maintenance-aware database utilities, which addresses the real file-bloat pattern caused by repeated write/delete cycles.

### Analysis Reliability and Presentation
- Fixed condition growth insight payloads so growth-oriented cards now match the frontend contract more closely instead of relying on partially mismatched field names.
- Hardened bundled research-card rendering by guarding against non-array payload shapes in EPV and state-action views.
- Improved confidence-badge handling so missing or malformed sample counts degrade safely instead of producing misleading or broken UI states.
- Tightened cluster bootstrap test coverage so missing-Ray behavior and other bootstrap edge cases fail more explicitly during test runs.

### Fast Review and In-Game Coach Support
- Added RallyClipNavigator so analysts can jump directly to rally segments by video timestamp rather than scrubbing through raw footage.
  The navigator uses the `localfile://` protocol for desktop local video access and ties clip boundaries to annotated rally records, turning annotation data into a navigation layer over existing video.
- Added QuickSummaryCard with five rule-based coaching signals (momentum shift, serve pattern, unforced error rate, return pressure, fatigue indicator) targeted at between-set intervals.
  Cards are intentionally rule-based rather than model-driven so they surface reliably even when sample sizes are small enough to make statistical inference unreliable.
  Growth-oriented framing is preserved throughout 窶・no direct weakness labels appear in any card.

### Data Asset Packaging
- Added a JSON data package export / import workflow that bundles a match together with its linked players, sets, rallies, and strokes into a single portable file.
  The workflow is auth-aware and handles cross-device package movement through the existing secure sync infrastructure, making it practical to carry a finished match dataset from an annotation PC to an analysis machine without a shared DB.

### Multi-Camera Architecture (4-Camera Simultaneous)
- Extended the camera management model from a single-active constraint to a four-camera simultaneous limit.
  Removed the deactivate-all shortcut and replaced it with a handoff policy: when a fifth camera attempts to activate, the oldest active camera is handed off first, keeping at most four cameras live at any time.
  This matches real multi-court or multi-angle deployment scenarios without requiring operator coordination for every camera switch.
- Fixed a DeviceSelector text color regression where CPU usage text was rendering blue-on-blue (white text on white badge background), making CPU load invisible in the device panel.

### Distributed Tracking Foundation (Player Position Frames)
- Added the `PlayerPositionFrame` model (`player_position_frames` table) to the core schema.
  Stores per-frame positional data for all four court players (player_a, partner_a, player_b, partner_b) and the shuttle as float coordinates, keyed to match / set / rally and a frame counter.
  Indexed on (match_id, frame_num) for fast sequential playback reads and separately on rally_id for rally-scoped queries.
  This is the foundation for time-series player movement analysis, court pressure visualization, and future Ray-distributed tracking pipelines.
- Added Alembic migration `0007_player_position_frames` with an idempotent table-existence check, continuing the sequential migration chain at revision 0007.

### Cluster Infrastructure and Distributed Processing
- Designed and implemented a two-node cluster architecture targeting Minisforum X1 AI (primary) and GMKtec K10 (worker).
  Network topology: 2.5GbE direct Ethernet as the primary cluster link (192.168.100.0/24), USB-C RNDIS as a fallback link (192.168.101.0/24), WiFi for client access.
  USB-C is treated as fallback only 窶・the K10 does not have Thunderbolt, so USB networking tops out around 300窶・00 Mbps via RNDIS rather than full Thunderbolt speeds.
  Traffic budget analysis confirmed the 2.5GbE link is sufficient: ~50 Mbps for PostgreSQL WAL replication plus ~200 Mbps for four cameras at compressed JPEG frame rates leaves substantial headroom under the 2.5 Gbps physical limit.
- Added `cluster.config.yaml` as the user-facing cluster configuration file at the app root.
  Fields cover cluster mode (single / primary / worker), network interface assignment, Ray head address, PostgreSQL connection settings, camera inference limits, and per-node load thresholds.
  Designed to be understandable and editable by other users without code changes.
- Added `backend/cluster/topology.py`: cached YAML config loader with getters for mode, node identity, primary IP, workers list, Ray address, PG host, load limits, and inference config.
  Includes `list_interfaces()` (psutil-based network interface enumeration) and `ping_node()` (HTTP health check with latency measurement) so the UI can discover and verify cluster nodes.
- Added `backend/cluster/load_guard.py`: singleton `LoadGuard` with CPU (psutil), GPU (pynvml), and concurrent-task limits.
  Provides `can_accept()`, a `task_slot()` context manager for safe active-task counting, and `wait_until_available()` with configurable timeout.
  Limits are read from `cluster.config.yaml` so operators can tune thresholds without code changes.
- Added `backend/routers/cluster.py` with endpoints for cluster status, config read/write, interface listing, node ping, and live node status across all workers.
  Registered in `backend/main.py` under `/api`.
- Added `ClusterSettingsPanel` to the Settings UI: mode selector, node ID, network interface dropdowns (populated from `/api/cluster/interfaces`), worker list with per-worker ping test, load threshold sliders, live CPU/GPU gauge bars, Ray status badge, and a save button.
  Added the cluster tab to `SettingsPage` and wired all translation strings into `src/i18n/ja.json`.

### Windows Cluster Startup Scripts
- Added `scripts/cluster/start_primary.bat`: sequences PostgreSQL startup, Ray head node startup, a background health monitor, and the FastAPI server.
  Accepts `SS_CLUSTER_MODE`, `SS_RAY_PORT`, `SS_RAY_CPUS`, `SS_RAY_GPUS`, and `API_PORT` environment variables for flexible deployment.
- Added `scripts/cluster/start_worker.bat`: starts the PostgreSQL standby, connects the Ray worker to the head node at `SS_PRIMARY_IP`, and enters a 30-second reconnect loop to handle transient network interruptions during startup.
- Added `scripts/cluster/setup_routes.bat`: configures Windows routing tables for cluster and fallback subnets and sets interface metrics (cluster interface priority 10, fallback 100) so traffic naturally prefers the direct Ethernet link.
- Added `scripts/cluster/failover_promote.bat`: promotes the PostgreSQL standby to primary, starts a Ray head node on the worker machine, and updates `cluster.config.yaml` mode to `primary`, enabling the worker to operate as a fully autonomous primary if the original primary is lost.
- Added `scripts/cluster/pg_setup_primary.bat`: creates the `ss_user` database role, the `shuttlescope` database, and the `replicator` replication role, and configures PostgreSQL `wal_level`, `max_wal_senders`, `wal_keep_size`, and `listen_addresses` for streaming replication.
- Added `scripts/cluster/pg_setup_standby.bat`: runs `pg_basebackup` from the primary and starts the standby in hot-standby mode via `standby.signal`.

### SQLite 竊・PostgreSQL 18 Migration
- Migrated the operational database from SQLite to PostgreSQL 18.
  PostgreSQL 18 was installed via winget on the primary PC (`127.0.0.1:5432`, database `shuttlescope`, user `ss_user`).
  41,204 rows across 13 populated tables were migrated successfully (players 22, matches 62, sets 129, rallies 4,467, strokes 35,750, and supporting tables).
- Added `scripts/pg_migrate_sqlite.py` with dependency-ordered table migration, FK constraint bypass via `session_replication_role`, idempotent `ON CONFLICT DO NOTHING` inserts, post-migration sequence correction via `setval`, and Alembic head stamping.
  Key fix applied during migration: SQLite stores boolean columns as 0/1 integers, while PostgreSQL requires Python `True`/`False`.
  The script now pre-collects all boolean columns from the PostgreSQL schema via `pg_inspector` and converts values in each batch before insert, preventing the `DatatypeMismatch` error that would otherwise fail silently on partial rows.
- Updated `.env.development` to point `DATABASE_URL` at the PostgreSQL instance, with the previous SQLite URL commented out as a rollback reference.
- Updated `backend/requirements.txt` with organized sections covering core FastAPI / SQLAlchemy dependencies, PostgreSQL driver (`psycopg2-binary`), cluster utilities (`psutil`, `pyyaml`), and optional AI/reporting packages.

### CV Inference Architecture Foundation

- Added the CV inference factory (`backend/cv/factory.py`) as the single entry point for all CV backend selection.
  Priority chain: `SS_CV_MOCK=1` 竊・Mock, `SS_USE_GPU=1` 竊・CUDA, fallback 竊・CPU, final fallback 竊・Mock.
  All routers and pipeline code use only `get_tracknet()` / `get_pose()` so backend selection stays in one place.
- Added `CpuTrackNet` (`cv/tracknet_cpu.py`): classical CV shuttle detection using HSV color filter, MOG2 background subtraction, contour matching, and HoughCircles fallback.
  Missing frames are filled with linear interpolation so downstream consumers always receive a full-length sample list.
- Added `CudaTrackNet` (`cv/tracknet_cuda.py`): PyTorch / cv2.cuda structure ready for real TrackNet weights.
  Phase A delegates to `CpuTrackNet`; when actual `.pt` weights are placed and the TODO stub is completed, the GPU path activates automatically without touching the factory.
- Added `CudaPose` (`cv/pose_cuda.py`) and `CpuPose` (`cv/pose_cpu.py`): MediaPipe Pose inferencer pair.
  The CUDA variant uses MediaPipe Tasks GPU delegate; the CPU variant is the plain MediaPipe CPU path.
  Both satisfy the `PoseInferencer` Protocol so the factory can swap them without caller changes.
- Added `backend/tracknet/inference.py`: TrackNet inference wrapper with OpenVINO (GPU-preferred) 竊・ONNX Runtime CPU 竊・TensorFlow CPU priority chain.
  Loads real badminton-tuned TrackNet checkpoint weights and exposes `predict_frames(frames)` returning per-frame zone / coordinate / confidence dicts.
- Added `backend/yolo/inference.py`: YOLOv8 player detection wrapper with OpenVINO IR 竊・ultralytics PT 竊・custom ONNX CPU priority chain, per-frame court-side and depth-band assignment, and thread-safe locking for OpenVINO's stateful compiled model.
- Added Ray remote task structure (`backend/cluster/tasks.py`) with `_maybe_remote` decorator: GPU-intensive tasks (`run_tracknet`, `run_mediapipe`, `num_gpus=1`) target the X1 AI GPU node; CPU tasks (`extract_clips`, `run_statistics`, `calc_center_of_gravity`, `classify_shots`, `num_cpus=1`) target K10 worker nodes.
  Tasks degrade to synchronous execution when Ray is not initialized.
- Added `backend/cluster/pipeline.py`: orchestration layer that calls tasks in parallel stages (TrackNet + MediaPipe concurrently, then clips, then statistics / CoG / shots concurrently) using Ray when live or sequential fallback otherwise.
- Added `backend/pipeline/video_pipeline.py` and `backend/pipeline/jobs.py`: `run_pipeline()` and `execute_job()` coordinate full per-match analysis runs (TrackNet 竊・ShuttleTrack DB, Pose 竊・PoseFrame + CenterOfGravity DB, shot classification 竊・ShotInference DB), with `AnalysisJob` status tracking (running 竊・done / failed), error recording, and idempotent delete-before-insert.
- Added `backend/benchmark/devices.py`: compute device probe layer (`probe_all()`) covering CPU (psutil), NVIDIA GPU (pynvml), OpenVINO devices (iGPU / dGPU), ONNX Runtime CUDA EP, and Ray worker nodes.
  Results are cached for 60 seconds to avoid repeated probe overhead during dashboard polling.
- Added `scripts/setup_gpu.ps1` and `scripts/setup_gpu.sh`: GPU environment setup scripts that install PyTorch (CUDA 12.4 index), MediaPipe, and pynvml into the backend venv.

### Detailed Progress
- Refined research analytics interactions and Markov persistence.
- Added analysis bundles and response-cache foundation.
- Added condition tracking and analytics workflow.
- Expanded condition analysis and tagging workflows.
- Added expert labeler and secure package sync flow.
- Added CV inference factory, CpuTrackNet / CudaTrackNet, CpuPose / CudaPose, TrackNet inference wrapper, YOLO inference wrapper.
- Added Ray remote task definitions and cluster pipeline orchestrator.
- Added video pipeline, job tracking, and benchmark device probe layer.
- Added GPU setup scripts (Windows PowerShell and Linux shell).
- Added benchmark and DB maintenance workflows.
- Added RallyClipNavigator for timestamp-based video segment navigation.
- Added QuickSummaryCard with five rule-based between-set coaching signals.
- Added JSON match data package export and import workflow.
- Extended camera model to four simultaneous cameras with oldest-handoff policy.
- Fixed DeviceSelector CPU text color (blue-on-blue 竊・white).
- Added PlayerPositionFrame model and Alembic migration 0007.
- Designed two-node cluster topology (2.5GbE primary, USB-C fallback, WiFi clients).
- Added cluster.config.yaml, topology.py, load_guard.py, and cluster router.
- Added ClusterSettingsPanel to Settings UI with live gauges and config save.
- Added Windows cluster startup scripts (primary, worker, routes, failover, PG setup).
- Migrated 41,204 rows from SQLite to PostgreSQL 18 with boolean type fix.
- Updated .env.development and requirements.txt for PostgreSQL.

## 2026-04-15

### CV, Tracking, and Desktop Workflow
- Added realtime YOLO overlay groundwork so CV output can start surfacing during active desktop workflows rather than only after offline batch runs.
- Added ReID groundwork for player tracking, which begins to separate simple detection from actual player identity continuity.
- Improved player tracking overlays, movement-oriented analysis, CV result messaging, and fallback behavior around YOLO-driven flows.
- Added ROI-aware and desktop-oriented polish around capture / annotation workflows so CV work is more usable on real operator desktops.

### Auth and Settings
- Added local auth hardening and role-aware settings flow so local security and role behavior are less implicit.
- Added a role picker and auth-aware controls that connect settings behavior more clearly to the operator's current role.
- Refined auth-aware analysis panels and match/settings behavior so role differences start affecting more of the product in a visible way.

### Product Shape
- At this point ShuttleScope moved further toward a product with a real operator workflow: desktop capture, ROI setup, CV overlays, role-aware settings, and player-tracking foundations now connect more visibly.

### Detailed Progress
- Refined match linking and CV result messaging.
- Improved player tracking overlays and YOLO fallback flow.
- Added player movement analytics and ROI desktop polish.
- Hardened local auth and CV desktop workflows.
- Improved desktop capture overlays and YOLO controls.
- Polished CV job controls and YOLO annotator flow.
- Added ReID foundation for player tracking.
- Added role picker and auth-aware settings flow.
- Refined auth-aware analysis panels and match settings flow.

## 2026-04-14

### Prediction and Tactical Surfaces
- Improved prediction output so it reads more like an analyst-facing narrative and less like a raw probability panel.
- Added role-specific panels around prediction and pair-oriented analysis so the prediction area is easier to use for coach / analyst workflows.
- Expanded partner and lineup-related views to make pre-match and planning work more readable.

### CV Throughput and Analysis UX
- Extended CV analysis-rate options up to 60fps and added warnings around batch-processing cost so high-fidelity processing is possible without hiding the runtime tradeoff.
- Improved benchmark controls, resume behavior, ROI diff handling, and multiple dashboard / chart interaction details.
- Polished composite heatmaps, rally-detail modals, doubles display, and chart bugs that made detailed review surfaces harder to trust.

### Annotation and Match UX
- Improved inline confirmations, player-row consistency, silent-save handling, and match / player editing reliability.
- Continued reducing small-but-costly operator friction around lists, selectors, and save flows.

### Detailed Progress
- Fix chart bugs and add rally detail to score progression.
- Add CV analysis rate settings with benchmark UI, fix YOLO/TrackNet resume bug, add keyboard server select, and extend doubles support for warm-up notes and match list.
- Fix benchmark button text color for readability.
- Extend CV rate options to 60fps with batch processing time warning dialog.
- Improve composite heatmap interactivity, rally detail modal UX, and doubles annotation display.
- Polish UI with tooltips, sort, bulk select, and inline confirmations.
- Fix silent player update failure and apply `exclude_unset` to PUT handlers.
- Unify player row height and convert mobile delete behavior to inline confirmation.

## 2026-04-13

### Prematch, Resume, and ROI
- Added prematch prediction snapshots so prediction outputs can be stored in a more time-aware way instead of always behaving like a live recomputation.
- Added ROI-aware CV batch processing so selected regions actually flow through TrackNet / YOLO processing rather than staying as UI-only overlays.
- Added CV resume and ROI-diff workflows so interrupted or changed CV analysis runs can be resumed more intentionally.
- Improved court-grid / ROI editing and restoration behavior around annotator video workflows.

### Desktop Capture and Annotation Support
- Added ROI rectangle overlays and desktop-capture support that better match real operator use on Windows.
- Strengthened video-pane and annotator integration so video-region capture and CV analysis can sit inside the normal annotation flow more naturally.

### Test and CI Guardrails
- Fixed CI failures around websocket signaling by ensuring the test harness consistently creates the newer session-related tables and uses the patched test session factory.
- Added dedicated guardrail tests so similar signaling / SessionLocal regressions are more likely to fail fast in CI.

### Detailed Progress
- Add prematch snapshots and CV resume ROI workflows.
- Add player tracking overlay controls.
- Improve match edit validation feedback and static MIME mapping.
- Add ROI-aware CV batch processing.
- Improve prediction narrative and role-specific panels.
- Stabilize websocket signaling tests in CI.
- Add CI guardrails for websocket test harness.

## 2026-04-12

### Product and UX
- Expanded the top-level product documentation so the repository now explains ShuttleScope in a more grounded, current-state way.
- Added a proper root `CHANGELOG.md` so progress is visible from the repository top level.
- Polished dashboard selectors and theme controls, including better mobile-safe selectors, same-page navigation, and overview / advanced page usability.
- Improved responsive behavior across dashboard surfaces and heatmap-related views.

### Annotation and Match Workflow
- Improved match edit validation feedback and safer save behavior.
- Fixed server-state handling during rally confirmation so saved annotation state is less likely to drift from UI state.
- Improved LAN same-device access flow so sharing links behave more reliably when the same machine is both operator and consumer.

### Heatmaps and Responsive UI
- Added heatmap composite support and corresponding backend / frontend integration.
- Tightened responsive UI behavior across overview, advanced, settings, top navigation, section navigation, and several analysis cards.
- Added dedicated backend heatmap composite tests and updated UI behaviors so complex analysis views survive narrower layouts better.

### Security and Hardening
- Responded to a dedicated security review pass with concrete backend hardening.
- Restricted `localfile://` handling more aggressively.
- Added upload / body-size limits and safer request handling around file-oriented endpoints.
- Hardened sync import / copy paths against oversized input and path traversal.
- Added active-session and participant validation in camera WebSocket signaling.
- Added operator-token protection for sensitive remote session management flows.
- Switched session code generation from non-cryptographic random generation to a CSPRNG-based approach.

### Validation and Test Health
- Updated websocket signaling tests so they reflect the newer active-session requirements instead of silently depending on older assumptions.
- Kept the full test suite green while expanding responsive / security coverage.

### Detailed Progress
- Improved match edit validation feedback and static MIME mapping.
- Improved LAN same-device access and documented current product status more honestly.
- Improved responsive UI and heatmap composite views.
- Hardened remote session security and fixed annotation server state handling.
- Polished dashboard selectors and theme controls.

## 2026-04-11

### Post-Match Video and CV Pipeline
- Added a post-match local video import flow that moves ShuttleScope closer to a realistic "analyze after recording" workflow.
- Added `Video Only` / second-screen foundation so playback can continue while annotation happens elsewhere.
- Added court calibration foundation and then hardened it so backend persistence and restore behavior are more reliable.
- Improved CV ROI mapping and court-aware handling so downstream CV artifacts can use court geometry more safely.
- Added automation and validation scaffolding around court calibration and CV artifacts.

### Match and Player Management
- Added match editing after creation, including safer handling of referenced players.
- Prevented player deletion when matches still reference that player.
- Hardened match edit payload handling so empty optional values stop causing avoidable failures.
- Added player team history support and migration so roster changes can be tracked more realistically over time.

### Validation and Non-Human Checks
- Added more non-human validation coverage around calibration, artifacts, bootstrap behavior, and match edit safety.
- Tightened bootstrap and migration tests so DB evolution remains safer as the schema grows.

### Detailed Progress
- Added post-match video import and multi-monitor foundation.
- Refined court calibration persistence and CV ROI mapping.
- Closed calibration automation gaps and CV artifact hardening.
- Added match editing and referenced-player safeguards.
- Hardened match edit payload handling and save errors.
- Added player team history support and migration.
- Ignored local CV weights and kernel diagnostics so repository status stays clean.

## 2026-04-10

### YOLO / TrackNet / CV-Assisted Annotation
- Added YOLO player detection and CV alignment foundation.
- Added shuttle overlay and a dashboard CV position card so computer vision results start to surface in both annotation and dashboard flows.
- Polished YOLO-driven role signals and annotator-side CV controls.
- Improved YOLO diagnostics and artifact-status visibility so missing setup / problems are easier to diagnose.
- Added CV-assisted annotation candidates, candidate badges, and review queue groundwork.
- Started moving from "CV exists" to "CV suggests actual annotation actions" by introducing candidate application flows and review handling.

### Remote and CV Failure Handling
- Recorded and responded to critical remote / CV failures as validation findings rather than hiding them behind optimistic assumptions.
- Fixed remote share rebasing problems and made CV errors much more visible.
- Improved tunnel / ngrok hardening so remote sharing state is more explicit.

### Bootstrap and No-Video Work
- Used the no-video window productively by strengthening CV assist UX, review queue flow, and environment / bootstrap tooling.
- Added and improved bootstrap helpers and setup doctor output so the project is easier to bring up on additional devices without guesswork.

### Detailed Progress
- Added YOLO player detection and CV alignment foundation.
- Added shuttle overlay and dashboard CV position card.
- Polished YOLO role signal and annotator CV controls.
- Improved YOLO diagnostics and artifact status UX.
- Added foundation registry split and recorded critical remote CV failures.
- Fixed remote share rebasing and CV error diagnostics.
- Added CV-assisted annotation candidates and ngrok URL hardening.
- Polished no-video CV assist flow and device bootstrap.
- Improved device bootstrap guidance and doctor output.

## 2026-04-09

### Dashboard Rearchitecture
- Rebuilt the dashboard from a single large page into a structured shell with separate overview, live, review, growth, advanced, and research areas.
- Added top-level and section-level navigation patterns that make the dashboard feel more like a product surface than a page of stacked charts.
- Added evidence and research status presentation patterns so more experimental modules are visibly different from mature ones.

### Research Spine and Advanced Analysis
- Added the dashboard research spine and metadata / evidence groundwork.
- Added research cards and meta integration so state-value, counterfactual, hazard / fatigue, and related work has a stable home.
- Added promotion workflow and advanced-meta rollout so research outputs can be tracked as candidates for broader adoption.
- Completed promotion gaps and extended the color / theming system across more dashboard surfaces.
- Added audit log and theme fixes around promotion overrides.
- Hardened opponent policy refresh and error-state handling.

### Dashboard and Analysis UX
- Added date slider v2 and zone-map modal workflows.
- Fixed heatmap filtering and crash-handling issues.
- Applied theme / card rules consistently across advanced and research surfaces.

### Remote Camera and Live Collaboration
- Added remote tunnel providers and initial WebRTC / TURN settings support.
- Hardened remote diagnostics and stale camera cleanup behavior.
- Added TURN diagnostics and reconnect hardening.
- Added a remote viewer page and improved sender reconnect behavior.
- Polished remote handoff flow and grouped viewer UX.
- Added tunnel-provider visibility to the annotator remote health banner.

### Documentation and Positioning
- Rewrote the README around the practical PoC / current product scope rather than over-claiming future work.

### Detailed Progress
- Improved LAN access troubleshooting and sharing UX.
- Polished camera sender UX and live overlay behavior.
- Clarified README for current PoC scope.
- Fixed dashboard heatmap filters and crash handling.
- Rebuilt dashboard structure and routing.
- Added research spine and evidence metadata.
- Completed research cards and metadata integration.
- Added promotion workflow and advanced-meta rollout.
- Applied card theme rules to dashboard research and advanced views.
- Completed promotion gaps and color rollout.
- Added promotion audit log and live theme fixes.
- Hardened opponent policy card refresh and error states.
- Added date slider v2 and zone-map modal workflows.
- Added remote tunnel providers and WebRTC TURN settings.
- Hardened remote device diagnostics and stale camera cleanup.
- Added TURN diagnostics and receiver reconnect hardening.
- Added remote viewer page and sender visibility reconnect.
- Polished remote handoff flow and grouped viewer UX.
- Showed tunnel provider in annotator remote health banner.
- Added ngrok authtoken support and ignored local env files.

## 2026-04-08

### Analysis Architecture and Search UX
- Unified analysis foundations and player context so the later advanced / research stack had a cleaner base.
- Split analysis routers into stable, advanced, and research layers.
- Added stage 2 engines, then stage 3 research engines for counterfactual and EPV-oriented work.
- Added searchable selects and date-range filtering across important UI paths.

### Sync, DB, and Migration Foundation
- Added sync architecture phase 1 data-management support.
- Strengthened sync metadata and data-management flows after the first pass.
- Closed major DB sync gaps and added analytics indexes.
- Added Alembic migrations and the dominant-hand schema fix.
- Hardened DB bootstrap behavior and several DB-adjacent edge cases.

### Annotation and Review Acceleration
- Added annotation modes and a review-acceleration flow.
- Improved mobile UX and quick-start route behavior.

### LAN, Session, and Live Source Work
- Added LAN session auth and device-control flow.
- Added live source control and the first LAN inference foundation.
- Expanded single-PC validation coverage for the LAN live stack.
- Fixed LAN join flow and multiple device-manager UX issues.

### Detailed Progress
- Unified analysis foundations and player context.
- Split analysis routers and added stage 2 engines.
- Added stage 3 research engines for counterfactual and EPV.
- Polished mobile UX and fixed quick-start route issues.
- Added searchable selects and date-range filters.
- Added sync architecture phase 1 data management.
- Strengthened sync metadata and data management flows.
- Closed remaining DB sync gaps and added analytics indexes.
- Added Alembic migrations and dominant-hand schema fix.
- Hardened DB bootstrap and heatmap error handling.
- Added annotation modes and review acceleration flow.
- Added LAN session auth and device control flow.
- Added live source control and LAN inference foundation.
- Added single-PC validation coverage for the LAN live stack.
- Fixed LAN join flow and device-manager UX issues.

## 2026-04-07

### Annotation Workflow
- Refined the annotation keymap and rally-end flow so basic annotation became faster and less error-prone.
- Added a dedicated doubles hitter flow.
- Improved end-state handling and match-setup ergonomics.

### Analytics and Research
- Implemented research roadmap analytics modules.
- Added warm-up observations and related analytics context.
- Closed major remaining gaps with tests, seed data, and CI.
- Added heatmap modal and warm-up analytics fixes.

### Prediction
- Added the first prediction tab and pair-simulation foundation.
- Refined the prediction tab toward coach / analyst workflows.
- Added analyst-depth and human-benchmark oriented prediction features.

### Sharing and Access
- Added LAN and tunnel web-access support.

### Documentation
- Refreshed the README multiple times to keep it closer to reality as scope expanded.

### Detailed Progress
- Refined annotation keymap and rally-end flow.
- Refreshed the top-level README.
- Polished annotation flow end-state handling.
- Implemented research roadmap analytics modules.
- Added warm-up observations and detail analytics context.
- Closed remaining gaps with tests, seed data, and CI.
- Added heatmap modal and warm-up analytics fixes.
- Added prediction tab and pair-simulation foundation.
- Refined prediction tab for coach and analyst workflows.
- Added doubles annotation hitter flow.
- Added LAN and tunnel web-access support.
- Refreshed README for current product scope.
- Clarified README for PoC scope.
- Upgraded prediction with analyst depth and human benchmarks.

## 2026-04-06

### Streaming and Video Handling
- Added DRM-capable streaming playback and download tests.
- Improved ffmpeg fallback behavior and cookie-download guidance.
- Added a streaming download workflow and hardened the related UI.

### Annotation and Match-Day Flow
- Adapted the shot panel to rally context.
- Refined shot-key pause behavior.
- Added a match-day workflow and set-summary behavior.
- Improved desktop startup and quick-start flows.
- Improved annotation flow and interval handling.
- Completed a broad annotation / desktop workflow phase.
- Added TrackNet automation and settings sync.
- Implemented stage 1 sharing and live collaboration.

### Analytics
- Polished dashboard analytics access and labels.
- Implemented advanced analytics and reports.
- Enhanced EPV bootstrap and scouting reports.
- Refined analytics visuals and doubles dashboard.
- Added filter-aware analytics and related support.

### UX and Visual System
- Unified color-system rules and refreshed docs.
- Implemented the light-theme color spec.
- Polished analytics light theme and midgame review.

### Detailed Progress
- Added DRM-capable streaming playback and download tests.
- Improved ffmpeg fallback and cookie download guidance.
- Adapted shot panel to rally context.
- Refined shot key pause behavior.
- Polished dashboard analytics access and labels.
- Implemented advanced analytics and reports.
- Enhanced EPV bootstrap and scouting reports.
- Refined analytics visuals and doubles dashboard.
- Aligned private docs and validation layout.
- Unified color system and refreshed docs.
- Added filter-aware analytics and license documents.
- Polished light theme readability and match round labels.
- Implemented match day workflow and set summary.
- Improved desktop startup flow.
- Added quick start workflow and hardened desktop launch.
- Improved annotation flow and interval handling.
- Completed P1 / P2 / P4 annotation and desktop workflow.
- Added TrackNet automation and settings sync.
- Implemented stage 1 sharing and live collaboration.
- Implemented color spec v1 light theme rules.
- Polished analytics light theme and midgame review.
- Implemented analytics review phases 1 to 3.
- Improved annotator court flow and doubles sharing.
- Refined match setup and documented annotation flow.

## 2026-04-05

### Repository Setup
- Created the repository and initial ShuttleScope codebase.
- Added the repository-level Claude guidance file.
- Ignored local player / match database artifacts so local work would not pollute version control.

### First Substantial Feature Foundation
- Added an advanced analysis dashboard and support scripts very early in the repository lifetime, which set the tone for ShuttleScope as more than a minimal tagger.

### Detailed Progress
- Initial commit.
- Ignored local player and match databases.
- Added repository Claude guide.
- Added advanced analysis dashboard and support scripts.

## Notes

- This changelog is intentionally detailed because the project has been evolving quickly and the accumulated work matters.
- It is still higher-level than raw commit history; validation docs remain the best place for issue-specific detail.
- Local-only planning notes remain in `private_docs/` and are not committed.
