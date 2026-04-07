# ShuttleScope

ShuttleScope is a local-first Windows desktop app for badminton annotation and match analysis.
It is being built mainly for coach and analyst use, with player-safe presentation where needed.

At the current stage, the core value is:

- fast structured annotation
- post-match review
- badminton-specific analysis
- local sharing and testing workflows

Prediction is included and growing, but the product is still best understood as an annotation + analytics PoC rather than a finished commercial platform.

## What It Does Today

### Annotation

- quick-start match creation
- rally-by-rally stroke annotation
- numpad-based landing input
- skipped rally handling
- score correction
- forced set end / exception handling
- match-day mode for faster operation
- doubles hitter switching within the same side
- set interval summary and mid-game summary

### Analysis / Review

- court heatmaps
- score progression and set comparison
- shot / rally / temporal analysis
- pre-win and pre-loss pattern views
- growth and trend views across matches
- doubles / partner analysis
- warm-up observation analysis
- confidence-aware analytics display

### Prediction

- match preview
- pair simulation
- fatigue risk estimation
- tactical notes and score distribution views

This area is already usable, but still under active refinement.

### Sharing / Access

- live session sharing
- comments and bookmarks
- LAN access from browser clients on the same Wi-Fi
- QR sharing for LAN URLs
- optional temporary tunnel-based access
- network diagnostics

### Video / Tracking

- local video workflow
- WebView-based playback path
- video-only second-screen workflow
- TrackNet integration path and runtime selection

## Main Screens

- `MatchListPage`
  - match creation and entry point
- `AnnotatorPage`
  - live / post-match annotation workflow
- `DashboardPage`
  - review and analysis
- `PredictionPage`
  - prediction and pair simulation
- `SettingsPage`
  - player management, sharing, TrackNet, and role switching
- `VideoOnlyPage`
  - second-screen / video-only view

## Intended Users

- `analyst`
- `coach`
- `player`

Coach and analyst views can expose deeper review and prediction features.
Player-facing views are meant to stay more conservative.

## Tech Stack

- Electron
- React 18 + TypeScript + Vite
- Zustand
- TanStack Query
- FastAPI
- SQLite
- Recharts / D3
- NumPy / SciPy / scikit-learn
- ReportLab / matplotlib

## Repository Layout

```text
shuttle-scope/
├─ README.md
├─ LICENSE
├─ CLAUDE.md
├─ private_docs/                # local private notes, ignored
├─ .github/workflows/           # CI / smoke workflows
└─ shuttlescope/
   ├─ electron/
   ├─ src/
   ├─ backend/
   ├─ docs/
   ├─ scripts/
   └─ shuttlescope.db
```

## Setup

### Requirements

- Windows as the primary target environment
- Node.js 18+
- Python 3.10+
- optional: `ffmpeg`
- optional: `cloudflared`

### Dev run

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

The default backend URL is `http://127.0.0.1:8765`.

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

- main CI
- desktop package smoke
- TrackNet smoke

## Data and Local Files

- the current database is SQLite
- the default DB file is `shuttlescope/shuttlescope.db`
- `private_docs/` is ignored
- `shuttlescope/docs/validation/` is ignored
- local DBs, videos, TrackNet weights, and generated artifacts are not committed

## Current Status

ShuttleScope is already useful as an internal badminton analysis PoC, especially for:

- structured annotation
- post-match review
- exploratory tactical analysis
- growth tracking
- doubles-aware review

It is still evolving in:

- operational polish
- broader field validation
- prediction depth and quality
- research-heavy analysis modules
- long-term sharing and deployment hardening

In short, ShuttleScope is already a serious internal tool, but it is still under active development and should be read as a practical PoC rather than a finished product.
