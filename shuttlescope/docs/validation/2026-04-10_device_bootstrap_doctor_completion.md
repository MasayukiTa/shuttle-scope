# ShuttleScope Device Bootstrap / Setup Doctor Completion

## Date
2026-04-10

## Scope
New-device onboarding and environment diagnostics for Windows machines.

Reference:
- `README.md`
- `shuttlescope/bootstrap_windows.ps1`
- `shuttlescope/backend/tools/setup_doctor.py`
- `shuttlescope/backend/setup_venv.bat`

## Implemented

### 1. One-command Windows bootstrap
Added `shuttlescope/bootstrap_windows.ps1` with optional flags:

- `-IncludeYolo`
- `-SetupTrackNet`
- `-RunDoctor`

What it does:

- verifies `python` and `npm`
- creates `backend/.venv` if missing
- upgrades `pip`
- installs backend requirements
- optionally installs `ultralytics`
- installs frontend dependencies with `npm install`
- optionally runs `backend.tracknet.setup all`
- optionally runs the environment doctor

### 2. Environment doctor
Added `shuttlescope/backend/tools/setup_doctor.py` and package marker
`shuttlescope/backend/tools/__init__.py`.

Command:

```powershell
.\backend\.venv\Scripts\python -m backend.tools.setup_doctor
```

What it reports:

- repo paths
- command availability
  - `python`
  - `npm`
  - `ngrok`
  - `cloudflared`
- important Python package versions
  - `tensorflow`
  - `tf2onnx`
  - `onnxruntime`
  - `opencv-python`
  - `ultralytics`
  - `numpy`
  - `scipy`
- TrackNet readiness
  - weights presence
  - runtime availability
  - loaded backend
  - concrete load error
- YOLO readiness
  - backend
  - status code
  - concrete message
- frontend readiness
  - `node_modules` presence

### 3. Doctor hardening
The doctor no longer assumes TrackNet / YOLO imports always succeed.
Import-time and init-time failures are converted into structured status instead of crashing the diagnostic run.

### 4. README onboarding update
`README.md` now includes:

- fastest new-device bootstrap path
- optional YOLO / TrackNet setup flags
- direct doctor command
- what the doctor output means

### 5. Legacy backend setup script cleanup
Replaced mojibake in `shuttlescope/backend/setup_venv.bat` and aligned wording with the new bootstrap flow.

## Local Verification

### Build

```text
3014 modules transformed
built successfully
```

### Frontend tests

```text
7 files passed
84 tests passed
```

### Backend tests

```text
464 passed, 1 warning
```

### Doctor output summary on current machine

- `python`: found
- `npm`: found
- `cloudflared`: found
- `ngrok`: not found in PATH
- TrackNet: weights present, loaded, backend=`onnx_cpu`
- YOLO: runtime available through `ultralytics`, weights still missing until first download or local model placement
- frontend `node_modules`: present

## Notes

- This phase improves reproducibility on another PC, but does not yet solve large model distribution by itself.
- `private_docs/` remains ignored.
- `docs/validation/` is ignored by default and must be force-added when committed.
