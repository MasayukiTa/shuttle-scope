# ShuttleScope

ShuttleScope is a badminton annotation, review, analytics, and prediction platform built as a local-first Windows desktop app.
It combines an Electron + React frontend with a FastAPI backend, SQLite storage, and an expanding set of badminton-specific research-inspired analysis modules.

The current product is no longer just a rally tagging tool.
It already covers:

- fast live or post-match annotation
- post-match review for coaches and analysts
- growth and trend tracking across matches
- doubles / partner analysis
- pre-match observation capture
- prediction and pair simulation
- LAN / browser sharing and temporary tunnel-based remote access

## What ShuttleScope Is For

ShuttleScope is designed to help a badminton team do three things in one system:

1. Capture structured match data quickly
2. Turn that data into useful review and coaching insight
3. Use accumulated history to support future lineup, tactical, and match prediction decisions

The intended users are mainly:

- analysts
- coaches
- players

Player-facing views are intentionally more conservative.
Coach and analyst views can expose deeper tactical interpretation, prediction, and lineup support.

## Current Product Shape

### Match List

- quick-start match creation
- singles and doubles entry flow
- match-day oriented start flow
- warm-up / pre-match observation entry
- reviewable match list and seed-data support

### Annotator

- keyboard-first stroke annotation
- numpad-based landing input
- live-friendly match-day mode
- skipped rally handling
- score correction
- forced set end / exception handling
- set interval summary and mid-game summary
- doubles hitter switching inside the same side
- stroke history with partner-aware labels

### Analytics

- court heatmaps and zone-level drill-down
- score progression and set comparison
- first-return, pre-win, pre-loss, temporal, and pattern analysis
- review and growth views
- doubles / partner analysis
- opponent-oriented analysis
- warm-up observation analytics
- EPV / Markov / shot influence style analysis
- confidence-aware presentation

### Prediction

- top-level prediction page
- match preview
- coach-ready summary strip
- match script estimation
- tactical recommendation ranking
- prediction drivers / evidence source explanation
- fatigue risk estimation
- pair simulation
- scoreline / set distribution displays

### Sharing / Access

- live session creation
- coach-view / session share workflows
- comments and bookmarks
- LAN access from browser clients on the same Wi-Fi
- QR-code sharing for LAN URLs
- optional Cloudflare Tunnel control from settings
- network diagnostics and transport guidance

### Tracking

- TrackNet integration path
- backend selection (`auto`, `onnx_cpu`, `tensorflow_cpu`, `openvino`)
- local weight / export workflow
- Git-ignored model artifacts

## Main Screens

- `MatchListPage`
  - match creation, quick start, and entry point
- `AnnotatorPage`
  - live / post-match annotation workflow
- `DashboardPage`
  - analytics, review, growth, doubles, and research-style analysis
- `PredictionPage`
  - match forecasting, fatigue risk, and pair simulation
- `SettingsPage`
  - player management, sharing, TrackNet, and account / role controls
- `VideoOnlyPage`
  - second-screen / video-only Electron workflow

## Tech Stack

- Desktop shell: Electron
- Frontend: React 18, TypeScript, Vite
- State / data: Zustand, TanStack Query
- Visualization: Recharts, D3
- Backend: FastAPI
- Database: SQLite
- Analysis libraries: NumPy, SciPy, scikit-learn
- Reporting: ReportLab, matplotlib
- Tracking path: ONNX Runtime / TensorFlow / OpenVINO
- Packaging: electron-builder
- CI: GitHub Actions

## Repository Layout

```text
shuttle-scope/
├─ README.md
├─ LICENSE
├─ CLAUDE.md
├─ private_docs/                # local private notes, ignored
├─ .github/workflows/           # CI / packaging / TrackNet smoke
└─ shuttlescope/
   ├─ electron/                 # Electron main / preload
   ├─ src/
   │  ├─ api/
   │  ├─ components/
   │  ├─ hooks/
   │  ├─ i18n/
   │  ├─ pages/
   │  ├─ store/
   │  ├─ styles/
   │  └─ types/
   ├─ backend/
   │  ├─ analysis/
   │  ├─ db/
   │  ├─ routers/
   │  ├─ tests/
   │  ├─ tracknet/
   │  └─ ws/
   ├─ docs/
   ├─ scripts/
   └─ shuttlescope.db
```

## Backend Routes

The backend already includes dedicated routers for:

- matches
- players
- strokes / rallies / sets
- analysis
- prediction
- reports
- warm-up observations
- sharing sessions
- comments / bookmarks
- network diagnostics
- TrackNet
- tunnel control

## Setup

### Requirements

- Windows is the primary target environment
- Node.js 18+
- Python 3.10+
- `ffmpeg` for broader media workflows
- optional: `cloudflared` for temporary external tunnel access

### App install and dev run

```bash
cd shuttlescope
npm install
npm run dev
```

### Production build

```bash
cd shuttlescope
npm run build
```

### Desktop startup

```bash
cd shuttlescope
npm run start
```

or:

```bat
shuttlescope\start.bat
```

### Backend only

```bash
cd shuttlescope/backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

The default local backend URL is `http://127.0.0.1:8765`.

## Tests

### Frontend

```bash
cd shuttlescope
npx vitest run --config vitest.config.ts
```

### Backend

```bash
cd shuttlescope
.\backend\.venv\Scripts\python -m pytest backend/tests/ -q
```

### Build check

```bash
cd shuttlescope
npm run build
```

## CI

GitHub Actions workflows are included for:

- main CI (`build`, `vitest`, `pytest`)
- desktop package smoke
- TrackNet smoke / export checks

See:

- `.github/workflows/ci.yml`
- `.github/workflows/desktop-package-smoke.yml`
- `.github/workflows/tracknet-smoke.yml`

## Data and Database

- the current local database is SQLite
- the default DB file is `shuttlescope/shuttlescope.db`
- player, match, rally, stroke, warm-up observation, sharing, and settings data are stored locally
- the architecture is intended to remain compatible with future networked or PostgreSQL-oriented expansion

## TrackNet Notes

- TrackNet support exists as an integration path, not a required dependency for normal app use
- model weights and exported artifacts are intentionally ignored by Git
- backend selection can be switched through settings

## Local-Only / Ignored Content

The following are intentionally not committed:

- `private_docs/`
- `shuttlescope/docs/validation/`
- local databases
- videos and temporary media
- TrackNet weights / exported artifacts
- generated local outputs

## Product Status

ShuttleScope is already useful as a badminton-specific PoC and internal competition tool.
Its strongest areas are now:

- structured annotation
- badminton-specific analytics
- review and growth workflows
- doubles-aware analysis
- prediction / pair simulation foundations
- local-first collaboration and browser access

It is still evolving in:

- operational polish
- broader field validation
- long-horizon prediction quality
- advanced model-backed research modules
- production-grade sharing / access hardening

In short: ShuttleScope has moved well beyond a simple annotation prototype, but it is still being actively shaped into a full badminton intelligence platform.
