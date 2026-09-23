@echo off
setlocal
cd /d "%~dp0"
python gatefront_test_lab_gui.py
exit /b %errorlevel%
