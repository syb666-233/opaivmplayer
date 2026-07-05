@echo off
setlocal
cd /d "%~dp0"
echo === Trickcal data -^> LunaTranslator ===
py -3 export_luna_glossary.py
if errorlevel 1 goto fail
py -3 apply_luna_trickcal.py
if errorlevel 1 goto fail
echo.
echo Done. Run start_luna_trickcal.bat to launch Luna.
pause
exit /b 0
:fail
pause
exit /b 1
