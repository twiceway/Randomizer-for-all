@echo off
setlocal
cd /d "%~dp0"
echo === m60 关卡前方 · 一槽一狗认编号探针 ===
python _probe_m60_dog_id_lineup.py %*
if errorlevel 1 exit /b 1
echo.
echo 完成。请完全退出游戏后重进「关卡前方」，到两辆宝箱马车旁锁 9 只狗看编号。
echo 图例见 output\runtime\_m60_dog_id_lineup_probe\dog_id_lineup_legend.txt
endlocal
