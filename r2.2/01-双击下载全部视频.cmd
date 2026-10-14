@echo off
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0DOWNLOAD.ps1"
if errorlevel 1 echo Some videos failed. Please double-click again later.
pause
