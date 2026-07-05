@echo off
setlocal
pushd "%~dp0\.."
echo [1] merge external contributions...
py -3 LunaTrickcal\scripts\merge_external_dict.py
echo [2] build ko_zh_pairs from Frida capture...
cd overlay_translator
py -3 build_ko_zh_pairs.py
if errorlevel 1 goto fail
cd ..\luna_integration
echo [3] export Luna glossary...
py -3 export_luna_glossary.py
echo [4] apply to LunaTrickcal runtime...
py -3 apply_luna_trickcal.py --luna-root "%~dp0..\LunaTrickcal\runtime" --json-log
echo Done.
popd
if /i not "%~1"=="nopause" pause
exit /b 0
:fail
popd
if /i not "%~1"=="nopause" pause
exit /b 1
