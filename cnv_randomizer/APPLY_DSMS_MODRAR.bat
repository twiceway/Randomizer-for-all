@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ========================================
echo  CNV randomizer - DSMSPortable merge
echo  Uses MODRAR\DSMSPortable (no Smithbox)
echo ========================================
echo.

set "GAME=C:\ERGame"
set "DSMS=%~dp0..\..\MODRAR\DSMSPortable\DSMSPortable.exe"
set "BIN=%~dp0..\..\mod\regulation.bin"
set "PATCH=%~dp0output\ItemLotParam_map.massedit"
set "TMP=%~dp0..\..\mod\regulation.bin.dsms.tmp"

if not exist "%DSMS%" (
    echo Missing: MODRAR\DSMSPortable\DSMSPortable.exe
    echo Extract MODRAR\DSMSPortablev1.9.zip first.
    pause
    exit /b 1
)

if not exist "%PATCH%" (
    echo Run RUN_RANDOMIZE.bat first.
    pause
    exit /b 1
)

if not exist "%BIN%" (
    echo Missing mod\regulation.bin
    pause
    exit /b 1
)

if not exist "%GAME%" (
    echo Creating junction C:\ERGame -^> game folder (no spaces for DSMS)...
    mklink /J "C:\ERGame" "%~dp0..\.."
    if errorlevel 1 (
        echo Failed to create C:\ERGame junction. Run as Administrator once.
        pause
        exit /b 1
    )
)

echo Game path for DSMS: %GAME%
for %%F in ("%BIN%") do echo Base bin size: %%~zF bytes
if %%~zF==3136624 (
    echo WARNING: bin is 3.1MB - wrong vanilla-upgraded file.
    echo Restore mod\regulation.bin from backup before merging.
    pause
    exit /b 1
)

echo.
echo Backing up mod\regulation.bin ...
copy /Y "%BIN%" "%BIN%.pre_dsms_merge.bak" >nul

echo Merging massedit patch ...
"%DSMS%" "%BIN%" -G ER -P "%GAME%" -M "%PATCH%" -O "%TMP%"
set ERR=!ERRORLEVEL!
echo DSMSPortable exit code: !ERR!

if not !ERR!==0 (
    echo.
    echo Merge FAILED. Common fixes:
    echo   7 = timeout - copy whole Game folder to C:\local\ER and set GAME= there
    echo   3 = game path wrong - check C:\ERGame exists
    echo   ^<0 = install .NET 6 Desktop Runtime
    if exist "%TMP%" del "%TMP%" >nul 2>&1
    pause
    exit /b 1
)

move /Y "%TMP%" "%BIN%" >nul
for %%F in ("%BIN%") do echo Merged bin size: %%~zF bytes

echo.
echo Done. Start_Convergence_ME3.bat + NEW CNV save to test.
pause
