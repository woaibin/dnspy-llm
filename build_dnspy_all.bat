@echo off
setlocal enabledelayedexpansion

:: ===============================================
:: dnSpy All-in-One Build Script
:: ===============================================
:: This script builds the entire dnSpy solution
:: with proper error handling and progress reporting
:: ===============================================

echo ===============================================
echo dnSpy All-in-One Build Script
echo ===============================================
echo.

:: Set colors for better output
set "INFO=[36m"
set "SUCCESS=[32m"
set "WARNING=[33m"
set "ERROR=[31m"
set "RESET=[0m"

:: Check if we're in the right directory
if not exist "dnSpy\dnSpy.sln" (
    echo %ERROR%ERROR: dnSpy.sln not found!%RESET%
    echo Please run this script from the repository root directory.
    echo Expected path: dnSpy\dnSpy.sln
    echo.
    pause
    exit /b 1
)

echo %INFO%Starting dnSpy build process...%RESET%
echo.

:: Step 1: Check for .NET SDK
echo %INFO%Step 1: Checking for .NET SDK...%RESET%
dotnet --version >nul 2>&1
if errorlevel 1 (
    echo %ERROR%ERROR: .NET SDK not found!%RESET%
    echo Please install the .NET SDK from https://dotnet.microsoft.com/download
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%i in ('dotnet --version') do set DOTNET_VERSION=%%i
echo %SUCCESS%.NET SDK version: !DOTNET_VERSION!%RESET%
echo.

:: Step 2: Clean previous builds
echo %INFO%Step 2: Cleaning previous builds...%RESET%
if exist "dnSpy\dnSpy\bin" (
    echo Cleaning bin directories...
    for /d /r "dnSpy" %%d in (bin) do if exist "%%d" rmdir /s /q "%%d" 2>nul
)
if exist "dnSpy\dnSpy\obj" (
    echo Cleaning obj directories...
    for /d /r "dnSpy" %%d in (obj) do if exist "%%d" rmdir /s /q "%%d" 2>nul
)
echo %SUCCESS%Clean completed.%RESET%
echo.

:: Step 3: Restore NuGet packages
echo %INFO%Step 3: Restoring NuGet packages...%RESET%
dotnet restore dnSpy\dnSpy.sln --verbosity minimal
if errorlevel 1 (
    echo %ERROR%ERROR: Package restore failed!%RESET%
    echo.
    pause
    exit /b 1
)
echo %SUCCESS%Packages restored successfully.%RESET%
echo.

:: Step 4: Build the solution
echo %INFO%Step 4: Building dnSpy solution...%RESET%
echo This may take a few minutes...
echo.

:: Build with detailed output for better error tracking
dotnet build dnSpy\dnSpy.sln --configuration Release --verbosity normal
set BUILD_RESULT=%errorlevel%

echo.
if %BUILD_RESULT% equ 0 (
    echo %SUCCESS%Build completed successfully!%RESET%
) else (
    echo %ERROR%Build failed with error code: %BUILD_RESULT%%RESET%
    echo.
    echo Common issues:
    echo 1. Make sure all required Visual Studio components are installed
    echo 2. Check if any dnSpy processes are running and close them
    echo 3. Try running as Administrator
    echo.
    pause
    exit /b %BUILD_RESULT%
)

:: Step 5: Verify output files
echo %INFO%Step 5: Verifying build output...%RESET%
set MAIN_EXE=dnSpy\dnSpy\dnSpy\bin\Release\net48\dnSpy.exe
set CONSOLE_EXE=dnSpy\dnSpy\dnSpy\bin\Release\net48\dnSpy.Console.exe
set X86_EXE=dnSpy\dnSpy\dnSpy\bin\Release\net48\dnSpy-x86.exe

if exist "%MAIN_EXE%" (
    for %%F in ("%MAIN_EXE%") do set SIZE=%%~zF
    echo %SUCCESS%Main executable: dnSpy.exe (%SIZE% bytes)%RESET%
) else (
    echo %ERROR%WARNING: Main executable not found!%RESET%
)

if exist "%CONSOLE_EXE%" (
    for %%F in ("%CONSOLE_EXE%") do set SIZE=%%~zF
    echo %SUCCESS%Console executable: dnSpy.Console.exe (%SIZE% bytes)%RESET%
) else (
    echo %ERROR%WARNING: Console executable not found!%RESET%
)

if exist "%X86_EXE%" (
    for %%F in ("%X86_EXE%") do set SIZE=%%~zF
    echo %SUCCESS%x86 executable: dnSpy-x86.exe (%SIZE% bytes)%RESET%
) else (
    echo %ERROR%WARNING: x86 executable not found!%RESET%
)

echo.

:: Step 6: Count built extensions
echo %INFO%Step 6: Checking extensions...%RESET%
set EXT_COUNT=0
for %%f in (Extensions\*\bin\Release\net48\*.x.dll) do (
    set /a EXT_COUNT+=1
)
if %EXT_COUNT% gtr 0 (
    echo %SUCCESS%Built %EXT_COUNT% extensions%RESET%
) else (
    echo %WARNING%No extensions found in output%RESET%
)

echo.

:: Step 7: Summary
echo ===============================================
echo %SUCCESS%BUILD SUMMARY%RESET%
echo ===============================================
echo %INFO%Configuration: Release
echo %INFO%Target Frameworks: .NET Framework 4.8, .NET 5.0-windows
echo %INFO%Output Directory: dnSpy\dnSpy\bin\Release\%RESET%
echo.
echo %SUCCESS%Build completed successfully!%RESET%
echo.
echo To run dnSpy:
echo   dnSpy\dnSpy\dnSpy\bin\Release\net48\dnSpy.exe
echo.
echo To run console version:
echo   dnSpy\dnSpy\dnSpy\bin\Release\net48\dnSpy.Console.exe
echo.

:: Ask if user wants to launch dnSpy
set /p LAUNCH="Would you like to launch dnSpy now? (Y/N): "
if /i "%LAUNCH%"=="Y" (
    echo.
    echo %INFO%Launching dnSpy...%RESET%
    start "" "dnSpy\dnSpy\dnSpy\bin\Release\net48\dnSpy.exe"
    echo %SUCCESS%dnSpy launched!%RESET%
)

echo.
echo %INFO%All done! Press any key to exit...%RESET%
pause >nul
exit /b 0