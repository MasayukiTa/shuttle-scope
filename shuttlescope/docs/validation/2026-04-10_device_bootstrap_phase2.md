# ShuttleScope Device Bootstrap Phase 2

## Date
2026-04-10

## Goal
Make new-device setup more practical without touching remote CV runtime work already in progress.

## Implemented

### 1. Setup doctor now has recommendations and exit codes
`backend/tools/setup_doctor.py` was extended with:

- `build_report()`
- `build_recommendations()`
- `compute_exit_code()`
- `summarize_report()`

New CLI behavior:

```powershell
.\backend\.venv\Scripts\python -m backend.tools.setup_doctor
.\backend\.venv\Scripts\python -m backend.tools.setup_doctor --format json
.\backend\.venv\Scripts\python -m backend.tools.setup_doctor --strict
```

Meaning:

- `text` mode is friendlier for manual setup
- `json` mode is better for automation / debugging
- `--strict` upgrades optional gaps to blocking failures

Exit code policy:

- `0` ready
- `1` warnings only
- `2` blocked

### 2. Batch bootstrap wrapper
Added `shuttlescope/bootstrap_windows.bat` as a thin wrapper around
`bootstrap_windows.ps1`, so a Windows user can still start from batch if needed.

### 3. README onboarding update
`README.md` now documents:

- PowerShell bootstrap
- batch wrapper bootstrap
- doctor text/json/strict modes
- recommendation / exit code behavior

### 4. Tests for doctor logic
Added `backend/tests/test_setup_doctor.py` to validate:

- recommendation generation
- warning vs blocking exit code behavior
- strict mode behavior
- summary output

## Verified

### Build

```text
npm run build
=> success
```

### Frontend tests

```text
npx vitest run --config vitest.config.ts
=> 84 passed
```

### Backend tests

```text
python -m pytest backend/tests/test_setup_doctor.py -q
=> 5 passed
```

### Doctor runtime

Current machine result:

- text mode prints human-readable readiness summary
- JSON mode prints structured report plus `recommendations` and `exit_code`
- current exit code is `1`
  - because `ngrok` is missing in PATH
  - and YOLO weights are not ready yet

This is correct behavior for a machine that can run the app but is not fully ready for every optional flow.

## Notes

- This phase intentionally did not touch in-progress TrackNet / Electron runtime edits already sitting in the worktree.
- Model distribution is still unresolved; this phase improves guidance, not artifact shipping.
