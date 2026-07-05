@echo off
cd /d "%~dp0"
echo ========================================
echo  Download EasyOCR Korean models
echo  (first run only, ~80MB total)
echo ========================================
echo.
py -3 download_models.py
if errorlevel 1 (
  echo.
  echo Download failed. Retry this bat or use VPN.
  pause
  exit /b 1
)
echo.
pause
