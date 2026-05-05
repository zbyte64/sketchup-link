@echo off
REM SketchUp Link VM Setup — OEM script for dockurr/windows
REM Runs during the last step of automatic Windows installation.
REM Deploys a first-logon startup script to install SketchUp, apply crack,
REM and deploy the SketchUp Link plugin.
REM See: https://github.com/dockur/windows#how-do-i-run-a-script-after-installation

REM *******************************************************************
REM Phase 0: Bootstrap — detect and skip already-deployed
REM *******************************************************************
set DEPLOY_MARKER=C:\OEM\.install_done
if exist "%DEPLOY_MARKER%" (
    echo install.bat: Already deployed (marker exists). Exiting.
    goto :EOF
)

REM *******************************************************************
REM Phase 1: Disable Windows Firewall
REM *******************************************************************
echo === install.bat: Disabling Windows Firewall ===
netsh advfirewall set allprofiles state off
if %ERRORLEVEL% neq 0 (
    echo WARNING: Failed to disable firewall (exit code %ERRORLEVEL%)
) else (
    echo OK: Firewall disabled
)

REM Add explicit firewall rule for SketchUp Link TCP port
echo Adding firewall rule for TCP port 9876...
netsh advfirewall firewall add rule name="SketchUp Link 9876" dir=in action=allow protocol=TCP localport=9876
if %ERRORLEVEL% neq 0 (
    echo WARNING: Failed to add firewall rule (exit code %ERRORLEVEL% — may already exist)
) else (
    echo OK: Firewall rule added
)

REM *******************************************************************
REM Phase 2: Deploy first-logon SketchUp installer script
REM *******************************************************************
echo === install.bat: Deploying first-logon SketchUp installer ===

set STARTUP_DIR=C:\ProgramData\Microsoft\Windows\Start Menu\Programs\StartUp
if not exist "%STARTUP_DIR%" (
    mkdir "%STARTUP_DIR%"
    if %ERRORLEVEL% neq 0 (
        echo ERROR: Could not create startup directory %STARTUP_DIR%
        exit /b 1
    )
    echo Created startup directory
)

REM Write VBS launcher that runs PowerShell hidden
REM Using temporary file approach to avoid heredoc issues
set VBS_FILE=%STARTUP_DIR%\install_sketchup.vbs
echo Set WshShell = CreateObject("WScript.Shell") > "%VBS_FILE%"
if %ERRORLEVEL% neq 0 (
    echo ERROR: Could not write VBS launcher to %VBS_FILE%
    exit /b 1
)
echo WshShell.Run "powershell.exe -ExecutionPolicy Bypass -NoProfile -WindowStyle Hidden -File C:\OEM\install_sketchup.ps1", 0, False >> "%VBS_FILE%"
if %ERRORLEVEL% neq 0 (
    echo ERROR: Could not append to VBS launcher
    exit /b 1
)
echo OK: VBS launcher written to %VBS_FILE%

REM *******************************************************************
REM Phase 3: Write deployment marker
REM *******************************************************************
echo Deployed: %DATE% %TIME% > "%DEPLOY_MARKER%"

echo === install.bat: OEM setup complete ===
