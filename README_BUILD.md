# dnSpy Build Scripts

This directory contains automated build scripts for dnSpy.

## Available Scripts

### Build Only Scripts

#### 1. Batch Script (Windows)
**File**: `build_dnspy_all.bat`

Simple batch script that builds dnSpy with basic error handling.

**Usage**:
```cmd
build_dnspy_all.bat
```

**Features**:
- ✅ Checks for .NET SDK
- ✅ Cleans previous builds
- ✅ Restores NuGet packages
- ✅ Builds solution
- ✅ Verifies output files
- ✅ Counts extensions built
- ✅ Optional launch after build
- ✅ Color-coded output
- ✅ Error handling with helpful messages

#### 2. PowerShell Script (Advanced)
**File**: `build_dnspy_all.ps1`

Advanced PowerShell script with more features and better error handling.

**Usage**:
```powershell
# Basic build
.\build_dnspy_all.ps1

# Skip launching dnSpy after build
.\build_dnspy_all.ps1 -SkipLaunch

# Force clean and stop running processes
.\build_dnspy_all.ps1 -Force

# Debug configuration
.\build_dnspy_all.ps1 -Configuration Debug
```

**Features**:
- ✅ All features from batch script
- ✅ Advanced error handling
- ✅ Process detection and termination
- ✅ Build time tracking
- ✅ Visual Studio detection
- ✅ Detailed file size reporting
- ✅ PowerShell parameter support
- ✅ Better progress reporting

#### 3. Simple Versions
- **`quick_build.bat`** - Minimal batch script
- **`build_dnspy_simple.ps1`** - Clean PowerShell script

### Build and Open Scripts

#### 4. Build and Open (Batch - Recommended)
**File**: `build_and_open.bat`

**Best choice for most users** - builds dnSpy and automatically opens it.

**Usage**:
```cmd
build_and_open.bat
```

**Features**:
- ✅ Builds dnSpy automatically
- ✅ Detects and handles running dnSpy instances
- ✅ Automatic launch after successful build
- ✅ Color-coded output
- ✅ Comprehensive error handling
- ✅ User-friendly prompts

#### 5. Build and Open (PowerShell - Advanced)
**File**: `build_and_open.ps1`

Advanced version with maximum features and customization.

**Usage**:
```powershell
# Build and open
.\build_and_open.ps1

# Skip build, just open existing executable
.\build_and_open.ps1 -SkipBuild

# Force close existing dnSpy instances
.\build_and_open.ps1 -ForceClose

# Wait for dnSpy to close before ending script
.\build_and_open.ps1 -WaitForClose

# Custom configuration
.\build_and_open.ps1 -Configuration Debug -ExecutablePath "custom\path\dnSpy.exe"
```

**Features**:
- ✅ All build features from other scripts
- ✅ Automatic dnSpy launch
- ✅ Process management (detect/close running instances)
- ✅ Administrator privilege detection
- ✅ Process ID tracking
- ✅ Advanced error handling
- ✅ Customizable executable path
- ✅ Wait for close option
- ✅ Detailed progress reporting

#### 6. Quick Build and Open
**File**: `quick_build_and_open.bat`

Minimal script for quick build and open.

**Usage**:
```cmd
quick_build_and_open.bat
```

**Features**:
- ✅ Fast build and open
- ✅ Automatic process cleanup
- ✅ Simple error handling

## Requirements

- **.NET SDK** (version 5.0 or later recommended)
- **Visual Studio** (optional, for full debugging support)
- **Windows** (scripts are Windows-specific)

## Quick Start

### For Most Users (Recommended)

**Build and automatically open dnSpy:**
```cmd
# Simple build and open (recommended)
build_and_open.bat

# Or PowerShell version with more features
.\build_and_open.ps1
```

### For Build Only

**Just build without opening:**
```cmd
# Simple batch script
build_dnspy_all.bat

# Or PowerShell with advanced options
.\build_dnspy_all.ps1
```

### Steps

1. **Open Command Prompt or PowerShell as Administrator**
2. **Navigate to repository root directory** (where `dnSpy` folder is located)
3. **Run the desired script** from the options above

**Note**: The scripts automatically look for `dnSpy\dnSpy.sln` in the subdirectory.

## Output Locations

After successful build, executables will be located at:

- **Main Application**: `dnSpy\dnSpy\dnSpy\bin\Release\net48\dnSpy.exe`
- **Console Version**: `dnSpy\dnSpy\dnSpy\bin\Release\net48\dnSpy.Console.exe`
- **x86 Version**: `dnSpy\dnSpy\dnSpy\bin\Release\net48\dnSpy-x86.exe`
- **.NET 5.0 Versions**: `dnSpy\dnSpy\dnSpy\bin\Release\net5.0-windows\`

## Troubleshooting

### Common Issues

1. **".NET SDK not found"**
   - Install .NET SDK from https://dotnet.microsoft.com/download
   - Ensure it's added to PATH

2. **"Build failed - file locked"**
   - Close any running dnSpy instances
   - Use `-Force` parameter with PowerShell script
   - Restart your machine if needed

3. **"Missing Visual Studio components"**
   - Install Visual Studio with .NET desktop development workload
   - Ensure MSBuild tools are installed

4. **Permission errors**
   - Run Command Prompt/PowerShell as Administrator
   - Check folder permissions

### Manual Build (Fallback)

If scripts fail, you can build manually:

```cmd
dotnet restore dnSpy\dnSpy.sln
dotnet build dnSpy\dnSpy.sln --configuration Release
```

## Build Configuration

The scripts build dnSpy with these settings:

- **Configuration**: Release
- **Target Frameworks**:
  - .NET Framework 4.8
  - .NET 5.0-windows
- **Output**: Self-contained executables
- **Extensions**: All default extensions included

## Customization

You can modify the scripts to:
- Change build configuration (Debug/Release)
- Add custom build arguments
- Include additional build steps
- Modify output paths

## Support

For issues with the build scripts:
1. Check the [dnSpy Wiki](https://github.com/dnSpy/dnSpy/wiki)
2. Review [GitHub Issues](https://github.com/dnSpy/dnSpy/issues)
3. Ensure you have the latest .NET SDK