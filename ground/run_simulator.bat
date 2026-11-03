@echo off
REM Publish simulated packets (with fault tests) so the hosted dashboard shows live data without hardware.
cd /d "%~dp0"
py -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
py mqtt_publisher.py --simulate --faults
