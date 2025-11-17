# dnSpy Compilation Guide

## Overview
dnSpy is a .NET assembly editor and debugger written in C#. This document outlines the compilation methods for the project.

## Prerequisites
- .NET SDK 5.0 or later (project uses net5.0-windows and net48)
- PowerShell (for build.ps1 script)
- Git with submodules support

## Repository Structure
```
dnSpy/
├── dnSpy.sln              # Main solution file
├── build.ps1              # Primary build script (PowerShell)
├── clean-all.cmd          # Clean build artifacts
├── dnSpy/                 # Main application source
├── Extensions/            # Extension modules
├── Libraries/             # Third-party libraries
├── Build/                 # Build utilities
└── .gitmodules           # Git submodule definitions
```

## Compilation Methods

### Method 1: PowerShell Build Script (Recommended)
```powershell
# Clone with submodules (required)
git clone --recursive https://github.com/dnSpy/dnSpy.git
cd dnSpy

# Build using PowerShell script
./build.ps1

# Or use dotnet build instead of MSBuild
./build.ps1 -NoMsbuild
```

**Build Parameters:**
- `$buildtfm`: Target framework ('all', 'netframework', 'net-x86', 'net-x64')
- `-NoMsbuild`: Use dotnet build instead of MSBuild

**Outputs:**
- .NET Framework: `dnSpy/dnSpy/bin/Release/net48/`
- .NET 5 x86: `dnSpy/dnSpy/bin/Release/net5.0-windows/win-x86/publish/`
- .NET 5 x64: `dnSpy/dnSpy/bin/Release/net5.0-windows/win-x64/publish/`

### Method 2: Manual dotnet build
```bash
# Ensure submodules are initialized first
git submodule update --init --recursive

# Build specific projects
dotnet build dnSpy.sln

# Or build specific configurations
dotnet build -c Release -f net48
dotnet build -c Release -f net5.0-windows
```

### Method 3: MSBuild
```bash
# Using MSBuild directly
msbuild dnSpy.sln -p:Configuration=Release -p:TargetFramework=net48
```

## Build Configuration Details

### Target Frameworks
- **net48**: .NET Framework 4.8 (desktop application)
- **net5.0-windows**: .NET 5.0 Windows-specific build

### Architecture Support
- **x86**: 32-bit builds for .NET 5
- **x64**: 64-bit builds for .NET 5
- **Any CPU**: .NET Framework builds

### Build Process
1. **AppHostPatcher**: Builds first to patch application hosts
2. **.NET Framework Build**: Creates dnSpy.exe for net48
3. **.NET 5 Build**: Creates self-contained executables for specified architectures
4. **Output Organization**: Moves binaries to structured directories

## Key Submodules Required
The project depends on several git submodules:
- `ICSharpCode.Decompiler`: ILSpy decompiler engine
- `ICSharpCode.TreeView`: Enhanced TreeView control
- `Mono.Debugger.Soft`: Mono debugging support
- `Roslyn.ExpressionCompiler`: Roslyn-based expression compiler
- `dnSpy.Images`: Application image resources

## Build Issues Encountered

### Submodule Initialization Problems
```bash
# If submodules fail to clone, try:
git submodule sync
git submodule update --init --recursive --force

# Or clone individually:
git submodule update --init --recursive --depth 1
```

### Network/Proxy Issues
When using a proxy, configure git appropriately:
```bash
git config --global http.proxy http://127.0.0.1:2805
git config --global https.proxy http://127.0.0.1:2805
```

### Alternative: Download Release Binaries
If compilation fails due to missing dependencies, pre-compiled binaries are available at:
https://github.com/dnSpy/dnSpy/releases

## Build Artifacts
After successful compilation, you'll find:
- `dnSpy.exe`: Main application (GUI)
- `dnSpy.Console.exe`: Console version
- `dnSpy-x86.exe`: 32-bit version (netframework)
- Required DLLs and dependencies in respective `bin/` folders

## Notes
- The build script automatically handles dependency restoration
- COM references are used, requiring full MSBuild in some scenarios
- .NET 5.0 is flagged as out-of-support, consider upgrading to newer versions
- Debug builds can be created by changing configuration to 'Debug'