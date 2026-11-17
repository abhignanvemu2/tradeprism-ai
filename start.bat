@echo off
cd /d "%~dp0"
if not exist backend\.venv\Scripts\python.exe (
 echo Run setup.bat first.
 exit /b 1
)
backend\.venv\Scripts\python run_local.py
