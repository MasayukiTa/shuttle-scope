# ShuttleScope Claude Guide

## Purpose
- ShuttleScope is a desktop badminton video annotation and analysis application.
- The tracked app code lives under `shuttlescope/`.
- The git repository root also contains local confidential planning documents under `private_docs/`; they must not be committed.
- This file exists to preserve the most important product and implementation rules even when the confidential source documents are unavailable.

## Working Directory Map
- Repo root: git root, confidentiality rules, top-level agent guidance.
- `shuttlescope/`: actual app root.
- `shuttlescope/electron/`: Electron main/preload process.
- `shuttlescope/src/`: React renderer.
- `shuttlescope/backend/`: FastAPI app, SQLAlchemy models, routers, validation logic.
- `shuttlescope/scripts/`: local helper scripts and test dataset utilities.

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
- Desktop shell: Electron.
- Renderer: React + TypeScript.
- Backend: FastAPI.
- Local DB: SQLite.
- Planned future DB: PostgreSQL.
- Frontend communicates with the backend over HTTP on `localhost:8765`.
- Do not introduce Electron IPC for application API calls unless there is a strong reason; the current design intentionally uses HTTP to make later server migration easier.
- Electron main process launches Python as a child process.
- Local video selection uses the custom `localfile://` protocol registered in `shuttlescope/electron/main.ts`.

## Source Of Truth Files
- Backend schema: `shuttlescope/backend/db/models.py`
- Backend startup and router registration: `shuttlescope/backend/main.py`
- Backend config defaults: `shuttlescope/backend/config.py`
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
- Keep router responsibilities split by domain:
  - `players.py`
  - `matches.py`
  - `sets.py`
  - `rallies.py`
  - `strokes.py`
  - `analysis.py`
  - `reports.py`
- Put cross-cutting validation logic in `backend/utils/`.
- Put analysis logic in `backend/analysis/`.
- If a feature changes stored meaning or structure, update models, validators, routers, and any dependent UI together.

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

## Local Environment Defaults
- Renderer dev command:
  - `npm run dev`
- Production build check:
  - `npm run build`
- Backend direct run:
  - `python backend/main.py`
  - or on Windows: `.\backend\.venv\Scripts\python backend/main.py`
- Backend health endpoint:
  - `http://localhost:8765/api/health`
- Default local environment values are stored in:
  - `shuttlescope/.env.development`

## Testing And Validation
- Frontend build is the minimum smoke check after UI or Electron changes:
  - `cd shuttlescope`
  - `npm run build`
- Backend tests:
  - `cd shuttlescope`
  - `.\backend\.venv\Scripts\python -m pytest`
- `pytest.ini` intentionally limits collection to `backend/tests` so helper scripts in `scripts/` do not break test runs.
- If you touch API contracts, validate both backend responses and frontend call sites.
- If you touch annotation flow, validate:
  - keyboard flow
  - score progression
  - rally confirmation
  - local video loading

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
- Showing analyst/coach-only metrics to players.
- Returning optimistic analysis results without confidence metadata.
- Adding Electron IPC for app data when plain HTTP is the intended architecture.
- Committing local databases or confidential root docs.
- Treating the localStorage role switch as production auth.

## If The Confidential Docs Are Not Available
- Use this file as the minimum operating manual.
- Preserve the current architecture and product safety rules.
- Bias toward conservative, honest UX for analytics.
- When unsure, prefer:
  - more uncertainty disclosure
  - stricter player-facing restrictions
  - smaller scoped changes
