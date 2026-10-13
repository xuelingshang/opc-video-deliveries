@echo off
chcp 65001 >nul
set /p OPC_DATE=Enter assigned delivery date YYYY-MM-DD: 
if "%OPC_DATE%"=="" exit /b 1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0DOWNLOAD.ps1" -Date "%OPC_DATE%"
pause
