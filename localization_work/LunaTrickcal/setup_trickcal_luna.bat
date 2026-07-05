@echo off
setlocal
cd /d "%~dp0"
echo === Build Trickcal Luna runtime ===
py -3 apply_patches.py
if errorlevel 1 goto fail
echo.
echo === Sync Trickcal glossary (optional) ===
py -3 ..\luna_integration\export_luna_glossary.py
py -3 ..\luna_integration\apply_luna_trickcal.py --luna-root "%~dp0runtime"
echo.
echo Done. Run start_trickcal_luna.bat
pause
exit /b 0
:fail
pause
exit /b 1
