@echo off
cd /d "%~dp0"
if not exist backend\.venv\Scripts\python.exe python -m venv backend\.venv
if errorlevel 1 exit /b 1
backend\.venv\Scripts\python -m pip install -r backend\requirements.txt
if errorlevel 1 exit /b 1
cd frontend
call npm ci
if errorlevel 1 exit /b 1
cd ..
echo Setup complete. Run start.bat.
