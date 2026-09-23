@echo off
chcp 65001 >nul
cd /d "%~dp0cnv_randomizer"
python cnv_randomizer_gui.py
if errorlevel 1 pause
