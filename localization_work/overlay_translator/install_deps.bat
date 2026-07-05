@echo off
cd /d "%~dp0"
echo ========================================
echo  Install dependencies (step by step)
echo ========================================
echo.

REM Step 1: core (small, always needed)
echo [1/3] Core packages...
py -3 -m pip install mss pillow opencv-python-headless pywin32 numpy translators "rapidocr-onnxruntime==1.2.3" deep-translator
if errorlevel 1 goto fail

REM Step 2: scipy alone (often fails when bundled with large downloads)
echo.
echo [2/3] scipy (Korean OCR dependency)...
py -3 -m pip install scipy --no-cache-dir
if errorlevel 1 (
  echo.
  echo scipy failed. Close antivirus real-time scan briefly, then run this bat again.
  goto fail
)

REM Step 3: easyocr + torch (large, may take 30+ min)
echo.
echo [3/3] EasyOCR + PyTorch (~130MB, please wait)...
py -3 -m pip install easyocr --no-cache-dir
if errorlevel 1 goto fail

echo.
echo ========================================
echo  All dependencies installed OK
echo ========================================
pause
exit /b 0

:fail
echo.
echo [ERROR] Install failed. Tips:
echo   1. Close other cmd windows running pip
echo   2. Temporarily disable antivirus, run this bat again
echo   3. Or run manually:
echo      py -3 -m pip install scipy --no-cache-dir
echo      py -3 -m pip install easyocr --no-cache-dir
pause
exit /b 1
