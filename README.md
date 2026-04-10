# ShuttleScope

ShuttleScope is a local-first Windows desktop app for badminton annotation and review.
It is currently aimed at coaches, analysts, and internal testing workflows rather than public release.

The current core is:

- match annotation
- post-match review
- badminton-specific analysis
- local LAN sharing for nearby devices

Prediction, live camera workflows, and tracking are already present in the codebase, but the product is still best understood as a practical internal PoC.

## What Works Today

### Annotation

- quick-start match creation
- rally-by-rally stroke annotation
- numpad-based landing input
- skipped rally handling
- score correction and forced set end handling
- doubles hitter switching
- manual record / assisted record modes
- review-later flow for incomplete rallies

### Analysis

- court heatmaps
- score progression and set comparison
- shot, rally, and time-based analysis
- pre-win and pre-loss pattern views
- growth and trend views across matches
- doubles and partner analysis
- warm-up observation analysis
- confidence-aware displays

### Prediction

- match preview
- pair simulation
- fatigue-related risk hints
- score distribution and tactical note views

This area is usable, but still under active refinement.

### Sharing and Access

- live session sharing
- comments and bookmarks
- LAN access from browser clients on the same network
- QR-based join flow
- password-protected LAN sessions
- device manager and camera sender pages

### Video and Tracking

- local video workflow
- second-screen video-only view
- LAN camera sender groundwork
- TrackNet runtime selection

## Main Screens

- `Match List`
- `Annotator`
- `Dashboard`
- `Prediction`
- `Settings`
- `Video Only`

## Intended Use

ShuttleScope is currently strongest for:

- structured post-match annotation
- coach and analyst review
- exploratory tactical analysis
- doubles-aware review
- internal LAN-based testing

It should not be read as a finished commercial product yet.

## Tech Stack

- Electron
- React 18 + TypeScript + Vite
- Zustand
- TanStack Query
- FastAPI
- SQLite
- Alembic
- Recharts / D3
- NumPy / SciPy / scikit-learn

## Repository Layout

```text
shuttle-scope/
├─ README.md
├─ LICENSE
├─ private_docs/              # local private notes, ignored
├─ .github/workflows/         # CI and smoke workflows
└─ shuttlescope/
   ├─ electron/
   ├─ src/
   ├─ backend/
   ├─ docs/
   ├─ scripts/
   └─ start.bat
```

## Setup

### Requirements

- Windows as the main target environment
- Node.js 18+
- Python 3.10+
- optional: `ffmpeg`
- optional: `cloudflared`

### Fastest New-Device Bootstrap

For a fresh Windows machine, the easiest path is:

```powershell
cd shuttlescope
.\bootstrap_windows.ps1 -RunDoctor
```

If PowerShell is inconvenient, a batch wrapper is also available:

```bat
cd shuttlescope
bootstrap_windows.bat -RunDoctor
```

Optional extras:

```powershell
.\bootstrap_windows.ps1 -IncludeYolo
.\bootstrap_windows.ps1 -SetupTrackNet
```

The doctor output can also be run directly:

```powershell
.\backend\.venv\Scripts\python -m backend.tools.setup_doctor
```

JSON mode and strict mode are available too:

```powershell
.\backend\.venv\Scripts\python -m backend.tools.setup_doctor --format json
.\backend\.venv\Scripts\python -m backend.tools.setup_doctor --strict
```

This reports:

- missing Python / npm tools
- TrackNet weights / backend readiness
- YOLO runtime readiness
- `ngrok` / `cloudflared` availability
- key Python package versions
- recommended next steps for this machine
- an exit code you can use in automation

### Install and Run

```bash
cd shuttlescope
npm install
npm run dev
```

### Build

```bash
cd shuttlescope
npm run build
```

### Desktop Start

```bash
cd shuttlescope
npm run start
```

or:

```bat
shuttlescope\start.bat
```

### Backend Only

```bash
cd shuttlescope/backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

The default backend URL is `http://127.0.0.1:8765`.

### TrackNet / YOLO Notes

- TrackNet needs weights and runtime support
- YOLO needs `ultralytics` or a local ONNX/PT model
- the bootstrap and doctor commands above are the quickest way to check readiness on a new device

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

### Build Check

```bash
cd shuttlescope
npm run build
```

## CI

GitHub Actions workflows are included for:

- CI
- desktop package smoke
- TrackNet smoke

## Local Data

- the current database is SQLite
- the default database file is `shuttlescope/shuttlescope.db`
- `private_docs/` is ignored
- `shuttlescope/docs/validation/` is ignored
- local DBs, videos, TrackNet weights, and generated artifacts are not committed

## Current Status

ShuttleScope is already useful as an internal badminton analysis tool and PoC.
Its strongest areas today are annotation, review, and badminton-specific analysis.

Some larger areas are still being actively shaped, especially:

- prediction quality
- live camera workflows
- realtime inference integration
- broader field validation

The repo should be read as an active internal project with working features, not as a finished product announcement.
