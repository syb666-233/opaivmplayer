@echo off
cd /d "%~dp0"
echo ========================================
echo  Install PaddleOCR (optional, Korean)
echo ========================================
echo.
echo Paddle 3.3.x on CPU needs enable_mkldnn=False (already set in code).
echo First run will download models to %%USERPROFILE%%\.paddlex\
echo.

py -3 -m pip install "paddlepaddle>=3.2.2" paddleocr
if errorlevel 1 goto fail

echo.
echo Testing PaddleOCR warmup...
py -3 -c "import os; os.environ.setdefault('FLAGS_use_mkldnn','0'); import numpy as np; from paddleocr import PaddleOCR; o=list(PaddleOCR(lang='korean', enable_mkldnn=False).predict(np.full((64,128,3),255,dtype=np.uint8))); print('PaddleOCR OK')"
if errorlevel 1 goto fail

echo.
echo ========================================
echo  PaddleOCR installed and verified
echo ========================================
pause
exit /b 0

:fail
echo.
echo [ERROR] Paddle install or warmup failed.
echo Try: py -3 -m pip install paddlepaddle==3.2.2 paddleocr
pause
exit /b 1
