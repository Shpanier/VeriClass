@echo off
rem Start VeriClass on Windows: double-click this file.
rem
rem The first start installs what VeriClass needs into this folder (Python
rem included, through the tool "uv"); later starts take a few seconds. Then the
rem lecturer's dashboard opens in the browser.
rem
rem   start.bat --port 8020     another port (default 8010)
rem   start.bat --lan           also reachable from the local network
rem   start.bat --no-browser    don't open the browser
setlocal
cd /d "%~dp0"
rem Exercises are written in UTF-8 (Hebrew too); Windows defaults to an older encoding.
set PYTHONUTF8=1
set "PATH=%USERPROFILE%\.local\bin;%PATH%"

where uv >nul 2>nul
if errorlevel 1 (
  echo ==^> Installing uv ^(it installs Python and the packages VeriClass needs^)...
  powershell -NoProfile -ExecutionPolicy ByPass -Command "irm https://astral.sh/uv/install.ps1 | iex"
)
where uv >nul 2>nul
if errorlevel 1 (
  echo.
  echo uv was installed but this window doesn't see it yet. Close this window and double-click start.bat again.
  pause
  exit /b 1
)

if not exist .venv (
  echo ==^> First start: downloading the packages ^(about 350 MB, a few minutes^)...
)
uv run --frozen python -m backend.cli %*
if errorlevel 1 (
  echo.
  echo VeriClass stopped with an error ^(see above^).
  pause
)
endlocal
