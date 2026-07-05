@echo off
cd /d "%~dp0"
echo ========================================
echo  Install PaddlePaddle GPU (CUDA 11.8)
echo ========================================
echo.
echo IMPORTANT: Use cu118 wheel (NOT cu126).
echo cu126 conflicts with PyTorch cu124 on Windows.
echo.

py -3 -m pip uninstall -y paddlepaddle paddlepaddle-gpu
if errorlevel 1 goto fail

echo.
echo Removing conflicting CUDA 12 helper packages...
py -3 -m pip uninstall -y nvidia-cublas-cu12 nvidia-cuda-runtime-cu12 nvidia-cudnn-cu12 nvidia-cufft-cu12 nvidia-curand-cu12 nvidia-cusolver-cu12 nvidia-cusparse-cu12 nvidia-nvjitlink-cu12 2>nul

echo.
echo Installing paddlepaddle-gpu cu118...
py -3 -m pip install paddlepaddle-gpu==3.3.0 -i https://www.paddlepaddle.org.cn/packages/stable/cu118/
if errorlevel 1 goto fail

echo.
echo Verifying CUDA...
py -3 -c "import os,sys; from pathlib import Path; sp=Path(sys.executable).resolve().parent/'Lib'/'site-packages'/'nvidia'; [os.add_dll_directory(str(p/'bin')) for p in sp.iterdir() if (p/'bin').is_dir()]; import paddle; print('paddle', paddle.__version__, 'cuda', paddle.is_compiled_with_cuda()); assert paddle.is_compiled_with_cuda()"
if errorlevel 1 goto fail

echo.
echo Testing PaddleOCR on GPU...
py -3 -c "import os,sys; from pathlib import Path; os.environ.setdefault('FLAGS_use_mkldnn','0'); sp=Path(sys.executable).resolve().parent/'Lib'/'site-packages'/'nvidia'; [os.add_dll_directory(str(p/'bin')) for p in sp.iterdir() if (p/'bin').is_dir()]; import torch; import numpy as np; from paddleocr import PaddleOCR; o=PaddleOCR(lang='korean', enable_mkldnn=False, device='gpu:0', use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=False); list(o.predict(np.full((64,128,3),255,dtype=np.uint8))); print('PaddleOCR GPU OK')"
if errorlevel 1 goto fail

echo.
echo ========================================
echo  Paddle GPU installed. Restart start.bat
echo ========================================
pause
exit /b 0

:fail
echo.
echo [ERROR] Install failed.
echo If DLL error persists, install: Microsoft Visual C++ 2015-2022 Redistributable (x64)
pause
exit /b 1
