@echo off
setlocal
cd /d "%~dp0.."
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-autostart.ps1"
if errorlevel 1 (
  echo.
  echo ============================================================
  echo CAI DAT THAT BAI - CHI TIET:
  echo ============================================================
  if exist "%~dp0install-live-reporter.log" (
    type "%~dp0install-live-reporter.log"
  ) else (
    echo Khong tao duoc file log cai dat.
  )
  echo.
  echo Log: "%~dp0install-live-reporter.log"
  echo Nhan phim bat ky de dong.
  pause >nul
  exit /b 1
)
echo.
echo Cai dat hoan tat. Nhan phim bat ky de dong.
pause >nul
