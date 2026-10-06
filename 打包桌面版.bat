@echo off
setlocal
title Bingyi Gal Creative Workshop - Build Desktop App
cd /d "%~dp0"

echo ============================================================
echo   Bingyi Gal Creative Workshop - Build desktop app (PyInstaller)
echo   Output: dist\BingyiGalCreativeWorkshop\BingyiGalCreativeWorkshop.exe
echo ============================================================
echo.

set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
"%PY%" --version >nul 2>&1
if errorlevel 1 goto :nopython

echo [1/5] Installing build dependencies (pyinstaller, pywebview) ...
echo       Using China mirror first, fallback to Aliyun if needed.
"%PY%" -m pip install --upgrade --index-url https://pypi.tuna.tsinghua.edu.cn/simple --default-timeout=120 --retries 10 pyinstaller pywebview
if errorlevel 1 (
  echo Tsinghua mirror failed, trying Aliyun mirror ...
  "%PY%" -m pip install --upgrade --index-url https://mirrors.aliyun.com/pypi/simple/ --default-timeout=120 --retries 10 pyinstaller pywebview
)
if errorlevel 1 (
  echo Mirrors failed, trying official PyPI with long timeout ...
  "%PY%" -m pip install --upgrade --default-timeout=180 --retries 15 pyinstaller pywebview
)
if errorlevel 1 goto :fail

echo [2/5] Building brand assets (avatar / signature / icon) ...
"%PY%" tools\build_brand_assets.py

echo [3/5] Cleaning old build output ...
if exist build rmdir /s /q build
if exist "dist\BingyiGalCreativeWorkshop" rmdir /s /q "dist\BingyiGalCreativeWorkshop"

echo [4/5] Running PyInstaller (this takes a few minutes) ...
"%PY%" -m PyInstaller --noconfirm --clean BingyiGalCreativeWorkshop.spec
if errorlevel 1 goto :fail

echo [5/5] Verifying output ...
if not exist "dist\BingyiGalCreativeWorkshop\BingyiGalCreativeWorkshop.exe" goto :noexe
echo.
echo ------------------------------------------------------------
echo  SUCCESS: dist\BingyiGalCreativeWorkshop\BingyiGalCreativeWorkshop.exe
echo  Double-click the exe to start the desktop app.
echo  In frozen mode, user data lives under APPDATA (not next
echo  to the exe), so uninstalling never deletes your data.
echo ------------------------------------------------------------
echo.
pause
exit /b 0

:nopython
echo [ERROR] Python not found. Create .venv first or install Python 3.11+.
goto :endfail
:noexe
echo [ERROR] Build finished but the exe is missing. Check the log above.
goto :endfail
:fail
echo [ERROR] A build step failed. See the messages above.
:endfail
echo.
pause
exit /b 1
