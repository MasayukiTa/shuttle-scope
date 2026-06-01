@echo off
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
set PY="C:\Users\kiyus\Desktop\github\shuttle-scope\shuttlescope\backend\.venv\Scripts\python.exe"
set S=C:\Users\kiyus\Desktop\dancetrack\eval\scripts
set TRK=C:\Users\kiyus\Desktop\dancetrack\eval\trackers
set LOG=C:\Users\kiyus\Desktop\dancetrack\eval\logs\sweep.log
echo === STITCH SWEEP (hybrid base, no-swap) === > %LOG%

REM A: bigger gap+jump
set PP_STITCH_MAX_GAP=120
set PP_STITCH_MAX_JUMP=250
set PP_STITCH_JUMP_PER_GAP=3.0
%PY% -u %S%\postprocess.py --in %TRK%\hybrid\data --out %TRK%\stitchA\data --no-swap >> %LOG% 2>&1

REM B: even bigger gap, generous jump
set PP_STITCH_MAX_GAP=180
set PP_STITCH_MAX_JUMP=350
set PP_STITCH_JUMP_PER_GAP=4.0
%PY% -u %S%\postprocess.py --in %TRK%\hybrid\data --out %TRK%\stitchB\data --no-swap >> %LOG% 2>&1

REM C: conservative gap, tight jump (precision-leaning)
set PP_STITCH_MAX_GAP=45
set PP_STITCH_MAX_JUMP=120
set PP_STITCH_JUMP_PER_GAP=1.5
%PY% -u %S%\postprocess.py --in %TRK%\hybrid\data --out %TRK%\stitchC\data --no-swap >> %LOG% 2>&1

echo === EVAL SWEEP === >> %LOG%
%PY% -u %S%\eval_trackeval.py --trackers stitchA,stitchB,stitchC >> %LOG% 2>&1
echo SWEEPDONE >> %LOG%
