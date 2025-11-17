@echo off
echo Building and launching dnSpy...
echo.

REM Check if solution exists
if not exist "dnSpy\dnSpy.sln" (
    echo ERROR: dnSpy.sln not found! Please run from repository root.
    pause
    exit /b 1
)

REM Stop any running dnSpy processes
taskkill /F /IM dnSpy.exe >nul 2>&1

REM Build dnSpy
echo Building dnSpy...
dotnet build dnSpy\dnSpy.sln --configuration Release --verbosity minimal

if %ERRORLEVEL% equ 0 (
    echo.
    echo Build successful! Launching dnSpy...
    start "" "dnSpy\dnSpy\dnSpy\bin\Release\net48\dnSpy.exe"
    echo dnSpy launched!
) else (
    echo.
    echo Build failed!
)

echo.
pause