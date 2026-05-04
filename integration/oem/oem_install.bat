@echo off
REM Automatically configure Windows for SketchUp Link testing
REM Runs during the last step of dockur/windows automatic installation.
REM See: https://github.com/dockur/windows#how-do-i-run-a-script-after-installation

echo === SketchUp Link VM Setup ===

REM Disable Windows Firewall for all profiles
echo Disabling Windows Firewall...
netsh advfirewall set allprofiles state off

REM Add explicit firewall rules for SketchUp Link TCP port
echo Adding firewall rule for TCP port 9876...
netsh advfirewall firewall add rule name="SketchUp Link 9876" dir=in action=allow protocol=TCP localport=9876

echo === Setup complete ===
