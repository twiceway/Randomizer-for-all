@echo off
setlocal
chcp 65001 >nul 2>&1
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
cd /d "%~dp0"
echo [T-084 R1] REEXPORT_DONOR — steps 2-5

python _export_donor_msb_state.py
if errorlevel 1 exit /b 1

python _export_bundle_catalog.py
if errorlevel 1 exit /b 1

python _export_slot_tags.py
if errorlevel 1 exit /b 1

python _export_bundle_slot_compat.py
if errorlevel 1 exit /b 1

python build_enemy_slot_density.py
if errorlevel 1 exit /b 1

python enemy_randomizer_core.py prep
if errorlevel 1 exit /b 1

echo [T-084 R1] REEXPORT_DONOR done.
exit /b 0
