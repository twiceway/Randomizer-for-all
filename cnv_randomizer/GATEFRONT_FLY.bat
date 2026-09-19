@echo off
cd /d "%~dp0"
python gatefront_test_lab.py fly-table
python gatefront_test_lab.py apply-fly --batch 1
pause
