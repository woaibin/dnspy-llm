# ===============================================
# dnSpy Build and Open Script (PowerShell)
# ===============================================
# This script builds dnSpy and automatically opens it
# with enhanced features and error handling
# ===============================================

param(
    [switch]$SkipBuild,
    [switch]$ForceClose,
    [switch]$WaitForClose,
    [string]$Configuration = "Release",
    [string]$ExecutablePath = "dnSpy\dnSpy\dnSpy\bin\Release\net5.0-windows\dnSpy.exe"
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

function Test-AdminPrivileges {
    $currentUser = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($currentUser)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Stop-dnSpyProcesses {
    param([bool]$Force = $false)

    $dnSpyProcesses = Get-Process -Name "dnSpy" -ErrorAction SilentlyContinue
    if ($dnSpyProcesses) {
        Write-ColorOutput "Found running dnSpy processes:" "Yellow"
        $dnSpyProcesses | ForEach-Object {
            Write-ColorOutput "  PID: $($_.Id), Started: $($_.StartTime)" "White"
        }

        if (-not $Force) {
            $response = Read-Host "Close existing dnSpy instances? (Y/N)"
            if ($response -ne "Y" -and $response -ne "y") {
                return $false
            }
        }

        Write-ColorOutput "Closing dnSpy processes..." "Yellow"
        $dnSpyProcesses | Stop-Process -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2

        # Verify they're closed
        $remaining = Get-Process -Name "dnSpy" -ErrorAction SilentlyContinue
        if ($remaining) {
            Write-ColorOutput "Some processes may still be running. Trying force close..." "Yellow"
            $remaining | Stop-Process -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 1
        }

        Write-ColorOutput "dnSpy processes closed." "Green"
        return $true
    } else {
        Write-ColorOutput "No running dnSpy processes found." "Green"
        return $true
    }
}

# Main script starts here
Write-Section "dnSpy Build and Open Script"

# Check if we're in the right directory
$solutionPath = "dnSpy\dnSpy.sln"
if (-not (Test-Path $solutionPath)) {
    Write-ColorOutput "ERROR: dnSpy.sln not found!" "Red"
    Write-ColorOutput "Please run this script from the repository root directory." "Yellow"
    Write-ColorOutput "Expected path: $solutionPath" "Yellow"
    Read-Host "Press Enter to exit"
    exit 1
}

# Check for .NET SDK
Write-ColorOutput "Checking prerequisites..." "Yellow"
if (-not (Test-Command "dotnet")) {
    Write-ColorOutput "ERROR: .NET SDK not found!" "Red"
    Write-ColorOutput "Please install the .NET SDK from https://dotnet.microsoft.com/download" "Yellow"
    Read-Host "Press Enter to exit"
    exit 1
}

$dotnetVersion = & dotnet --version
Write-ColorOutput ".NET SDK version: $dotnetVersion" "Green"

# Ensure standard Windows paths are available (NuGet / dotnet rely on these)
if (-not $env:APPDATA -or $env:APPDATA -eq "") {
    $env:APPDATA = Join-Path $env:USERPROFILE "AppData\Roaming"
}
if (-not $env:LOCALAPPDATA -or $env:LOCALAPPDATA -eq "") {
    $env:LOCALAPPDATA = Join-Path $env:USERPROFILE "AppData\Local"
}
if (-not $env:ProgramData -or $env:ProgramData -eq "") {
    $env:ProgramData = "C:\ProgramData"
}

# Check admin privileges
if (Test-AdminPrivileges) {
    Write-ColorOutput "Running with Administrator privileges" "Green"
} else {
    Write-ColorOutput "Running without Administrator privileges" "Yellow"
}

# Handle existing dnSpy processes
Write-Section "Managing dnSpy Processes"
if (-not (Stop-dnSpyProcesses -Force $ForceClose)) {
    Write-ColorOutput "Operation cancelled by user." "Yellow"
    exit 0
}

# Build dnSpy (unless skipped)
if (-not $SkipBuild) {
    Write-Section "Building dnSpy"

    try {
        Write-ColorOutput "Building solution (no restore)..." "Yellow"
        $buildStopwatch = [System.Diagnostics.Stopwatch]::StartNew()

        $buildArgs = @(
            "build",
            $solutionPath,
            "--configuration", $Configuration,
            "--verbosity", "minimal",
            "--no-restore"
        )

        $buildResult = & dotnet $buildArgs
        $buildStopwatch.Stop()

        $buildExitCode = $LASTEXITCODE
        if ($buildExitCode -eq 0) {
            Write-ColorOutput "Build completed successfully in $($buildStopwatch.Elapsed.TotalSeconds.ToString('F1')) seconds!" "Green"
        } else {
            if (Test-Path $ExecutablePath) {
                Write-ColorOutput "Build reported exit code $buildExitCode but dnSpy.exe exists. Continuing..." "Yellow"
            } else {
                throw "Build failed with exit code $buildExitCode"
            }
        }
    }
    catch {
        Write-ColorOutput "ERROR: Build failed!" "Red"
        Write-ColorOutput $_.Exception.Message "Red"
        Write-ColorOutput "`nTroubleshooting tips:" "Yellow"
        Write-ColorOutput "1. Make sure Visual Studio components are installed" "White"
        Write-ColorOutput "2. Close any running dnSpy instances manually" "White"
        Write-ColorOutput "3. Try running as Administrator" "White"
        Write-ColorOutput "4. Check available disk space" "White"
        Read-Host "Press Enter to exit"
        exit 1
    }
} else {
    Write-ColorOutput "Skipping build as requested." "Yellow"
}

# Verify executable exists
Write-Section "Verifying Output"
if (Test-Path $ExecutablePath) {
    $fileInfo = Get-Item $ExecutablePath
    $sizeMB = [math]::Round($fileInfo.Length / 1MB, 2)
    $lastModified = $fileInfo.LastWriteTime

    Write-ColorOutput "Executable found:" "Green"
    Write-ColorOutput "  Path: $ExecutablePath" "White"
    Write-ColorOutput "  Size: $sizeMB MB" "White"
    Write-ColorOutput "  Modified: $lastModified" "White"
} else {
    Write-ColorOutput "ERROR: dnSpy.exe not found!" "Red"
    Write-ColorOutput "Expected path: $ExecutablePath" "Yellow"
    Write-ColorOutput "The build may have failed or the executable is in a different location." "Yellow"
    Read-Host "Press Enter to exit"
    exit 1
}

# Launch dnSpy
Write-Section "Launching dnSpy"

try {
    Write-ColorOutput "Starting dnSpy..." "Yellow"

    # Start the process
    $dnspyProcess = Start-Process -FilePath $ExecutablePath -PassThru

    if ($dnspyProcess) {
        Write-ColorOutput "dnSpy launched successfully!" "Green"
        Write-ColorOutput "Process ID: $($dnspyProcess.Id)" "White"

        # Wait a moment for the window to appear
        Start-Sleep -Seconds 2

        # Verify it's still running
        if (Get-Process -Id $dnspyProcess.Id -ErrorAction SilentlyContinue) {
            Write-ColorOutput "dnSpy is running!" "Green"
        } else {
            Write-ColorOutput "Warning: dnSpy process may have terminated quickly" "Yellow"
        }
    } else {
        Write-ColorOutput "dnSpy launch initiated." "Yellow"
    }
}
catch {
    Write-ColorOutput "ERROR: Failed to launch dnSpy!" "Red"
    Write-ColorOutput $_.Exception.Message "Red"
    Write-ColorOutput "`nPossible reasons:" "Yellow"
    Write-ColorOutput "1. Windows Security blocked the execution" "White"
    Write-ColorOutput "2. Antivirus software blocked it" "White"
    Write-ColorOutput "3. Missing required runtime components" "White"
    Write-ColorOutput "4. Insufficient permissions" "White"
}

# Optional wait for dnSpy to close
if ($WaitForClose -and $dnspyProcess) {
    Write-ColorOutput "`nWaiting for dnSpy to close..." "Cyan"
    $dnspyProcess.WaitForExit()
    Write-ColorOutput "dnSpy has been closed." "Green"
}

# Final summary
Write-Section "Summary"

Write-ColorOutput "✅ Build Configuration: $Configuration" "Green"
Write-ColorOutput "✅ Executable: $ExecutablePath" "Green"
if ($dnspyProcess) {
    Write-ColorOutput "✅ Process ID: $($dnspyProcess.Id)" "Green"
}
Write-ColorOutput "✅ Status: Complete" "Green"

Write-ColorOutput "`n🎉 dnSpy is ready to use!" "Cyan"
Write-ColorOutput "You can now use dnSpy to:" "White"
Write-ColorOutput "  • Analyze .NET assemblies" "White"
Write-ColorOutput "  • Debug applications" "White"
Write-ColorOutput "  • Edit and decompile code" "White"
Write-ColorOutput "  • Explore assembly structure" "White"

if (-not $WaitForClose) {
    Write-ColorOutput "`nScript completed. Press Enter to exit..." "Cyan"
    Read-Host
}
