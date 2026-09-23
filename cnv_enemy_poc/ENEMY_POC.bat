@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set MODE=%1
if "%MODE%"=="" set MODE=list

set LOG=%~dp0enemy_poc_last_run.txt
echo === ENEMY_POC %MODE% %DATE% %TIME% === > "%LOG%"

dotnet run --project "%~dp0MsbEnemyPoc\MsbEnemyPoc.csproj" -c Release -- %MODE% %2 %3 %4 >> "%LOG%" 2>&1
set ERR=%ERRORLEVEL%

type "%LOG%"

echo.
if %ERR% NEQ 0 (
    echo [FAILED] exit code %ERR%
    echo See log: %LOG%
) else (
    echo [OK]
)
echo.
pause
exit /b %ERR%
