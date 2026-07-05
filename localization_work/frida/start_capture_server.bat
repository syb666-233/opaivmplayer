@echo off
cd /d "%~dp0"
echo Starting capture server on port 8787...
py -3 capture_server.py
pause
