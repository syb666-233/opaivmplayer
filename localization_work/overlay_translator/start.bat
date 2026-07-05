@echo off
cd /d "%~dp0"
echo ========================================
echo  Trickcal Overlay Translator v1.0
echo ========================================
echo.
py -3 -c "import sys; print('Python', sys.version.split()[0])"
echo.

REM Quick check: EasyOCR models (download separately if missing)
py -3 -c "import sys; sys.path.insert(0, r'%~dp0'); from download_models import models_ready; sys.exit(0 if models_ready() else 1)" 2>nul
if errorlevel 1 (
  echo EasyOCR models not found. Downloading via mirror...
  echo.
  py -3 download_models.py
  if errorlevel 1 (
    echo.
    echo Run download_models.bat manually, then start.bat again.
    pause
    exit /b 1
  )
)

py -3 -c "import easyocr" 2>nul
if errorlevel 1 (
  echo EasyOCR not installed. Run install_deps.bat first.
  pause
  exit /b 1
)

echo Dependencies OK.

echo.
echo Starting translator...
py -3 -u overlay_translator.py --window "trickcal" --interval 5.0 --engine bing
pause
