@echo off
setlocal
cd /d "%~dp0"
echo === Trickcal dict sync ===
py -3 scripts\sync_trickcal_dict.py
set ERR=%ERRORLEVEL%
if %ERR% neq 0 (
  echo [FAIL] sync_trickcal_dict exit %ERR%
  if /i not "%~1"=="nopause" pause
  exit /b %ERR%
)
echo [OK] Done. Log: logs\sync_log.json
if /i not "%~1"=="nopause" pause
exit /b 0
