@echo off
chcp 65001 >nul
title Xóa tiến trình TikTok LIVE Reporter

echo.
echo ========================================================
echo   Đang dừng và xóa tiến trình TikTok LIVE Reporter...
echo ========================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0uninstall-autostart.ps1"

echo.
echo ========================================================
echo   Đã xóa hoàn toàn tiến trình thành công!
echo ========================================================
echo.
echo Nhấn phím bất kỳ để đóng.
pause >nul
