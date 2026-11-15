@echo off
setlocal
where node >nul 2>nul
if errorlevel 1 (
  echo Install Node.js 22.12+ or 24+ ^(including npm^), then run this script again.
  exit /b 1
)
if not "%~2"=="" (
  echo Usage: start.cmd java ^| python
  exit /b 1
)
node "%~dp0scripts\start.cjs" "%~1"
exit /b %errorlevel%
