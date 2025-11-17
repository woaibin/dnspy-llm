# dnSpy Simple Build Script
Write-Host "===============================================" -ForegroundColor Cyan
Write-Host "dnSpy Simple Build Script" -ForegroundColor Cyan
Write-Host "===============================================" -ForegroundColor Cyan

# Check if we're in the right directory
if (-not (Test-Path "dnSpy\dnSpy.sln")) {
    Write-Host "ERROR: dnSpy.sln not found!" -ForegroundColor Red
    Write-Host "Please run this from the repository root directory." -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "Starting dnSpy build..." -ForegroundColor Yellow

try {
    # Clean
    Write-Host "Cleaning..." -ForegroundColor Yellow
    & dotnet clean dnSpy\dnSpy.sln --configuration Release --verbosity minimal

    # Restore
    Write-Host "Restoring packages..." -ForegroundColor Yellow
    & dotnet restore dnSpy\dnSpy.sln --verbosity minimal

    # Build
    Write-Host "Building solution..." -ForegroundColor Yellow
    $buildResult = & dotnet build dnSpy\dnSpy.sln --configuration Release --verbosity minimal

    if ($LASTEXITCODE -eq 0) {
        Write-Host "`n===============================================" -ForegroundColor Green
        Write-Host "BUILD SUCCESSFUL!" -ForegroundColor Green
        Write-Host "===============================================" -ForegroundColor Green

        # Check output files
        $mainExe = "dnSpy\dnSpy\bin\Release\net48\dnSpy.exe"
        $consoleExe = "dnSpy\dnSpy\bin\Release\net48\dnSpy.Console.exe"

        Write-Host "`nOutput files:" -ForegroundColor Cyan
        if (Test-Path $mainExe) {
            $size = (Get-Item $mainExe).Length / 1MB
            Write-Host "  $mainExe ($([math]::Round($size, 2)) MB)" -ForegroundColor Green
        }
        if (Test-Path $consoleExe) {
            $size = (Get-Item $consoleExe).Length / 1MB
            Write-Host "  $consoleExe ($([math]::Round($size, 2)) MB)" -ForegroundColor Green
        }

        Write-Host "`nBuild completed successfully!" -ForegroundColor Green
    } else {
        Write-Host "`n===============================================" -ForegroundColor Red
        Write-Host "BUILD FAILED!" -ForegroundColor Red
        Write-Host "===============================================" -ForegroundColor Red
        exit 1
    }
}
catch {
    Write-Host "Error during build: $_" -ForegroundColor Red
    exit 1
}

Write-Host "`nDone!" -ForegroundColor Cyan