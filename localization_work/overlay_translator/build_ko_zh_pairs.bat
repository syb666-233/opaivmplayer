@echo off
cd /d "%~dp0"
py -3 build_ko_zh_pairs.py %*
pause
