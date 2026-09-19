@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo === Boss batch 1 ===
dotnet run --project "%~dp0MsbEnemyPoc\MsbEnemyPoc.csproj" -c Release -- restore
if errorlevel 1 goto fail
dotnet run --project "%~dp0MsbEnemyPoc\MsbEnemyPoc.csproj" -c Release --no-build -- boss-batch1 %*
if errorlevel 1 goto fail
echo.
echo [OK] See BOSS_BATCH1_测试说明.txt and boss_batch1_spoiler.txt
pause
exit /b 0

:fail
echo [FAILED]
pause
exit /b 1
