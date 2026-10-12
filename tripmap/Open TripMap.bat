@echo off
title TripMap
cd /d "%~dp0"
python serve.py "%~dp0.."
if errorlevel 1 pause
