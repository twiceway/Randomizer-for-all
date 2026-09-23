@echo off
setlocal
cd /d "%~dp0.."
echo === Randomizer for all release pack ===
echo Default: --mode both  (exe zip + scripts zip)
echo Examples:
echo   packaging\pack_release.bat
echo   packaging\pack_release.bat --mode scripts --skip-prep --skip-dotnet
echo   packaging\pack_release.bat --mode exe --skip-pyinstaller
python packaging\stage_release.py %*
if errorlevel 1 exit /b 1
echo.
echo Zips under dist\
echo   Randomizer-for-all-1.0.1.zip
echo   Randomizer-for-all-1.0.1-scripts.zip
echo (dist\ should contain only the finished zip(s) for the mode you chose)
exit /b 0
