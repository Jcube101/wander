@echo off
title Wander editor
:: Put this file in a trip folder (e.g. D:\2026_ Thailand Trip\). It runs the editor
:: straight from the wander repo, so there is only one copy of the code.
set "WANDER=C:\Users\jobjo\Github\wander\tripmap"
if not exist "%WANDER%\serve.py" (
  echo Could not find %WANDER%\serve.py
  echo Edit the WANDER line in this file to point at your wander\tripmap folder.
  pause
  exit /b 1
)
python "%WANDER%\serve.py" "%~dp0."
if errorlevel 1 pause
