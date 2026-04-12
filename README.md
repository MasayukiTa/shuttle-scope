# ShuttleScope

ShuttleScope is a local-first Windows desktop workbench for structured badminton match annotation, post-match review, and badminton-specific analysis.

Right now, the fastest honest way to understand it is this:

- it is already usable as an internal tool for rally-by-rally annotation and coach / analyst review
- it is strong in local workflows: match creation, annotation, dashboard review, local video, and post-match analysis
- it already contains CV, prediction, LAN sharing, and remote-camera groundwork
- it is not yet a finished public product, and some of those advanced layers are still under active validation

In other words, ShuttleScope is no longer just a loose PoC, but it is also not something we should describe as a finished commercial release.

## What You Can Actually Do With It Today

If someone opens ShuttleScope today, the parts they can realistically expect to use are:

- create and edit matches, players, and doubles pairings
- annotate rallies stroke by stroke
- review rallies with comments, bookmarks, review-later markers, and warm-up notes
- run badminton-specific dashboard analysis across matches
- use local video with second-screen playback and court calibration support
- test CV-assisted annotation workflows and TrackNet / YOLO readiness on prepared environments
- share sessions on nearby devices over LAN with password-protected join flow

The parts that still need more real-world proof are:

- real-video CV quality and threshold tuning
- remote camera and browser video transport
- prediction quality under live or operational use
- fully automatic annotation without human verification

## Current Product Position

ShuttleScope is currently best understood as:

- an internal product-grade badminton analysis system
- a practical annotation and review tool for coaches / analysts
- a local-first experimentation platform for deeper analytics, prediction, and CV-assisted workflows

It is strongest in the annotation / review core, with research and CV layers built on top of that core rather than replacing it.

## Current Focus

The strongest parts of ShuttleScope today are:

- structured match annotation
- post-match review
- badminton-specific analytics
- local video workflow
- limited LAN sharing for nearby devices

Prediction, CV-assisted annotation, remote camera support, and research views are present in the codebase, but they are still uneven in real-world validation and should be treated as active development areas.

## What Works Well Today

### Annotation

- quick-start match creation
- match create/edit flow
- rally-by-rally stroke annotation
- stroke history and rally-by-rally review
- numpad-based landing input
- skipped rally handling
- score correction and forced set end handling
- doubles hitter switching
- initial server selection and analyst viewpoint persistence
- manual record / assisted record modes
- review-later flow for incomplete rallies
- warm-up / pre-match observation capture
- comments, bookmarks, and review markers around a match session

### Match and Player Management

- searchable player selectors in match creation
- provisional player creation during match setup
- team-aware player registration flow
- match editing after creation
- player deletion guard when the player is still referenced by matches
- player team history support at the data model and settings level

### Review and Analysis

- court heatmaps
- score progression and set comparison
- shot, rally, and time-based analysis
- zone maps and effective / vulnerable area views
- date-range filtering and recent-match filtering
- growth and trend views across matches
- doubles and partner analysis
- warm-up observation analysis
- recommendation and ranking style views
- stable / advanced / research dashboard split
- dashboard split into overview / live / review / growth / advanced / research

### Prediction and Research

- match preview and pair-oriented prediction views
- human forecast / analyst comparison groundwork
- fatigue and hazard style research views
- research cards for state/value/counterfactual-oriented analysis
- promotion workflow and evidence metadata groundwork

These areas are usable for internal exploration, but they are still a step behind the annotation/review core in real-world confidence.

### Video and CV Workflow

- local video import
- second-screen `Video Only` view
- court calibration overlay
- backend-persisted calibration with local fallback
- TrackNet and YOLO readiness checks
- TrackNet shuttle-track persistence
- YOLO player-position artifact flow
- CV assist candidate flow, candidate badges, and review queue foundation
- player / shuttle overlay groundwork in the annotator
- benchmark and doctor scripts for CV environment validation

These areas are useful for development and internal testing, but CV quality still depends heavily on real-video validation.

### Sharing and Access

- LAN session sharing
- password-protected LAN sessions
- comments and bookmarks
- QR-based join flow
- device manager and camera sender pages
- viewer page and grouped device / handoff UX groundwork
- tunnel-provider selection and remote health status groundwork

Remote and browser-based video workflows exist, but they should still be treated as experimental compared with the core local workflow.

## Main Screens

- `Match List`
- `Annotator`
- `Dashboard`
- `Prediction`
- `Settings`
- `Video Only`

## Current Product Shape

In practical terms, ShuttleScope currently behaves like a desktop badminton analysis workbench with several layers:

- a core annotation workflow that is already useful
- a growing post-match analysis stack
- a research layer that is visible in the product but still being validated
- a CV layer that assists annotation rather than fully replacing it
- a LAN / remote collaboration layer that is promising but not yet the main operating mode

## Intended Use Right Now

ShuttleScope is currently strongest for:

- structured post-match annotation
- coach / analyst review
- exploratory tactical analysis
- doubles-aware review
- small-team internal testing and iteration
- internal testing with local or nearby devices

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
- optional: `ngrok`
- optional: `cloudflared`

### Fastest New-Device Bootstrap

For a fresh Windows machine:

```powershell
cd shuttlescope
.\bootstrap_windows.ps1 -RunDoctor
```

If PowerShell is inconvenient:

```bat
cd shuttlescope
bootstrap_windows.bat -RunDoctor
```

Optional extras:

```powershell
.\bootstrap_windows.ps1 -IncludeYolo
.\bootstrap_windows.ps1 -SetupTrackNet
```

The doctor can also be run directly:

```powershell
.\backend\.venv\Scripts\python -m backend.tools.setup_doctor
```

Useful variants:

```powershell
.\backend\.venv\Scripts\python -m backend.tools.setup_doctor --format json
.\backend\.venv\Scripts\python -m backend.tools.setup_doctor --strict
```

The doctor reports:

- missing Python / npm tools
- TrackNet readiness
- YOLO readiness
- `ngrok` / `cloudflared` availability
- key Python package versions
- recommended next steps for the current machine

This setup path is already one of the stronger parts of the project: new-device bootstrap is much better than a typical research prototype, even though model/runtime setup still needs attention.

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

## TrackNet / YOLO Notes

- TrackNet needs weights and runtime support
- YOLO needs `ultralytics` or a local ONNX/PT model
- the bootstrap and doctor commands above are the quickest way to check readiness on a new device
- current CV support should be read as assistive and development-stage, not fully automatic production annotation
- real match videos are still the main requirement for confidence tuning, threshold adjustment, and practical validation

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
- local DBs, videos, CV weights, and generated artifacts are not committed

## Current Status

ShuttleScope is already useful as an internal badminton analysis tool.
Its strongest areas today are:

- annotation flow
- review and dashboard structure
- badminton-specific analysis
- local setup / bootstrap / doctor support

It is weaker, or still more conditional, in:

- real-video CV quality
- remote video transport and browser-camera reliability
- prediction quality under live use
- broad operator-facing polish and recovery behavior

The biggest areas still under active validation are:

- CV quality on real match video
- remote camera and browser video workflows
- prediction quality under real use
- operator-facing polish and failure recovery

This repository should be read as an active internal product prototype with many working features, not as a finished public release announcement.
