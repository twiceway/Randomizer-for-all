@echo off
chcp 65001 >nul
set "SB=V:\games\Smithbox-2-2-3-2026-06-26-a\Smithbox.exe"
set "GUIDE=%~dp0SMITHBOX_223_STEP_BY_STEP.txt"

if not exist "%SB%" (
    echo [错误] 找不到 Smithbox:
    echo   %SB%
    pause
    exit /b 1
)

if not exist "V:\games\Elden Ring\Game\mod\regulation.bin" (
    echo [警告] mod\regulation.bin 不存在，请先恢复法魂 bin。
    pause
)

start "" notepad "%GUIDE%"
start "" "%SB%"
echo.
echo 已打开 Smithbox 和中文步骤说明。
echo 按说明：Create Project -^> Project Directory 选 Game\mod
echo.
pause
