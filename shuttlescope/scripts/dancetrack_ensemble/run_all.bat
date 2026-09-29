@echo off
REM Full DanceTrack val: run all baselines + ensemble variants, then eval.
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
set PY="C:\Users\kiyus\Desktop\github\shuttle-scope\shuttlescope\backend\.venv\Scripts\python.exe"
set S=C:\Users\kiyus\Desktop\dancetrack\eval\scripts
set TRK=C:\Users\kiyus\Desktop\dancetrack\eval\trackers
set LOG=C:\Users\kiyus\Desktop\dancetrack\eval\logs\runall.log

echo === RUN BASELINES === > %LOG%
%PY% -u %S%\run_tracker.py --tracker bytetrack --name bytetrack >> %LOG% 2>&1
%PY% -u %S%\run_tracker.py --tracker ocsort   --name ocsort    >> %LOG% 2>&1
%PY% -u %S%\run_tracker.py --tracker hybrid   --name hybrid    >> %LOG% 2>&1

echo === ENSEMBLE POST-LAYERS (on hybrid base) === >> %LOG%
REM WINNING ensemble = hybrid base + offline stitch ONLY (swap-guard ablated: it hurt).
%PY% -u %S%\postprocess.py --in %TRK%\hybrid\data --out %TRK%\ensemble\data --no-swap >> %LOG% 2>&1
REM Ablations (diagnostic): swap-only, swap+stitch, and stitch on OC base.
%PY% -u %S%\postprocess.py --in %TRK%\hybrid\data --out %TRK%\ensemble_swaponly\data --no-stitch >> %LOG% 2>&1
%PY% -u %S%\postprocess.py --in %TRK%\hybrid\data --out %TRK%\ensemble_swapstitch\data >> %LOG% 2>&1
%PY% -u %S%\postprocess.py --in %TRK%\ocsort\data --out %TRK%\oc_ensemble\data --no-swap >> %LOG% 2>&1

echo === EVAL ALL === >> %LOG%
%PY% -u %S%\eval_trackeval.py --trackers bytetrack,ocsort,hybrid,ensemble,ensemble_swaponly,ensemble_swapstitch,oc_ensemble >> %LOG% 2>&1
echo ALLDONE >> %LOG%
