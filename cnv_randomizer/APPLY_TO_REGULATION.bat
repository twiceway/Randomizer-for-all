@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

set SEED=
if not "%~1"=="" set SEED=%~1

echo ========================================
echo  CNV map randomizer - apply to regulation.bin
echo  Scope: ItemLotParam_map only
echo  Ground glow / chest / boss drops
echo  No shop / no enemy drops
echo ========================================
echo.

if not exist "..\..\mod\regulation.bin" (
    echo Missing mod\regulation.bin
    pause
    exit /b 1
)

if not exist "output\ItemLotParam_map.massedit" (
    echo output\ItemLotParam_map.massedit not found. Run RUN_RANDOMIZE.bat first.
    pause
    exit /b 1
)

if "%SEED%"=="" (
    for /f "usebackq delims=" %%S in (`powershell -NoProfile -Command "(Get-Content config.json | ConvertFrom-Json).seed"`) do set SEED=%%S
)

echo Backing up mod\regulation.bin ...
copy /Y "..\..\mod\regulation.bin" "..\..\mod\regulation.bin.pre_cnv_rand_%SEED%.bak" >nul

echo Merging massedit patch into regulation.bin ...
cd /d "%~dp0..\DSMSPortable"
if not exist "DSMSPortable.exe" (
    echo DSMSPortable.exe not found
    pause
    exit /b 1
)

set "GAMEPATH=%~dp0..\..\"
set "OUTBIN=%~dp0..\..\mod\regulation.bin"
set "PATCH=%~dp0output\ItemLotParam_map.massedit"

DSMSPortable.exe "%OUTBIN%" -G ER -P "%GAMEPATH%" -M "%PATCH%" -O "%OUTBIN%.tmp"
if errorlevel 1 (
    echo DSMS merge failed.
    pause
    exit /b 1
)

move /Y "%OUTBIN%.tmp" "%OUTBIN%" >nul
if exist "%OUTBIN%.prev" del "%OUTBIN%.prev" >nul 2>&1

echo.
echo Done. regulation.bin updated (seed %SEED%).
echo Backup: mod\regulation.bin.pre_cnv_rand_%SEED%.bak
echo Spoiler: cnv_randomizer\output\runtime\spoiler_%SEED%_*.txt
echo.
echo Use a NEW CNV save slot to test.
pause
