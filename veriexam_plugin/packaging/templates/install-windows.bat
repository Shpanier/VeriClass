@echo off
REM VeriExam - exam client installer (Windows). Double-click this file.
REM It just runs install-windows.ps1 with the right execution policy.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-windows.ps1"
