@echo off
setlocal
cd /d "%~dp0"
echo === m60 关卡前方 · 巡逻槽强制封印监牢狼（c3180 / 31800025 / 31800020）===
python _probe_m60_gatefront_wolf.py %*
if errorlevel 1 exit /b 1
echo.
echo 完成。请完全退出游戏后进「关卡前方」；重点看 c4311_9005 是否沿路巡逻不冻。
endlocal
