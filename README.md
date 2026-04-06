# ShuttleScope

ShuttleScope is a Windows desktop app for badminton annotation, review, and match analysis.
It combines an Electron + React UI with a local FastAPI backend and SQLite database, with a strong focus on:

- fast point-by-point annotation during or after matches
- post-match review for coaches and analysts
- player-safe presentation of analytics
- local-first operation with optional LAN/session sharing

This repository contains the app shell, annotation workflow, analytics dashboard, sharing workflow, and TrackNet integration scaffolding.

## Current Product Shape

### Annotator

- quick-start match creation
- rally-by-rally stroke annotation
- numpad-based landing input and keyboard-first workflow
- skipped rally handling and score correction
- match-day mode for faster live operation
- set interval summary and mid-game review hooks
- video modes for local, WebView, and no-video operation
- dual-monitor / video-only workflow in Electron

### Analytics / Review

- court heatmaps and zone-level review
- shot-type and pattern analysis
- score progression and set comparison
- first-return, pre-win, pre-loss, and temporal analysis
- growth / trend views across matches
- doubles / partner-oriented analysis
- EPV / Markov / shot influence style analysis
- confidence-aware presentation for analytics

### Sharing / Collaboration

- live session creation and LAN sharing
- coach-view / session share flows
- comments and bookmarks
- network diagnostics

### Tracking

- TrackNet backend route and runtime selection
- ONNX / TensorFlow / OpenVINO-oriented integration path
- local weights and exported artifacts kept out of Git

## Tech Stack

- Desktop: Electron
- Frontend: React 18, TypeScript, Vite
- State / data: Zustand, TanStack Query
- Charts / visualization: Recharts, D3
- Backend: FastAPI
- Database: SQLite
- Analysis: NumPy, SciPy, scikit-learn
- Reporting: ReportLab, matplotlib
- Tracking integration: ONNX Runtime / TensorFlow / OpenVINO path

## Repository Layout

```text
shuttle-scope/
├─ README.md
├─ LICENSE
├─ CLAUDE.md
├─ private_docs/                # local private notes, ignored
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

## Main Screens

- `MatchListPage`
  - quick start, match creation, and match entry point
- `AnnotatorPage`
  - live / post-match annotation workflow
- `DashboardPage`
  - analysis, review, growth, and doubles views
- `SettingsPage`
  - app, video, sharing, and TrackNet-related settings
- `VideoOnlyPage`
  - second-screen / video-only presentation

## Roles

The app is designed around role-aware presentation:

- `analyst`
- `coach`
- `player`

Player-facing presentation is intentionally more conservative than coach / analyst views.
The codebase uses role gating and confidence-aware analytics to avoid exposing raw weak-point language or overconfident conclusions where inappropriate.

## Setup

### Requirements

- Windows as the primary target environment
- Node.js 18+
- Python 3.10+
- `ffmpeg` if you want broader download or media processing capability

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

You can also launch with:

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

The local FastAPI backend runs on `http://127.0.0.1:8765` by default.

## Tests

### Frontend tests

```bash
cd shuttlescope
npx vitest run --config vitest.config.ts
```

### Backend tests

```bash
cd shuttlescope
.\backend\.venv\Scripts\python -m pytest -v
```

### Build check

```bash
cd shuttlescope
npm run build
```

## Data and Database

- the current local database is SQLite
- the default database file is `shuttlescope/shuttlescope.db`
- player, match, rally, stroke, sharing, and settings data live in the local app DB
- the architecture is intended to allow a future move to PostgreSQL or a more networked deployment model

## TrackNet Notes

- TrackNet support is being integrated as a local runtime option
- large weights and exported model artifacts are intentionally ignored by Git
- backend settings support backend selection such as `auto`, `onnx_cpu`, `tensorflow_cpu`, and `openvino`

## Scripts

`shuttlescope/scripts/` contains local helper scripts for startup, data generation, and migration-style support work.
Examples include:

- `start.mjs`
- `preview.mjs`
- `generate_test_data.py`
- `generate_doubles_data.py`
- `generate_first_return_data.py`

## Notes

- `private_docs/` is private and ignored
- `shuttlescope/docs/validation/` contains local validation notes and is ignored
- local databases, videos, TrackNet weights, and generated artifacts are kept out of Git
- Japanese UI strings should be managed through `shuttlescope/src/i18n/ja.json`

## Status

ShuttleScope is already useful as a badminton-specific analysis PoC and internal tool, especially for:

- post-match review
- structured annotation
- exploratory tactical analysis
- growth and trend tracking

It is not yet positioned as a finished commercial-grade platform.
The strongest current areas are badminton-specific analytics and review workflows; the main areas still evolving are operational polish, collaboration depth, and long-term automation.
