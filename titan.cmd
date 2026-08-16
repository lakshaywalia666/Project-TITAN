@echo off
setlocal
cd /d "%~dp0"

where pwsh.exe >nul 2>nul
if %errorlevel% equ 0 (
  pwsh.exe -NoLogo -NoProfile -File "%~dp0titan.ps1" menu
) else (
  powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0titan.ps1" menu
)

if errorlevel 1 pause
endlocal
