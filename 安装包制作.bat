@echo off
setlocal
title Bingyi Gal Creative Workshop - Build Installer (Inno Setup)
cd /d "%~dp0"

echo ============================================================
echo   Bingyi Gal Creative Workshop - Build installer (Inno Setup)
echo   Needs dist\BingyiGalCreativeWorkshop from the desktop build first.
echo ============================================================
echo.

set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"

if not exist "dist\BingyiGalCreativeWorkshop\BingyiGalCreativeWorkshop.exe" goto :noapp

echo [1/3] Generating installer\setup.iss from ui\brand.json ...
"%PY%" tools\build_installer.py
if errorlevel 1 goto :fail

echo [2/3] Locating Inno Setup compiler ISCC.exe ...
set "ISCC="
if defined INNO_SETUP_ISCC if exist "%INNO_SETUP_ISCC%" set "ISCC=%INNO_SETUP_ISCC%"
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not defined ISCC (
  where ISCC.exe >nul 2>nul && set "ISCC=ISCC.exe"
)
if not defined ISCC (
  for /f "tokens=2*" %%a in ('reg query "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1" /v InstallLocation 2^>nul ^| findstr /i "InstallLocation"') do (
    if exist "%%bISCC.exe" set "ISCC=%%bISCC.exe"
  )
)
if not defined ISCC (
  for /f "tokens=2*" %%a in ('reg query "HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1" /v InstallLocation 2^>nul ^| findstr /i "InstallLocation"') do (
    if exist "%%bISCC.exe" set "ISCC=%%bISCC.exe"
  )
)
if not defined ISCC goto :noinno
echo       Found: %ISCC%

echo [3/3] Compiling installer ...
"%ISCC%" installer\setup.iss
if errorlevel 1 goto :fail
echo.
echo ------------------------------------------------------------
echo  SUCCESS: dist\BingyiGalCreativeWorkshop-Setup-1.0.exe
echo  The installer lets the user pick the install folder.
echo  User data stays under APPDATA and is not uninstalled.
echo ------------------------------------------------------------
echo.
pause
exit /b 0

:noapp
echo [ERROR] dist\BingyiGalCreativeWorkshop\BingyiGalCreativeWorkshop.exe not found.
echo         Run the desktop build bat first.
goto :endfail
:noinno
echo [ERROR] Inno Setup 6 not found on this PC.
echo         Install it first:  winget install JRSoftware.InnoSetup
goto :endfail
:fail
echo [ERROR] A step failed. See the messages above.
:endfail
echo.
pause
exit /b 1
