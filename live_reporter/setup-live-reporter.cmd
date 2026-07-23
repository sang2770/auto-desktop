@echo off
setlocal
cd /d "%~dp0.."
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-autostart.ps1"
if errorlevel 1 (
  echo.
  echo Cai dat that bai. Nhan phim bat ky de dong.
  pause >nul
  exit /b 1
)
echo.
echo Cai dat hoan tat. Nhan phim bat ky de dong.
pause >nul
