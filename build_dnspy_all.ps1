# ===============================================
# dnSpy All-in-One Build Script (PowerShell)
# ===============================================
# This script builds the entire dnSpy solution
# with proper error handling and progress reporting
# ===============================================

param(
    [switch]$SkipLaunch,
    [switch]$Force,
    [string]$Configuration = "Release"
)

# Enable colorful output
function Write-ColorOutput {
    param(
        [string]$Message,
        [string]$Color = "White"
    )
    Write-Host $Message -ForegroundColor $Color
}

function Write-Section {
    param([string]$Title)
    Write-ColorOutput "`n===============================================" "Cyan"
    Write-ColorOutput $Title "Cyan"
    Write-ColorOutput "===============================================" "Cyan"
}

function Test-Command {
    param([string]$Command)
    try {
        Get-Command $Command -ErrorAction Stop | Out-Null
        return $true
    }
    catch {
        return $false
    }
}

# Main script starts here
Write-Section "dnSpy All-in-One Build Script"

# Check if we're in the right directory
$solutionPath = "dnSpy\dnSpy.sln"
if (-not (Test-Path $solutionPath)) {
    Write-ColorOutput "ERROR: dnSpy.sln not found!" "Red"
    Write-ColorOutput "Please run this script from the repository root directory." "Yellow"
    Write-ColorOutput "Expected path: $solutionPath" "Yellow"
    Read-Host "Press Enter to exit"
    exit 1
}

# Step 1: Check for .NET SDK
Write-Section "Step 1: Checking Prerequisites"

if (-not (Test-Command "dotnet")) {
    Write-ColorOutput "ERROR: .NET SDK not found!" "Red"
    Write-ColorOutput "Please install the .NET SDK from https://dotnet.microsoft.com/download" "Yellow"
    Read-Host "Press Enter to exit"
    exit 1
}

$dotnetVersion = & dotnet --version
Write-ColorOutput ".NET SDK version: $dotnetVersion" "Green"

# Check for Visual Studio Build Tools (optional but recommended)
$vsWhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
if (Test-Path $vsWhere) {
    $vsPath = & $vsWhere -latest -products * -requires Microsoft.VisualStudio.Component.VSSDK -property installationPath
    if ($vsPath) {
        Write-ColorOutput "Visual Studio found: $vsPath" "Green"
    }
}

# Step 2: Stop any running dnSpy processes
if ($Force) {
    Write-Section "Step 2: Stopping dnSpy Processes"
    $dnSpyProcesses = Get-Process -Name "dnSpy" -ErrorAction SilentlyContinue
    if ($dnSpyProcesses) {
        Write-ColorOutput "Stopping running dnSpy processes..." "Yellow"
        $dnSpyProcesses | Stop-Process -Force
        Start-Sleep -Seconds 2
    } else {
        Write-ColorOutput "No running dnSpy processes found." "Green"
    }
}

# Step 3: Clean previous builds
Write-Section "Step 3: Cleaning Previous Builds"

$cleanupPaths = @(
    "dnSpy\dnSpy\bin",
    "dnSpy\dnSpy\obj"
)

$cleanedCount = 0
foreach ($path in $cleanupPaths) {
    if (Test-Path $path) {
        Write-ColorOutput "Cleaning: $path" "Yellow"
        try {
            Remove-Item $path -Recurse -Force -ErrorAction SilentlyContinue
            $cleanedCount++
        }
        catch {
            Write-ColorOutput "Warning: Could not clean $path - may be in use" "Yellow"
        }
    }
}
Write-ColorOutput "Cleaned $cleanedCount directories" "Green"

# Step 4: Restore packages
Write-Section "Step 4: Restoring NuGet Packages"

Write-ColorOutput "Restoring packages (this may take a moment)..." "Yellow"
try {
    $restoreResult = & dotnet restore $solutionPath --verbosity minimal
    if ($LASTEXITCODE -ne 0) {
        throw "Package restore failed"
    }
    Write-ColorOutput "Packages restored successfully!" "Green"
}
catch {
    Write-ColorOutput "ERROR: Package restore failed!" "Red"
    Write-ColorOutput $_.Exception.Message "Red"
    Read-Host "Press Enter to exit"
    exit 1
}

# Step 5: Build the solution
Write-Section "Step 5: Building dnSpy Solution"

Write-ColorOutput "Building dnSpy in $Configuration configuration..." "Yellow"
Write-ColorOutput "This will take several minutes, please be patient..." "Cyan"

$buildArgs = @(
    "build",
    $solutionPath,
    "--configuration", $Configuration,
    "--verbosity", "minimal",
    "--no-restore"
)

try {
    $buildStopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    $buildResult = & dotnet $buildArgs
    $buildStopwatch.Stop()

    if ($LASTEXITCODE -ne 0) {
        throw "Build failed with exit code $LASTEXITCODE"
    }

    Write-ColorOutput "Build completed successfully in $($buildStopwatch.Elapsed.TotalMinutes.ToString('F1')) minutes!" "Green"
}
catch {
    Write-ColorOutput "ERROR: Build failed!" "Red"
    Write-ColorOutput $_.Exception.Message "Red"
    Write-ColorOutput "`nTroubleshooting tips:" "Yellow"
    Write-ColorOutput "1. Make sure all Visual Studio components are installed" "White"
    Write-ColorOutput "2. Close any running dnSpy instances" "White"
    Write-ColorOutput "3. Try running with -Force parameter" "White"
    Write-ColorOutput "4. Run as Administrator" "White"
    Read-Host "Press Enter to exit"
    exit 1
}

# Step 6: Verify build output
Write-Section "Step 6: Verifying Build Output"

$outputFiles = @{
    "Main Executable" = "dnSpy\dnSpy\dnSpy\bin\Release\net48\dnSpy.exe"
    "Console Executable" = "dnSpy\dnSpy\dnSpy\bin\Release\net48\dnSpy.Console.exe"
    "x86 Executable" = "dnSpy\dnSpy\dnSpy\bin\Release\net48\dnSpy-x86.exe"
}

$foundFiles = 0
$totalSize = 0

foreach ($file in $outputFiles.GetEnumerator()) {
    if (Test-Path $file.Value) {
        $size = (Get-Item $file.Value).Length
        $sizeMB = [math]::Round($size / 1MB, 2)
        Write-ColorOutput "$($file.Key): $($file.Name) ($sizeMB MB)" "Green"
        $foundFiles++
        $totalSize += $size
    } else {
        Write-ColorOutput "WARNING: $($file.Key) not found!" "Yellow"
    }
}

# Count extensions
$extensionPath = "Extensions\*\bin\Release\net48\*.x.dll"
$extensions = Get-ChildItem $extensionPath -ErrorAction SilentlyContinue
$extensionCount = $extensions.Count

Write-ColorOutput "Built $extensionCount extensions" "Green"
Write-ColorOutput "Total output size: $([math]::Round($totalSize / 1MB, 2)) MB" "Cyan"

# Step 7: Final Summary
Write-Section "BUILD SUMMARY"

Write-ColorOutput "✅ Configuration: $Configuration" "White"
Write-ColorOutput "✅ Target Frameworks: .NET Framework 4.8, .NET 5.0-windows" "White"
Write-ColorOutput "✅ Output Directory: dnSpy\dnSpy\bin\Release\" "White"
Write-ColorOutput "✅ Executables Found: $foundFiles/3" "White"
Write-ColorOutput "✅ Extensions Built: $extensionCount" "White"

Write-ColorOutput "`n📁 Build artifacts location:" "Cyan"
Write-ColorOutput "   Main: dnSpy\dnSpy\dnSpy\bin\Release\net48\" "White"
Write-ColorOutput "   .NET 5.0: dnSpy\dnSpy\dnSpy\bin\Release\net5.0-windows\" "White"

Write-ColorOutput "`n🚀 To run dnSpy:" "Green"
Write-ColorOutput "   .\dnSpy\dnSpy\dnSpy\bin\Release\net48\dnSpy.exe" "White"

Write-ColorOutput "`n📟 To run console version:" "Green"
Write-ColorOutput "   .\dnSpy\dnSpy\dnSpy\bin\Release\net48\dnSpy.Console.exe" "White"

# Step 8: Launch dnSpy (optional)
if (-not $SkipLaunch) {
    Write-ColorOutput "`nWould you like to launch dnSpy now? (Y/N)" "Yellow"
    $response = Read-Host
    if ($response -eq "Y" -or $response -eq "y") {
        $dnSpyPath = "dnSpy\dnSpy\dnSpy\bin\Release\net48\dnSpy.exe"
        if (Test-Path $dnSpyPath) {
            Write-ColorOutput "Launching dnSpy..." "Cyan"
            Start-Process -FilePath $dnSpyPath
            Write-ColorOutput "✅ dnSpy launched successfully!" "Green"
        } else {
            Write-ColorOutput "ERROR: dnSpy executable not found!" "Red"
        }
    }
}

Write-ColorOutput "`n🎉 All done! dnSpy build completed successfully!" "Green"
if (-not $SkipLaunch) {
    Read-Host "Press Enter to exit"
}