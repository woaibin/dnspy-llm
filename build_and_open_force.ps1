param(
    [switch]$WaitForClose,
    [string]$Configuration = "Release",
    [string]$ExecutablePath = "dnSpy\dnSpy\dnSpy\bin\Release\net5.0-windows\dnSpy.exe"
)

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

Write-Section "dnSpy Force-Build and Open Script"

$solutionPath = "dnSpy\dnSpy.sln"
if (-not (Test-Path $solutionPath)) {
    Write-ColorOutput "ERROR: dnSpy.sln not found (expected at $solutionPath)" "Red"
    exit 1
}

Write-ColorOutput "Building dnSpy (configuration: $Configuration, no restore)..." "Yellow"
$buildStopwatch = [System.Diagnostics.Stopwatch]::StartNew()
& dotnet build $solutionPath --configuration $Configuration --no-restore
$buildExitCode = $LASTEXITCODE
$buildStopwatch.Stop()
if ($buildExitCode -ne 0) {
    Write-ColorOutput "ERROR: dotnet build failed with exit code $buildExitCode" "Red"
    exit $buildExitCode
}
Write-ColorOutput "Build completed in $($buildStopwatch.Elapsed.TotalSeconds.ToString('F1')) seconds." "Green"

Write-Section "Verifying Output"
if (-not (Test-Path $ExecutablePath)) {
    Write-ColorOutput "ERROR: dnSpy.exe not found after successful build." "Red"
    Write-ColorOutput "Expected path: $ExecutablePath" "Yellow"
    exit 1
}

$fileInfo = Get-Item $ExecutablePath
Write-ColorOutput "Executable: $ExecutablePath" "Green"
Write-ColorOutput "  Size: $([math]::Round($fileInfo.Length / 1MB, 2)) MB" "White"
Write-ColorOutput "  Modified: $($fileInfo.LastWriteTime)" "White"

Write-Section "Launching dnSpy"
$dnspyProcess = Start-Process -FilePath $ExecutablePath -PassThru
if (-not $dnspyProcess) {
    Write-ColorOutput "ERROR: Failed to start dnSpy." "Red"
    exit 1
}

Write-ColorOutput "dnSpy started. PID: $($dnspyProcess.Id)" "Green"

if ($WaitForClose) {
    Write-ColorOutput "`nWaiting for dnSpy to close..." "Cyan"
    $dnspyProcess.WaitForExit()
    Write-ColorOutput "dnSpy has exited. Exit code: $($dnspyProcess.ExitCode)" "Green"
}
