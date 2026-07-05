@echo off
cd /d "%~dp0"
echo Listing windows matching keyword "trickcal" (game):
py -3 overlay_translator.py --list-windows --window trickcal
echo.
echo Listing windows matching keyword "aivm" (may include false positives):
py -3 overlay_translator.py --list-windows --window aivm
echo.
pause
