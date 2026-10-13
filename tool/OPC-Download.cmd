@echo off
rem OPC Delivery Downloader (R2-compatible) - double-click to download all due deliveries.
rem No GitHub account, password or token is needed.
title OPC Delivery Downloader (R2-compatible)
cd /d "%~dp0"
chcp 65001 >nul
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0opc-download.ps1" %*
set RC=%ERRORLEVEL%
echo.
pause
exit /b %RC%
