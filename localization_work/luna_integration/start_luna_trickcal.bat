@echo off
setlocal
pushd "%~dp0\.."
if exist "LunaTranslator_x64\LunaTranslator.exe" (
  start "" "%CD%\LunaTranslator_x64\LunaTranslator.exe"
  popd
  exit /b 0
)
if exist "LunaTranslator\LunaTranslator_x64_win10\LunaTranslator.exe" (
  start "" "%CD%\LunaTranslator\LunaTranslator_x64_win10\LunaTranslator.exe"
  popd
  exit /b 0
)
popd
echo LunaTranslator.exe not found.
echo Extract LunaTranslator_x64_win10.zip into localization_work\
pause
exit /b 1
