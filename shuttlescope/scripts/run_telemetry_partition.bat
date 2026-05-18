@echo off
REM Windows Scheduled Task wrapper for monthly telemetry partition creation.
REM Register with:
REM   schtasks /Create /TN ShuttleScope-TelemetryPartition /TR "C:\path\to\run_telemetry_partition.bat" /SC MONTHLY /D 25 /ST 03:00 /RU SYSTEM /F
set PGHOST=127.0.0.1
set PGPORT=5432
set PGUSER=postgres
set PGPASSWORD=postgres
set PGDATABASE=shuttlescope
"C:\Users\kiyus\Desktop\github\shuttle-scope\shuttlescope\backend\.venv\Scripts\python.exe" "C:\Users\kiyus\Desktop\github\shuttle-scope\shuttlescope\scripts\telemetry_ensure_partition.py" >> "C:\Users\kiyus\Desktop\telemetry_partition.log" 2>&1
exit /b %errorlevel%
