@echo off
cd /d "%~dp0"
python apply_test_chests.py
if errorlevel 1 pause
echo.
echo 下一步：用 Smithbox 导入 output\TEST_CHESTS_ItemLotParam_map.csv 到 mod\regulation.bin
echo 详见 output\TEST_CHESTS_说明.txt
pause
