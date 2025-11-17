# Repository Guidelines

This document is for contributors (including automated agents) working in this repository. Follow these guidelines to keep changes consistent and easy to review.

## Project Structure & Module Organization
- Root: documentation and meta files such as `compile.md` and `dnSpy_Project_Analysis.md`.
- Main code: `dnSpy/` contains `dnSpy.sln`, build scripts, and the `dnSpy/dnSpy` subfolder with application projects (GUI, console, debugger contracts, decompiler, Roslyn, etc.).
- Extensions: `dnSpy/Extensions/` holds debugger, decompiler, and other plugin-style components.
- Libraries and assets: `dnSpy/Libraries/` for third‑party code and `dnSpy/images/` for UI resources.

## Build, Test, and Development Commands
- Build (recommended): `cd dnSpy` then `pwsh -File build.ps1` to build all primary targets (see `compile.md` for details).
- Manual build: `cd dnSpy` then `dotnet build dnSpy.sln -c Release`.
- Run tests (where available): `cd dnSpy` then `dotnet test dnSpy.sln` to execute test projects included in the solution.

## Coding Style & Naming Conventions
- C# uses tabs with width 4 (`.editorconfig` is the source of truth). Project files, XML, and YAML typically use 2-space indentation.
- Prefer clear, descriptive names: PascalCase for types and public members; camelCase for locals and parameters.
- Keep namespaces aligned with folder layout (e.g., `dnSpy.Debugger.*`, `dnSpy.Decompiler.*`) and avoid large “god” classes.

## Testing Guidelines
- Place tests next to related code, usually under `Tests` subfolders (for example in `Extensions/*/Tests`).
- Name test files and classes to reflect the feature under test (e.g., `InterpreterTests.cs`).
- Before opening a PR, run relevant tests via `dotnet test` or your IDE and ensure failures are addressed.

## Commit & Pull Request Guidelines
- Write concise, imperative commit subjects (e.g., `Fix step-over behavior in debugger`, `Refactor BAML decompiler options`), and keep each commit focused on one logical change.
- For pull requests, include: a short summary, detailed description of changes, any related issue IDs, a note on testing performed, and screenshots/gifs for UI changes.
- Update documentation such as `compile.md` or relevant README files when you change build steps, tooling, or major user-visible behavior.

