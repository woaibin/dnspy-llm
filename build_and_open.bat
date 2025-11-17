@echo off
setlocal enabledelayedexpansion

:: ===============================================
:: dnSpy Build and Open Script
:: ===============================================
:: This script builds dnSpy and automatically opens it
:: ===============================================

echo ===============================================
echo dnSpy Build and Open Script
echo ===============================================
echo.

:: Set colors for better output
set "INFO=[36m"
set "SUCCESS=[32m"
set "WARNING=[33m"
set "ERROR=[31m"
set "RESET=[0m"

:: Ensure standard Windows paths are available (needed by NuGet/dotnet)
if "%APPDATA%"=="" set "APPDATA=%USERPROFILE%\AppData\Roaming"
if "%LOCALAPPDATA%"=="" set "LOCALAPPDATA=%USERPROFILE%\AppData\Local"
if "%ProgramData%"=="" set "ProgramData=C:\ProgramData"

:: Check if we're in the right directory
if not exist "dnSpy\dnSpy.sln" (
    echo %ERROR%ERROR: dnSpy.sln not found!%RESET%
    echo Please run this script from the repository root directory.
    echo Expected path: dnSpy\dnSpy.sln
    echo.
    pause
    exit /b 1
)

:: Check for .NET SDK
echo %INFO%Checking for .NET SDK...%RESET%
dotnet --version >nul 2>&1
if errorlevel 1 (
    echo %ERROR%ERROR: .NET SDK not found!%RESET%
    echo Please install the .NET SDK from https://dotnet.microsoft.com/download
    echo.
    pause
    exit /b 1
)
echo %SUCCESS%.NET SDK found.%RESET%
echo.

:: Define executable path (framework-dependent net5 build)
set "EXE_PATH=dnSpy\dnSpy\dnSpy\bin\Release\net5.0-windows\dnSpy.exe"

:: Check if dnSpy is already running
echo %INFO%Checking for running dnSpy instances...%RESET%
tasklist /FI "IMAGENAME eq dnSpy.exe" 2>NUL | find /I /N "dnSpy.exe">NUL
if %ERRORLEVEL% equ 0 (
    echo %WARNING%dnSpy is already running!%RESET%
    echo.
    set /p CHOICE="Close existing dnSpy and continue? (Y/N): "
    if /i not "%CHOICE%"=="Y" (
        echo Exiting without building.
        pause
        exit /b 0
    )
    echo %INFO%Closing existing dnSpy instances...%RESET%
    taskkill /F /IM dnSpy.exe >nul 2>&1
    timeout /t 2 >nul
)

:: Start building
echo %INFO%Starting dnSpy build process...%RESET%
echo.

:: Clean previous builds
echo %INFO%Cleaning previous builds...%RESET%
if exist "dnSpy\dnSpy\bin" (
    echo Cleaning bin directories...
    for /d /r "dnSpy" %%d in (bin) do if exist "%%d" rmdir /s /q "%%d" 2>nul
)
echo %SUCCESS%Clean completed.%RESET%
echo.

:: Build the solution (skip restore since packages are already present)
echo %INFO%Building dnSpy solution (no restore)...%RESET%
echo This may take a few minutes, please be patient...
echo.

dotnet build dnSpy\dnSpy.sln --configuration Release --verbosity minimal --no-restore
set BUILD_RESULT=%errorlevel%

echo.
if %BUILD_RESULT% equ 0 (
    echo %SUCCESS%Build completed successfully!%RESET%
) else (
    echo %ERROR%Build failed with error code: %BUILD_RESULT%%RESET%
    echo.
    echo Common issues:
    echo 1. Make sure all required Visual Studio components are installed
    echo 2. Check if any dnSpy processes are still running and close them manually
    echo 3. Try running as Administrator
    echo.
    pause
    exit /b %BUILD_RESULT%
)

:: Verify the executable was created
echo %INFO%Verifying build output...%RESET%
if exist "%EXE_PATH%" (
    for %%F in ("%EXE_PATH%") do set SIZE=%%~zF
    set /a SIZE_MB=!SIZE! / 1048576
    echo %SUCCESS%dnSpy.exe found (!SIZE_MB! MB)%RESET%
) else (
    echo %ERROR%ERROR: dnSpy.exe not found at expected location!%RESET%
    echo Expected: %EXE_PATH%
    echo.
    pause
    exit /b 1
)

:: Launch dnSpy
echo.
echo %SUCCESS%=====================================%RESET%
echo %SUCCESS%BUILD COMPLETE - LAUNCHING dnSpy!%RESET%
echo %SUCCESS%=====================================%RESET%
echo.
echo %INFO%Starting dnSpy...%RESET%

start "" "%EXE_PATH%"

if errorlevel 1 (
    echo %WARNING%dnSpy launch initiated. If it doesn't appear, check for any error dialogs.%RESET%
) else (
    echo %SUCCESS%dnSpy launched successfully!%RESET%
)

echo.
echo %INFO%dnSpy should be opening in a few moments...%RESET%
echo %INFO%You can now use dnSpy to analyze .NET assemblies.%RESET%
echo.

:: Optional: Keep window open for a moment
timeout /t 3 >nul

echo %SUCCESS%All done! Script complete.%RESET%
echo.
echo %INFO%If dnSpy doesn't appear, check:%RESET%
echo %INFO%1. Windows Security prompts (may need to allow)%RESET%
echo %INFO%2. Any error dialogs that may have appeared%RESET%
echo %INFO%3. Task Manager to verify dnSpy.exe is running%RESET%
echo.

pause
