@echo off
chcp 65001 >nul
rem Founder only: download the TEST sandbox batches (2099-12-31). Employees do not need this.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0DOWNLOAD.ps1" -Date 2099-12-31
pause
