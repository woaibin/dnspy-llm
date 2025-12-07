# NineSolTrainer Reference Hack Trainer

This directory contains a standalone C# trainer project used as a **reference hack app** for the game "Nine Sols". It is not part of the dnSpy binaries; instead it serves as a playground to experiment with memory / data manipulation, effect triggering, and player-state changes while we reverse-engineer the game.

## Layout

`nine sol trainer/`

- `EffectDealer.txt` - Dump of notable game-side effect names, IDs, and notes gathered while reversing; used as a quick lookup when wiring trainer buttons / hotkeys to in-game visual or gameplay effects.
- `Static Player class .txt` - Notes on static Player-related classes in the game assemblies (fields, properties, inferred meanings for HP/MP/attack stats, etc.).
- `NineSolTrainer/` - Root folder for the trainer solution.

`nine sol trainer/NineSolTrainer/`

- `NineSolTrainer.sln` - Visual Studio / dotnet solution that hosts the trainer project, targeting .NET Standard 2.1 so it can also be loaded as a helper assembly in other tools.

`nine sol trainer/NineSolTrainer/NineSolTrainer/`

- `NineSolTrainer.csproj` - C# project file that references the same game assemblies Nine Sols uses (copied under `bin/Debug/netstandard2.1`) and builds `NineSolTrainer.dll` with helpers for reading/writing player stats and triggering effects.
- `NineSolTrainerMain.cs` - Main trainer implementation, with high-level entry points for external loaders (dnSpy scripts, injectors) and utilities for quickly testing new hooks or patches using the notes from the text dumps.
- `Loader.cs` - Lightweight loader shim exposing a simple static entry used when the trainer is loaded via reflection or injection.
- `bin/` - **Build output only (ignored by Git)**; `Debug/netstandard2.1` holds game assemblies, third-party DLLs, `NineSolTrainer.dll`, and its PDB from local builds, never versioned.
- `obj/` - **MSBuild intermediate output (ignored by Git)**; auto-generated files like `*.AssemblyInfo.cs`, caches, `project.assets.json`, and another copy of the built DLL/PDB, all safe to delete and recreated on build.

## Usage

- Open `NineSolTrainer.sln` in Visual Studio or run:
  `dotnet build "nine sol trainer/NineSolTrainer/NineSolTrainer/NineSolTrainer.csproj" -c Debug`
- After building, `NineSolTrainer.dll` will be under:
  `nine sol trainer/NineSolTrainer/NineSolTrainer/bin/Debug/netstandard2.1/`
- You can then load `NineSolTrainer.dll` into dnSpy and call its entry points from the C# REPL / scripting environment, or hook it up to other injectors that reference the DLL.

## Git hygiene for the trainer

- This trainer is **source-only** in Git: compiled outputs and game DLLs under `bin/` and `obj/` are ignored via the root `.gitignore`, as are logs/JSON dumps created while hacking Nine Sols.
- If you add new helper tools or notes, keep them under `nine sol trainer/` and do **not** commit any new `bin/` or `obj/` contents; if they show up in `git status`, extend `.gitignore` instead of staging them.
