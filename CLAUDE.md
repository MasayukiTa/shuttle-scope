# ShuttleScope Claude Guide

## Purpose
- ShuttleScope is a desktop badminton video annotation and analysis application.
- The tracked app code lives under `shuttlescope/`.
- The git repository root also contains local confidential planning documents under `private_docs/`; they must not be committed.
- This file exists to preserve the most important product and implementation rules even when the confidential source documents are unavailable.

## Working Directory Map
- Repo root: git root, confidentiality rules, top-level agent guidance, legal/policy docs (`README.md`, `CHANGELOG.md`, `LICENSE`, `PRIVACY.md`, `TERMS_OF_SERVICE.md`, `SECURITY.md`, `DATA_CONTRIBUTION_TERMS.md`), security tool configs (`.bandit`, `.devskim.json`), `.github/` workflows.
- `shuttlescope/`: actual app root.
- `shuttlescope/electron/`: Electron main/preload process (`main.ts`, `preload.ts`).
- `shuttlescope/src/`: React + TypeScript renderer.
  - `src/api/`: HTTP API clients (`client.ts`, `benchmark.ts`, `db.ts`, `review.ts`).
  - `src/components/`: feature-grouped UI (`common/`, `annotation/`, `annotator/`, `analysis/`, `auth/`, `benchmark/`, `cluster/`, `condition/`, `court/`, `dashboard/`, `session/`, `video/`).
  - `src/pages/`: top-level routed pages (annotator, login, dashboard, settings, expert labeler, prediction, condition, etc.).
  - `src/hooks/`: shared React hooks (auth, annotation, video, conditions, live inference, realtime YOLO, theme, mobile detection, etc.).
  - `src/i18n/`, `src/store/`, `src/contexts/`, `src/styles/`, `src/types/`, `src/utils/`.
- `shuttlescope/backend/`: FastAPI app, SQLAlchemy models, routers, analysis, CV, cluster, and worker code.
  - `backend/routers/`: FastAPI endpoint modules grouped by domain (~39 files; see Backend Guidance).
  - `backend/analysis/`: tiered analysis engine (registry, Bayesian/Markov models, EPV, condition analytics, promotion rules).
  - `backend/cv/`, `backend/yolo/`, `backend/tracknet/`: computer vision base classes, YOLO/TrackNet inference and court/zone mapping.
  - `backend/pipeline/`: standalone job worker (`worker.py`), video pipeline, shot classification, clip generation.
  - `backend/services/`: business logic (clip generator, gpu health, import/export, merge resolver, backup).
  - `backend/cluster/`: Ray cluster bootstrap, topology, task distribution, remote queues.
  - `backend/ws/`: WebSocket implementations (live score broadcast, camera stream).
  - `backend/db/`: SQLAlchemy models (`models.py`), `database.py` session, Alembic migrations.
  - `backend/utils/`: cross-cutting helpers (auth, JWT, validators, confidence scoring, response caching).
  - `backend/models/`: pre-trained ML model files (ONNX/Torch).
  - `backend/public/`: public-API response schemas.
  - `backend/tests/`: pytest suite (~50+ test files).
  - `backend/benchmark/`, `backend/tools/`, `backend/data/`.
- `shuttlescope/scripts/`: local helper scripts and dataset/seed utilities.
  - `scripts/cluster/`: cluster failover and PostgreSQL primary/standby helpers.
  - `scripts/pm2/`: PM2 process manager ecosystem config.
- `shuttlescope/infra/`: Cloudflare tunnel daemon, SSH, Windows-specific infra setup.
- `shuttlescope/cluster.config.yaml`: Ray cluster configuration.
- `shuttlescope/docs/`, `shuttlescope/.env.development`: docs and local env defaults.

## Confidentiality Rules
- Never commit or upload the confidential files under `private_docs/`, including:
  - `private_docs/ShuttleScope_SPEC.md`
  - `private_docs/ShuttleScope_TASKS.md`
  - `private_docs/ShuttleScope_PRD_v1.0.docx`
- Treat those files as local-only reference material.
- Do not quote or copy confidential business content into public issues, commit messages, or generated docs unless the user explicitly asks for a sanitized version.
- Do not commit local databases, downloaded videos, build output, virtual environments, caches, or machine-specific files.

## Product Mission
- Help analysts annotate badminton matches quickly.
- Turn annotations into coach-facing and player-facing analysis.
- Support a local single-analyst POC now, with a migration path to team/server deployment later.

## Non-Negotiable Product Rules
- Never show players direct "weakness" framing.
- Replace any weak/negative coaching language with growth-oriented language such as `伸びしろ`.
- Never show player-facing screens raw absolute win-rate style judgments unless the product explicitly changes that rule.
- Never show player-facing screens direct EPV or direct weakness summaries.
- Every analysis view must communicate confidence or uncertainty.
- Statistical uncertainty, sample-size limitations, and warnings must not be omitted.
- If there is not enough data, the UI should say so clearly instead of pretending certainty.

## Current Architecture
- Desktop shell: Electron (vite-bundled via `electron-vite`).
- Renderer: React + TypeScript with Tailwind.
- Backend: FastAPI (Python) running locally as a child process.
- Background worker: a standalone Python process (`backend/pipeline/worker.py`) consumes the analysis job queue independently of the API process; it coordinates with API to avoid GPU contention and handles graceful shutdown.
- Real-time channels: WebSocket endpoints under `backend/ws/` — `live.py` for multi-client live-score broadcast (S-001) and `camera.py` for camera streaming (S-002).
- Local DB: SQLite. Planned future DB: PostgreSQL (cluster scripts already model primary/standby with failover).
- Migrations: SQLAlchemy + Alembic in `backend/db/migrations/`.
- Frontend communicates with the backend over HTTP on `localhost:8765`.
- Do not introduce Electron IPC for application API calls unless there is a strong reason; the current design intentionally uses HTTP to make later server migration easier.
- Electron main process launches Python as a child process.
- Local video selection uses the custom `localfile://` protocol registered in `shuttlescope/electron/main.ts`.
- Optional distributed mode: Ray-based cluster (`backend/cluster/`, `cluster.config.yaml`, `scripts/cluster/`, `scripts/pm2/`) for multi-machine job execution; PM2 manages long-running processes; Cloudflare tunnel (`infra/cloudflared/`) is used for remote access in non-local deployments.

## Source Of Truth Files
- Backend schema: `shuttlescope/backend/db/models.py`
- Backend startup and router registration: `shuttlescope/backend/main.py`
- Backend config defaults: `shuttlescope/backend/config.py`
- Standalone analysis worker: `shuttlescope/backend/pipeline/worker.py`
- Live-score WebSocket: `shuttlescope/backend/ws/live.py`
- Camera-stream WebSocket: `shuttlescope/backend/ws/camera.py`
- Analysis tier registry: `shuttlescope/backend/analysis/analysis_registry.py` (referenced by `routers/analysis_stable.py`, `analysis_advanced.py`, `analysis_research.py`)
- Ray cluster config: `shuttlescope/cluster.config.yaml`
- PM2 ecosystem: `shuttlescope/scripts/pm2/ecosystem.config.js`
- Electron app startup and backend orchestration: `shuttlescope/electron/main.ts`
- HTTP client conventions: `shuttlescope/src/api/client.ts`
- Role gating: `shuttlescope/src/components/common/RoleGuard.tsx`
- Confidence display: `shuttlescope/src/components/common/ConfidenceBadge.tsx`
- Japanese UI copy: `shuttlescope/src/i18n/ja.json`
- Role state for POC: `shuttlescope/src/hooks/useAuth.ts`

## Implementation Rules
- Keep comments in Japanese where comments are needed.
- Do not hardcode Japanese UI strings in components. Add them to `shuttlescope/src/i18n/ja.json` and reference them through i18n.
- Use existing common components and hooks before inventing new patterns.
- Preserve the HTTP API pattern in `src/api/client.ts` for frontend-backend communication.
- Preserve role-based restrictions with `RoleGuard`.
- Preserve or extend confidence/uncertainty UI with `ConfidenceBadge` and warning components.
- Do not remove error handling to make code shorter.
- Prefer incremental, reversible changes over broad rewrites.

## Frontend Guidance
- The renderer is React + TypeScript with Tailwind-based styling.
- Favor edits that keep the annotation workflow fast and keyboard-friendly.
- When changing analysis UI, ask:
  - Is this view for analysts, coaches, players, or more than one role?
  - Does this expose restricted insight to players?
  - Does this show confidence and sample-size context?
- Prefer reusable UI in:
  - `src/components/common/`
  - `src/components/annotation/`
  - `src/components/court/`
  - `src/components/video/`
- Keep navigation and page composition inside `src/pages/`.
- Avoid mixing business-rule text directly into page components when the same rule belongs in `RoleGuard`, shared report logic, or translation files.

## Backend Guidance
- FastAPI app bootstraps tables at startup through `create_tables()`.
- Database access goes through SQLAlchemy sessions from `backend/db/database.py`.
- Keep router responsibilities split by domain. Core domain routers:
  - `players.py`, `matches.py`, `sets.py`, `rallies.py`, `strokes.py`
  - `analysis.py` (and tiered variants: `analysis_stable.py`, `analysis_advanced.py`, `analysis_research.py`, `analysis_spine.py`, `analysis_bundle.py`)
  - `reports.py`
- Additional routers grouped by feature area:
  - Annotation/review: `bookmarks.py`, `comments.py`, `review.py`, `expert.py`
  - Conditions: `conditions.py`, `condition_tags.py`
  - CV / models: `cv_candidates.py`, `cv_benchmark.py`, `tracknet.py`, `yolo.py`, `yolo_realtime.py`, `court_calibration.py`
  - Sessions / auth: `sessions.py`, `auth.py`, `settings.py`
  - Ops / infra: `cluster.py`, `pipeline.py`, `db_maintenance.py`, `network_diag.py`, `tunnel.py`, `warmup.py`, `sync.py`, `benchmark.py`
  - Data flow: `uploads.py`, `video_import.py`, `data_package.py`
  - External-facing: `public_site.py`
  - Forecasting: `prediction.py`, `human_forecast.py`
- Put cross-cutting validation logic in `backend/utils/`.
- Put analysis logic in `backend/analysis/`. New analyses must be registered through the analysis tier registry (`backend/analysis/analysis_registry.py`) with stable / advanced / research tiering, evidence levels, and a minimum-sample threshold.
- The standalone analysis worker (`backend/pipeline/worker.py`) is a separate process. Do not move job-processing logic into request handlers; queue it through the pipeline so the worker can pick it up.
- WebSocket endpoints live in `backend/ws/`. Use the existing `ConnectionManager` patterns rather than ad-hoc websocket routes.
- If a feature changes stored meaning or structure, update models, validators, routers, and any dependent UI together. For DB schema changes, also create an Alembic migration.

## Analysis Tier System
- Analyses are registered through `backend/analysis/analysis_registry.py` and surfaced via tiered routers:
  - `analysis_stable.py` — production-ready analyses with established sample-size thresholds.
  - `analysis_advanced.py` — promoted-but-not-stable analyses; treat output as conditional.
  - `analysis_research.py` — experimental; not for player-facing UI under any circumstances.
  - `analysis_spine.py` / `analysis_bundle.py` — bundled cross-tier responses for review/research bundles.
- Promotion between tiers is governed by `backend/analysis/promotion_rules.py` (do not bypass).
- New analyses must declare evidence level, minimum sample size, and behavior when the threshold is unmet.
- Frontend views consuming research-tier output must surface explicit uncertainty warnings via `ConfidenceBadge` and never expose them to the `player` role.

## Pipeline And Worker
- The standalone worker (`backend/pipeline/worker.py`) processes `AnalysisJob` queue entries out-of-band from the API process.
- The worker and API both touch GPU resources; respect the existing GPU-conflict avoidance logic in `backend/services/gpu_health.py` and the worker startup.
- Long-running jobs (video import, shot classification, clip generation) belong in `backend/pipeline/` or `backend/services/`, never inline in request handlers.
- Job status flows back to the UI through the API; the frontend should not poll the worker process directly.

## WebSocket Layer
- WebSocket endpoints live in `backend/ws/` and are intentionally separate from REST routers.
- `backend/ws/live.py` implements the live-score broadcast (S-001) using a `ConnectionManager` keyed by session.
- `backend/ws/camera.py` implements the camera streaming protocol (S-002).
- New realtime features should reuse the existing `ConnectionManager` pattern instead of registering ad-hoc WebSocket routes on the FastAPI app.
- Client side: hooks like `useLiveInference.ts`, `useRealtimeYolo.ts`, and `useDeviceHeartbeat.ts` are the canonical entry points for realtime data on the renderer.

## Cluster And Distributed Mode
- Local single-machine operation remains the default; cluster mode is opt-in.
- Ray topology and remote queues live in `backend/cluster/`; configuration in `shuttlescope/cluster.config.yaml`.
- Cluster lifecycle scripts: `scripts/cluster/` (PostgreSQL primary/standby, failover promotion, route setup, primary/worker startup).
- Long-running supervision: PM2 via `scripts/pm2/ecosystem.config.js`.
- Remote access: Cloudflare tunnel under `infra/cloudflared/`; named-tunnel setup in `scripts/setup_cloudflare_named_tunnel.ps1`.
- Authentication hardening for cluster/remote mode is tracked in the top-level `2026-04-20_cluster_auth_hardening_execution_plan.md`. Read it before changing auth surfaces that are exposed beyond localhost.
- Do not weaken the local-only security posture (e.g. binding to `0.0.0.0` without auth) just to make cluster work easier.

## Data And Analytics Rules
- Player, match, set, rally, and stroke models represent the core domain.
- Annotation progress is meaningful product state; do not fake completion.
- Coordinates, stroke metadata, and derived metrics should remain explicit and inspectable.
- Confidence should be tied to available sample size and analysis scope.
- If you add a new analysis endpoint, include:
  - a clear response shape
  - confidence metadata
  - behavior for insufficient sample size
  - a UI state for loading, empty data, and warnings

## Role Model
- Current POC roles are:
  - `analyst`
  - `coach`
  - `player`
- Current POC auth is localStorage-based role switching in `src/hooks/useAuth.ts`.
- This is not secure authentication; it is only a local role simulation for the prototype.
- If implementing protected UI, assume:
  - analysts see the most raw operational data
  - coaches see analysis and reporting views
  - players see restricted growth-oriented views only

## Reporting Rules
- Coach-facing reporting can include more direct tactical analysis.
- Player-facing reporting must stay constructive and avoid direct weakness labeling.
- Any report that summarizes performance should include uncertainty context.
- If a report uses analytics, it should not silently hide low sample quality.

## Localization And Text Rules
- Default product language is Japanese.
- Keep strings in `src/i18n/ja.json`.
- Avoid introducing new hardcoded Japanese or English copy in TSX files.
- Preserve UTF-8 encoding when editing localization files.
- If a file displays mojibake in a shell, verify encoding before assuming the source text is broken.

## コートヒートマップ合成ビューの制約

- 打点タブ・着地点タブで相手コート側が灰色なのは不具合ではない。
  解析対象選手は相手コートに立たないため、意図した設計である。

- 合成タブの点対称変換は「可視化専用」。
  `backend/routers/analysis_stable.py` の `get_heatmap_composite()` が持つ変換は
  UIの視覚補助のためのみに使用すること。
  `backend/analysis/` 以下の空間分析コードはこの変換を呼び出してはならない。
  空間分析は `hit_zone`/`land_zone` の生データのみを使用すること。

- 合成ビューのデータソースは `/api/analysis/heatmap/composite` のみ。
  空間分析のエンドポイント（`/api/analysis/spatial/*`）は独立して動作する。

- テスト: `backend/tests/test_heatmap_composite.py` で点対称変換の正当性を検証済み。

## レスポンシブUI制約

- iOS 自動ズーム防止: `input, select, textarea` に `font-size: 16px !important` を適用済み
  (`src/styles/globals.css`)。font-size を小さくするスタイルは padding/height で代替すること。

- タブ横スクロール: `DashboardTopNav`, `DashboardSectionNav`, `SettingsPage` のタブは
  `overflow-x-auto scrollbar-hide` で横スクロール実装済み。`flex-wrap` に戻さないこと。

- モバイルカード形式: `MatchListPage` は `md:` 未満でカードリスト、`md:` 以上でテーブル。
  テーブルを全画面に戻さないこと。

- ボトムナビ: ダークモードトグルはモバイルボトムナビから除去済み。デスクトップサイドバーのみに表示。

## Local Environment Defaults
- npm scripts (run from `shuttlescope/`):
  - `npm run dev` — `electron-vite dev` (renderer + Electron)
  - `npm run build` — `electron-vite build` with `NODE_OPTIONS=--max-old-space-size=16384`
  - `npm run preview` — runs `scripts/preview.mjs`
  - `npm run start` — runs `scripts/start.mjs`
  - `npm run test` — Vitest (frontend tests)
  - `npm run lint` — ESLint over the repo
- Backend direct run:
  - `python backend/main.py`
  - or on Windows: `.\backend\.venv\Scripts\python backend/main.py`
- Standalone worker (background analysis jobs):
  - `python backend/pipeline/worker.py`
  - In production-like setups it is supervised via PM2 (`scripts/pm2/ecosystem.config.js`).
- Backend health endpoint:
  - `http://localhost:8765/api/health`
- Default local environment values are stored in:
  - `shuttlescope/.env.development`
- Bootstrap helpers (Windows):
  - `shuttlescope/bootstrap_windows.bat`, `bootstrap_windows.ps1`, `start.bat`

## Testing And Validation
- Frontend build is the minimum smoke check after UI or Electron changes:
  - `cd shuttlescope`
  - `npm run build`
- Frontend unit tests (Vitest):
  - `cd shuttlescope`
  - `npm run test`
- Lint:
  - `cd shuttlescope`
  - `npm run lint`
- Backend tests (pytest):
  - `cd shuttlescope`
  - `.\backend\.venv\Scripts\python -m pytest` (Windows)
  - or `python -m pytest` after activating the venv
- `pytest.ini` intentionally limits collection to `backend/tests` (`testpaths = backend/tests`) so helper scripts in `scripts/` do not break test runs.
- The backend test suite covers core domains plus subsystems: heatmap composite, analysis foundation, candidate builder, court calibration, condition analytics/questionnaire, Bayesian/Markov models, benchmarking, cluster bootstrap/pipeline, auth bootstrap, LAN session auth, standalone worker, YOLO/TrackNet integration, websocket signaling, live inference pipeline.
- If you touch API contracts, validate both backend responses and frontend call sites.
- If you touch annotation flow, validate:
  - keyboard flow
  - score progression
  - rally confirmation
  - local video loading
- If you touch the pipeline/worker, validate that:
  - the API process and worker process do not race over GPU resources
  - graceful shutdown still works
  - jobs are picked up off the queue and statuses propagate to the UI
- If you touch a WebSocket route, validate reconnection and multi-client fan-out via the relevant test (`test_websocket_signaling.py`, `test_live_inference_pipeline.py`).

## Git Hygiene
- The tracked application is under `shuttlescope/`, but commits happen from the repo root.
- Do not stage ignored confidential documents even if they are present locally.
- Be careful not to commit:
  - `node_modules/`
  - `out/`
  - `.venv/`
  - local DB files such as `shuttlescope.db`, `players.db`, `matches.db`, `results.db`
  - videos or generated reports
- Before committing, inspect `git status` from the repo root.
- Do not revert unrelated user changes.

## Change Strategy
- For product-facing changes, start by identifying which role sees the result.
- For data model changes, check all of:
  - SQLAlchemy models
  - API schemas
  - routers
  - frontend types
  - pages/components consuming the data
- For UI text changes, update translations first, then wire the key into components.
- For anything analytics-related, check confidence and uncertainty presentation before considering the task complete.

## Common Mistakes To Avoid
- Adding Japanese text directly in TSX instead of i18n.
- Showing analyst/coach-only metrics to players, or surfacing research-tier analyses to players.
- Returning optimistic analysis results without confidence metadata.
- Bypassing the analysis tier registry / promotion rules to expose experimental output as stable.
- Adding Electron IPC for app data when plain HTTP is the intended architecture.
- Doing long-running CV/analysis work inline in request handlers instead of going through the worker pipeline.
- Registering ad-hoc WebSocket routes instead of reusing the `ConnectionManager` patterns under `backend/ws/`.
- Committing local databases, generated reports, model weights, or confidential root docs.
- Treating the localStorage role switch as production auth — particularly when enabling cluster / remote-tunnel deployment.
- Calling the heatmap composite point-symmetry transform from spatial analysis code (it is visualization-only; see コートヒートマップ section).

## If The Confidential Docs Are Not Available
- Use this file as the minimum operating manual.
- Preserve the current architecture and product safety rules.
- Bias toward conservative, honest UX for analytics.
- When unsure, prefer:
  - more uncertainty disclosure
  - stricter player-facing restrictions
  - smaller scoped changes
