@echo off
setlocal
cd /d "%~dp0.."
echo === Randomizer for all release pack ===
python packaging\stage_release.py %*
if errorlevel 1 exit /b 1
echo.
echo Zip under dist\Randomizer-for-all-1.0.0.zip
echo (dist\ should contain only that zip)
exit /b 0
