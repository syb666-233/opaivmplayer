@echo off
cd /d "%~dp0"
echo ========================================
echo  Install PyTorch with CUDA (GPU)
echo ========================================
echo.
echo This replaces CPU-only torch so EasyOCR can use your GPU.
echo Requires NVIDIA GPU + up-to-date driver.
echo Download size ~2.5GB, please wait...
echo.
py -3 -m pip uninstall torch torchvision -y
py -3 -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124
if errorlevel 1 (
  echo.
  echo [ERROR] CUDA torch install failed.
  echo Try cu121: py -3 -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
  pause
  exit /b 1
)
echo.
py -3 -c "import torch; print('torch', torch.__version__); print('cuda available:', torch.cuda.is_available()); print('gpu:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'N/A')"
echo.
echo Done. Restart start.bat to use GPU.
pause
