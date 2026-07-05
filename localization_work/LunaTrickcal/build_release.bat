@echo off
cd /d "%~dp0"
echo === LunaTrickcal Release Build ===
py -3 scripts\build_release.py %*
if errorlevel 1 pause
exit /b %ERRORLEVEL%
