@echo off
setlocal
cd /d "%~dp0cnv_pickup_hook"

set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
for /f "usebackq delims=" %%i in (`"%VSWHERE%" -latest -products * -requires Microsoft.Component.MSBuild -property installationPath`) do set "VSROOT=%%i"
if not defined VSROOT (
    echo Visual Studio not found.
    exit /b 1
)

call "%VSROOT%\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 exit /b 1

msbuild cnv_pickup_hook.vcxproj /p:Configuration=Release /p:Platform=x64 /m
if errorlevel 1 exit /b 1

echo.
echo Built: %~dp0..\bin\cnv_pickup_hook.dll
echo Run tools\DEPLOY.bat to copy into Game\mod\dll\
exit /b 0
pause
