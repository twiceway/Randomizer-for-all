@echo off
setlocal
cd /d "%~dp0"
echo === m60 关卡前方 · 马车旁多狗对比真机探针 ===
python _probe_m60_dog_compare.py %*
if errorlevel 1 exit /b 1
echo.
echo 完成。请完全退出游戏后重进「关卡前方」，到两辆宝箱马车旁对比不同狗的外观。
endlocal
