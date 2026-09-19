@echo off
setlocal
cd /d "%~dp0"
echo [T-077] Offline enemy slot table scan...
python scan_enemy_slot_table.py %*
exit /b %ERRORLEVEL%
