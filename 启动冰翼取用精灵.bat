@echo off
setlocal
cd /d "%~dp0"
set "PY_EXE="
set "PY_ARGS="
if exist ".venv\Scripts\python.exe" set "PY_EXE=%~dp0.venv\Scripts\python.exe"
if not defined PY_EXE (
  where py >nul 2>nul
  if not errorlevel 1 (
    set "PY_EXE=py"
    set "PY_ARGS=-3"
  )
)
if not defined PY_EXE (
  where python >nul 2>nul
  if not errorlevel 1 set "PY_EXE=python"
)
if not defined PY_EXE (
  echo Python 3 was not found. Install Python 3.11 or newer.
  pause
  exit /b 1
)
"%PY_EXE%" %PY_ARGS% desktop_pet.py %* > pet-debug.log 2>&1
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo Companion startup failed. See pet-debug.log.
  type pet-debug.log
  pause
)
exit /b %RC%
