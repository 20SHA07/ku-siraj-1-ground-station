@echo off
REM Forward ESP32 USB serial packets to MQTT so the hosted dashboard updates live.
REM Usage: run_mqtt.bat COM5
if "%~1"=="" (
  echo Usage: run_mqtt.bat COM5
  echo Replace COM5 with the ESP32 port shown in Device Manager.
  pause
  exit /b 1
)
cd /d "%~dp0"
py -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
py mqtt_publisher.py --serial %~1
