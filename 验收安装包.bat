@echo off
setlocal
title Bingyi Gal Creative Workshop - Verify Installer (end to end)
cd /d "%~dp0"

echo ============================================================
echo   Bingyi Gal Creative Workshop - Verify the built installer
echo   Installs silently, launches, clicks the picker, then
echo   uninstalls and cleans up. Nothing is left behind.
echo ============================================================
echo.

set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
"%PY%" --version >nul 2>&1
if errorlevel 1 goto :nopython

if not exist "dist" goto :noinstaller
dir /b "dist\*Setup*.exe" >nul 2>&1
if errorlevel 1 goto :noinstaller

echo Running tools\verify_installer.py ...
echo.
"%PY%" tools\verify_installer.py %*
set "RC=%ERRORLEVEL%"
echo.
if not "%RC%"=="0" goto :failed

echo ------------------------------------------------------------
echo  PASSED - this installer is safe to hand out.
echo  It installed, started, opened the bundled LICENSE, and the
echo  desktop pet (IceWing Companion) came up. Everything was
echo  uninstalled again afterwards.
echo ------------------------------------------------------------
echo.
pause
exit /b 0

:nopython
echo [ERROR] Python not found. Create .venv first or install Python 3.11+.
goto :endfail
:noinstaller
echo [ERROR] No installer found in dist\ so there is nothing to verify.
echo         Run the desktop build bat, then the installer bat, first.
goto :endfail
:failed
echo ------------------------------------------------------------
echo  FAILED - do NOT hand out this installer.
echo  Scroll up for the [FAIL] lines; they name what broke.
echo  Tip: run with  --keep  to keep the test install for a look:
echo       %PY% tools\verify_installer.py --keep
echo ------------------------------------------------------------
:endfail
echo.
pause
exit /b 1
