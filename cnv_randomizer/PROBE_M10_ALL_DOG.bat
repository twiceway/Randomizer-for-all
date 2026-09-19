@echo off
setlocal
cd /d "%~dp0"
echo === m10 城堡内 · 全换辫毛流浪狗（c5525 / npc 55250095）真机探针 ===
python _probe_m10_all_dog.py %*
if errorlevel 1 exit /b 1
echo.
echo 完成。请完全退出游戏后重进关卡前方；重点看两辆宝箱马车旁是否全是长毛狗。
endlocal
