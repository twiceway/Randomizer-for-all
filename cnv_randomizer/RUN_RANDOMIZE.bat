@echo off
setlocal
cd /d "%~dp0"

echo ========================================
echo  CNV map randomizer
echo  ItemLotParam_map: glow / chest / boss
echo  No shop / no enemy drops
echo ========================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo Python not found. Install Python 3 and retry.
    pause
    exit /b 1
)

if not exist "..\..\csv\ItemLotParam_map.csv" (
    echo Missing ..\..\csv\ItemLotParam_map.csv
    echo Export regulation.bin to csv\ first.
    pause
    exit /b 1
)

if not "%~1"=="" (
    echo Using seed %~1
    powershell -NoProfile -Command ^
      "$c = Get-Content config.json | ConvertFrom-Json; $c.seed = [int]('%~1'); $c | ConvertTo-Json -Depth 6 | Set-Content config.json"
)

python randomize_map_lots.py
if errorlevel 1 (
    echo Randomizer failed.
    pause
    exit /b 1
)

echo.
echo Output:
echo   output\ItemLotParam_map.csv
echo   output\ItemLotParam_map.massedit
echo   output\spoiler_*.txt
echo.
echo Next: APPLY_TO_REGULATION.bat
echo If DSMS CLI fails, use Smithbox import (see IMPORT_SMITHBOX.txt)
pause
