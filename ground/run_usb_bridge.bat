@echo off
REM USB bridge: ESP32 serial -> local WebSocket. Then pick "USB bridge" on the dashboard.
REM Usage: run_usb_bridge.bat COM5
if "%~1"=="" (
  echo Usage: run_usb_bridge.bat COM5
  pause
  exit /b 1
)
cd /d "%~dp0"
py -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
start "KU-SIRAJ 1 USB bridge" cmd /k py server.py --serial-port "%~1" --baudrate 115200
start "" "https://20sha07.github.io/ku-siraj-1-ground-station/?mode=local"
