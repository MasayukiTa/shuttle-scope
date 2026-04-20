# ShuttleScope

ShuttleScope is a local-first Windows desktop workbench for badminton match annotation, review, and analysis.

The quickest honest summary is:

- it is already usable as an internal tool for rally-by-rally annotation and coach / analyst review
- it is strongest in local workflows: match setup, annotation, dashboard review, local video, desktop capture, and post-match analysis
- it already includes CV, prediction, LAN sharing, and remote-camera groundwork, but those layers are still less proven than the annotation core
- it is not yet a finished public product, and advanced CV / remote / prediction areas are still under active validation

In short, ShuttleScope is well past a loose PoC, but it should still be described as an internal product-grade system rather than a finished commercial release.

## What You Can Actually Do With It Today

If someone opens ShuttleScope today, the parts they can realistically expect to use are:

- create and edit matches, players, and doubles pairings
- sign in with role-aware local auth flows for admin / analyst / coach / player
- annotate rallies stroke by stroke
- review rallies with comments, bookmarks, review-later markers, and warm-up notes
- run badminton-specific dashboard analysis across matches
- inspect condition data through role-aware filtered views rather than one unrestricted surface
- use local video, second-screen playback, and court calibration support
- capture desktop video regions, define ROI, and run ROI-aware CV batch analysis on prepared environments
- test CV-assisted annotation flows, candidate review, and TrackNet / YOLO readiness on prepared environments
- benchmark CPU / GPU / OpenVINO / Ray-capable environments from Settings and compare available inference targets
- configure Ray / cluster routing from Settings and inspect worker availability, load limits, and network health
- share sessions on nearby devices over LAN with password-protected join flow

The parts that still need more real-world proof are:

- real-video CV quality and threshold tuning
- remote camera and browser video transport
- prediction quality under live or operational use
- fully automatic annotation without human verification
- long-running operator recovery and failure handling under heavy live use

## Current Product Position

ShuttleScope is currently best understood as:

- an internal product-grade badminton analysis system
- a practical annotation and review tool for coaches / analysts
- a local-first experimentation platform for deeper analytics, prediction, CV assistance, and sharing workflows

It is strongest in the annotation / review core, with research and CV layers built on top of that core rather than replacing it.

## Current Focus

The strongest parts of ShuttleScope today are:

- structured match annotation
- post-match review
- badminton-specific analytics
- local video workflow
- desktop capture and ROI-based CV workflow
- limited LAN sharing for nearby devices

Prediction, CV-assisted annotation, remote camera support, and research views are present in the codebase, but they are still uneven in real-world validation and should be treated as active development areas.

## What Works Well Today

### Annotation

- quick-start match creation
- match create / edit flow
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
- user management for role-aware local access control
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
- pre-match snapshot groundwork
- human forecast / analyst comparison groundwork
- fatigue and hazard style research views
- research cards for state / value / counterfactual-oriented analysis
- promotion workflow and evidence metadata groundwork

These areas are usable for internal exploration, but they are still a step behind the annotation / review core in real-world confidence.

### Video and CV Workflow

- local video import
- desktop capture with ROI selection
- second-screen `Video Only` view
- court calibration overlay
- backend-persisted calibration with local fallback
- ROI-aware TrackNet / YOLO batch processing
- CV resume / diff workflow foundation
- TrackNet and YOLO readiness checks
- GPU device selection and setup checks in Settings
- TrackNet shuttle-track persistence
- YOLO player-position artifact flow
- CV assist candidate flow, candidate badges, and review queue foundation
- player / shuttle overlay groundwork in the annotator
- realtime YOLO overlay and player-tracking foundation
- benchmark jobs, device probing, and doctor scripts for CV environment validation
- YOLO benchmark target and backend override controls
- Ray / worker-aware benchmark routing for cluster environments

These areas are useful for development and internal testing, but CV quality still depends heavily on real-video validation.

### Sharing and Access

- LAN session sharing
- password-protected LAN sessions
- role-aware local login flow for admin / analyst / coach / player
- JWT-backed local auth session handling
- user management page for creating and maintaining role-bound users
- access logging groundwork for auth and sensitive data access
- condition views filtered by audience and field sensitivity
- comments and bookmarks
- QR-based join flow
- device manager and camera sender pages
- viewer page and grouped device / handoff UX groundwork
- tunnel-provider selection and remote health status groundwork

Remote and browser-based video workflows exist, but they should still be treated as experimental compared with the core local workflow.

### Cluster and Distributed Processing

- two-node cluster foundation for a primary machine plus worker machine
- Ray-aware task routing for TrackNet, pose, clip extraction, and analysis stages
- Settings-based cluster management with interface selection, worker list, ping tests, and load thresholds
- worker bootstrap support for K10-style CPU / iGPU nodes
- firewall / routing support scripts for Windows cluster deployment
- graceful fallback to local execution when Ray or worker capabilities are unavailable

## Main Screens

- `Login`
- `Match List`
- `Annotator`
- `Dashboard`
- `Prediction`
- `Settings`
- `User Management`
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
- role-aware internal access for coaches, analysts, admins, and players
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
├─ CHANGELOG.md
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

### Worker / Cluster Setup

If you are preparing a second Windows machine as a Ray worker:

```powershell
cd shuttlescope
.\scripts\setup_k10_worker.ps1
```

Related files:

- `shuttlescope\requirements_worker.txt`
- `shuttlescope\cluster.config.yaml`
- `shuttlescope\scripts\cluster\start_primary.bat`
- `shuttlescope\scripts\fix_ray_firewall.ps1`

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

### Authentication Notes

- ShuttleScope now includes a local role-aware login flow with separate paths for admin, analyst, coach, and player access.
- Player access is designed around player-linked accounts and PIN-style entry, while admin access uses password login.
- Coach and analyst views are intended for internal workflows and do not expose the same condition-detail surface as player self-view or privileged admin flows.
- Sensitive access now depends on backend auth context rather than only frontend role selection.
- The first admin user is no longer created with a hard-coded password. For a fresh environment, set `BOOTSTRAP_ADMIN_PASSWORD` before the first admin login.
- Optional bootstrap knobs are `BOOTSTRAP_ADMIN_USERNAME` and `BOOTSTRAP_ADMIN_DISPLAY_NAME`; if omitted, the first admin defaults to username `admin`.

## TrackNet / YOLO Notes

- TrackNet needs weights and runtime support
- YOLO can run through a local ONNX / PT model and the repository already includes a checked-in `yolov8n.onnx` baseline asset for current flows
- the bootstrap and doctor commands above are the quickest way to check readiness on a new device
- current CV support should be read as assistive and development-stage, not fully automatic production annotation
- real match videos are still the main requirement for confidence tuning, threshold adjustment, and practical validation
- base backend requirements are intentionally CI-safe; GPU-specific runtime pieces should be added through setup scripts or targeted machine prep rather than assumed in every environment

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

Recent CI hardening:

- base backend install no longer assumes `onnxruntime-gpu` in generic CI environments
- benchmark tests now respect explicit mock mode and avoid spurious `ffmpeg`-driven failures
- backend pipeline mock loading is aligned with the benchmark / smoke test path

## Local Data

- current development configuration points `DATABASE_URL` to local PostgreSQL by default
- SQLite is still available as a fallback / legacy local mode for some setups and older data
- `shuttlescope/.env.development` is the practical source of truth for the active local DB target
- `private_docs/` is ignored
- `shuttlescope/docs/validation/` is committed and used as implementation / verification history
- local DBs, DB backups, videos, CV weights, and generated artifacts are not committed

## Current Status

ShuttleScope is already useful as an internal badminton analysis tool.
Its strongest areas today are:

- annotation flow
- review and dashboard structure
- badminton-specific analysis
- local setup / bootstrap / doctor support
- local video and ROI-based CV batch workflow
- cluster / benchmark groundwork for multi-machine inference experiments

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
