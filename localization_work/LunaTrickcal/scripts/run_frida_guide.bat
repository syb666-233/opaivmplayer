@echo off
rem Frida 韩文抓取 — 快速启动指南
rem 需要: adb、frida、frida-server（版本一致）
echo.
echo === Trickcal Frida 韩文抓取 ===
echo.
echo [步骤 1] 在本窗口启动抓取服务:
echo   cd /d "%~dp0..\..\frida"
echo   start_capture_server.bat
echo.
echo [步骤 2] 新终端 — 连接 AIVM adb:
echo   adb connect 127.0.0.1:8555
echo   adb forward tcp:8787 tcp:8787
echo.
echo [步骤 3] 注入 Frida（游戏未开时用 -f）:
echo   frida -U -f com.epidgames.trickcalrevive -l hook_capture_ko.js --no-pause
echo   或 attach: frida -U com.epidgames.trickcalrevive -l hook_capture_ko.js
echo.
echo [步骤 4] 在游戏内浏览 UI / 剧情，抓取写入:
echo   localization_work\frida\ko_captured.jsonl
echo.
echo [步骤 5] 同步到 Luna:
echo   cd /d "%~dp0.."
echo   sync_dict_and_patch.bat
echo.
echo 详细日志: logs\sync_log.json
echo.
pause
