@echo off
title Wander editor
:: Wander editor launcher (Windows). Put a copy in a trip folder with
::   python tripmap\launcher.py "<trip folder>"
:: which fills in the WANDER line below with where this repo is. Run straight
:: from the repo, it finds serve.py next to itself; then drop a trip folder on it.
set "WANDER=%~dp0."
set "TRIP=%~1"
if "%TRIP%"=="" set "TRIP=%~dp0."
if not exist "%WANDER%\serve.py" (
  echo Could not find serve.py in %WANDER%
  echo Run: python tripmap\launcher.py "%TRIP%"   from the wander repo to refresh this launcher.
  pause
  exit /b 1
)
python "%WANDER%\serve.py" "%TRIP%"
if errorlevel 1 pause
