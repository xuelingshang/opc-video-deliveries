@echo off
rem OPC Delivery Downloader (R2-compatible) - also fetches TEST-* samples into OPC-DELIVERIES\_TEST.
rem No GitHub account, password or token is needed.
title OPC Delivery Downloader (R2-compatible) - with TEST samples
cd /d "%~dp0"
chcp 65001 >nul
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0opc-download.ps1" -IncludeTest %*
set RC=%ERRORLEVEL%
echo.
pause
exit /b %RC%
