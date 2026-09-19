@echo off

setlocal

cd /d "%~dp0"

echo === m60 关卡前方 · 全换辫毛流浪狗（c5525 / npc 55250095）真机探针 ===

python _probe_m60_gatefront_dog.py %*

if errorlevel 1 exit /b 1

echo.

echo 完成。请完全退出游戏后重进「关卡前方」赐福；重点看两辆宝箱马车旁是否全是长毛狗。

endlocal

