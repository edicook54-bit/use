@echo off
setlocal EnableExtensions EnableDelayedExpansion

:: ============================================================
::  Windows Time Service (w32time) Reset & Repair
::  Run as Administrator
:: ============================================================

set "LOG=%TEMP%\w32time_reset_%DATE:/=-%.log"

:: --- Require administrator privileges ---
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] This script must be run as Administrator.
    echo Right-click the file and choose "Run as administrator".
    pause
    exit /b 1
)

echo Logging to "%LOG%"
echo ===== w32time reset started %DATE% %TIME% ===== > "%LOG%"

:: --- Ensure the service is enabled (not Disabled) ---
echo [*] Setting W32Time to start automatically...
sc config w32time start= auto >> "%LOG%" 2>&1

:: --- Stop the service (ignore error if already stopped) ---
echo [*] Stopping W32Time...
net stop w32time >> "%LOG%" 2>&1
timeout /t 2 /nobreak >nul

:: --- Re-register the service ---
echo [*] Re-registering W32Time...
w32tm /unregister >> "%LOG%" 2>&1
timeout /t 2 /nobreak >nul
w32tm /register >> "%LOG%" 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] w32tm /register failed. See "%LOG%".
    pause
    exit /b 1
)
timeout /t 2 /nobreak >nul

:: --- Fix registry: polling interval + compatibility flags ---
echo [*] Applying registry settings...
reg add "HKLM\SYSTEM\CurrentControlSet\Services\W32Time\TimeProviders\NtpClient" /v SpecialPollInterval /t REG_DWORD /d 900 /f >> "%LOG%" 2>&1
reg add "HKLM\SYSTEM\CurrentControlSet\Services\W32Time\TimeProviders\NtpClient" /v CompatibilityFlags /t REG_DWORD /d 0 /f >> "%LOG%" 2>&1

:: --- Configure stable NTP servers ---
echo [*] Configuring NTP peers...
w32tm /config /manualpeerlist:"time.google.com,0x9 time.windows.com,0x9 time.nist.gov,0x9" /syncfromflags:manual /reliable:no /update >> "%LOG%" 2>&1

:: --- Firewall: allow NTP (UDP 123) ---
echo [*] Configuring firewall rules...
netsh advfirewall firewall delete rule name="NTP-OUT" >nul 2>&1
netsh advfirewall firewall delete rule name="NTP-IN"  >nul 2>&1
netsh advfirewall firewall add rule name="NTP-OUT" dir=out protocol=udp remoteport=123 action=allow >> "%LOG%" 2>&1
netsh advfirewall firewall add rule name="NTP-IN"  dir=in  protocol=udp localport=123  action=allow >> "%LOG%" 2>&1

:: --- Restart the service ---
echo [*] Restarting W32Time...
net stop w32time >> "%LOG%" 2>&1
timeout /t 2 /nobreak >nul
net start w32time >> "%LOG%" 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Could not start W32Time. See "%LOG%".
    pause
    exit /b 1
)

:: --- Force resync ---
echo [*] Forcing time resync...
w32tm /resync /force >> "%LOG%" 2>&1
if %errorlevel% neq 0 (
    echo [WARN] Resync reported an error. Check connectivity / firewall.
)

:: --- Show current status ---
echo.
echo ===== Current time status =====
w32tm /query /status
echo.
echo Done. Full log: "%LOG%"
pause
endlocal
