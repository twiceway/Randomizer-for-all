@echo off
setlocal
cd /d "%~dp0"
if "%~1"=="" (
  echo === 关卡前方试验台 ===
  echo   fix-ruins-blockers  清电球/锁不上干扰槽
  echo   apply-quad-dogs     四足认狗 batch 1
  echo   dog-list            列流浪狗
  python gatefront_test_lab.py fix-ruins-blockers
  exit /b %errorlevel%
)
python gatefront_test_lab.py %*
exit /b %errorlevel%
