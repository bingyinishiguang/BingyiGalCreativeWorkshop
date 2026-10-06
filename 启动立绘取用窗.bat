@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" floating_picker.py
  exit /b 0
)
where pyw >nul 2>nul
if not errorlevel 1 (
  start "" pyw -3 floating_picker.py
  exit /b 0
)
where pythonw >nul 2>nul
if not errorlevel 1 (
  start "" pythonw floating_picker.py
  exit /b 0
)
echo Python 3 was not found. Install Python and the dependencies in requirements.txt.
pause
exit /b 1
