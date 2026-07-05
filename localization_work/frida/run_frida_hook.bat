@echo off
cd /d "%~dp0"
echo ============================================================
echo Trickcal Frida 韩文抓取
echo ============================================================
echo.
echo [1] 先运行 start_capture_server.bat（本机 8787 端口）
echo [2] 连接 AIVM adb，例如: adb connect 127.0.0.1:8555
echo [3] 端口转发: adb forward tcp:8787 tcp:8787
echo [4] 确保 frida-server 在虚拟机内运行且版本匹配 PC 端 frida
echo.
echo 启动游戏并注入（spawn）:
echo   frida -U -f com.epidgames.trickcalrevive -l hook_capture_ko.js --no-pause
echo.
echo 或 attach 已运行进程:
echo   frida -U com.epidgames.trickcalrevive -l hook_capture_ko.js
echo.
echo 游戏内浏览剧情/UI 后，在本机运行:
echo   py -3 ..\overlay_translator\build_ko_zh_pairs.py
echo ============================================================
pause
