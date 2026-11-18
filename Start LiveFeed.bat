@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" -m livefeed
  exit /b 0
)
if exist ".venv\Scripts\python.exe" (
  start "" ".venv\Scripts\python.exe" -m livefeed
  exit /b 0
)

where pythonw >nul 2>&1
if %errorlevel%==0 (
  start "" pythonw -m livefeed
  exit /b 0
)

where pyw >nul 2>&1
if %errorlevel%==0 (
  start "" pyw -3 -m livefeed
  exit /b 0
)

where py >nul 2>&1
if %errorlevel%==0 (
  start "" py -3 -m livefeed
  exit /b 0
)

where python >nul 2>&1
if %errorlevel%==0 (
  start "" python -m livefeed
  exit /b 0
)

echo Could not find Python. Install Python 3.11+ and try again.
pause
exit /b 1
