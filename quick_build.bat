@echo off
echo ===============================================
echo dnSpy Quick Build Script
echo ===============================================
echo.

REM Check if we're in the right directory
if not exist "dnSpy\dnSpy.sln" (
    echo ERROR: dnSpy.sln not found!
    echo Please run this from the repository root directory.
    pause
    exit /b 1
)

echo Starting dnSpy build...
echo.

REM Clean and build
dotnet clean dnSpy\dnSpy.sln --configuration Release
dotnet restore dnSpy\dnSpy.sln
dotnet build dnSpy\dnSpy.sln --configuration Release --verbosity minimal

if %ERRORLEVEL% equ 0 (
    echo.
    echo ===============================================
    echo BUILD SUCCESSFUL!
    echo ===============================================
    echo.
    echo Output files:
    if exist "dnSpy\dnSpy\bin\Release\net48\dnSpy.exe" (
        echo   dnSpy\dnSpy\bin\Release\net48\dnSpy.exe
    )
    if exist "dnSpy\dnSpy\bin\Release\net48\dnSpy.Console.exe" (
        echo   dnSpy\dnSpy\bin\Release\net48\dnSpy.Console.exe
    )
    echo.
    echo Launch dnSpy? (Y/N)
    set /p choice=
    if /i "%choice%"=="Y" (
        start "" "dnSpy\dnSpy\bin\Release\net48\dnSpy.exe"
        echo dnSpy launched!
    )
) else (
    echo.
    echo ===============================================
    echo BUILD FAILED!
    echo ===============================================
    echo.
)

pause