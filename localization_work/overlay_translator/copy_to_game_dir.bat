@echo off
cd /d "%~dp0"
echo Copy overlay translator to game directory (optional)...
set "TARGET=C:\opaivmplayer\localization_work\overlay_translator"
if not exist "C:\opaivmplayer" (
  echo C:\opaivmplayer not found. Copy overlay_translator folder manually.
  pause
  exit /b 1
)
mkdir "C:\opaivmplayer\localization_work" 2>nul
xcopy /E /I /Y "%~dp0" "%TARGET%"
echo.
echo Copied to: %TARGET%
echo Run start.bat from that folder next time.
pause
