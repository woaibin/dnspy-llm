# LLM Chat Automation Plan

This document tracks the design and implementation TODOs for the **llm-chat-automation** feature on top of the existing LLM Chat integration in dnSpy.

## 1. Goals & Scope

- Provide an HTTP API server that exposes:
  - **Broad lookup API**: regex-based search over the analyzed project model, limited to the most recent 500 matches.
  - **Clear lookup API**: direct lookup from a concrete type/class/member identifier to an absolute file path (and related metadata).
- Provide an **automation harness** that uses an external LLM tool (e.g. `claude -p ...`) to:
  - Take a high-level natural-language request from the user.
  - Decide which API(s) to call (broad vs clear lookup).
  - Return a structured JSON result summarizing the findings for the UI.
- Integrate the automation into dnSpy’s UI so that the final structured result can be presented to the user (and ideally allow navigation back into dnSpy where applicable).

## 2. Architecture Overview

- **Existing building blocks**
  - `AnalyzedProject` / `AnalyzedModule` / `AnalyzedType` / `AnalyzedMember` in `Documents/Tabs/ProjectAnalysis.cs`.
  - `ProjectAnalysisFactory.Create(documentTreeView)` used by `LlmChatViewModel` to build the in-memory analysis cache.
  - `LlmSearchEngine.Search(...)` + `LlmSearchFormatter` for current LLM chat keyword-based search.
  - Existing Python LLM backend (`PythonLlmBackend`) that already speaks JSON over stdin/stdout.
- **New modules**
  - `LlmAutomation.Server` (working name): .NET HTTP server hosting the APIs.
  - `LlmAutomation.Orchestrator`: a thin automation layer that:
    - Invokes `claude -p ...` with a carefully-designed system prompt.
    - Interprets the returned JSON (list of tool calls and final answer).
    - Calls the HTTP server endpoints as requested.
  - `LlmAutomation.UI` integration:
    - Either reuse the existing `LlmChatWindow` (new “Automation” mode).
    - Or add a separate window/pane for automation results.

## 3. HTTP API Server Design

**3.1 Hosting model**

- Implement as a new .NET project (e.g. `dnSpy.LlmAutomation.Server`) in the solution:
  - Uses ASP.NET Core minimal APIs or a lightweight self-hosted HTTP listener.
  - Configurable host/port via appsettings or command-line arguments.
- Startup:
  - Load analyzed project data:
    - Option A: Run inside the dnSpy process and reuse the in-memory `AnalyzedProject` created for the LLM chat.
    - Option B: Standalone process that loads a JSON-exported `AnalyzedProject` (reusing the existing project-analysis export logic).
  - For the first iteration, prefer **Option B** (decouple from UI, easier to debug and script).

**3.2 Data model extensions**

- Ensure `AnalyzedModule` and `AnalyzedType` carry enough info to answer “clear lookups”:
  - Add `AssemblyPath` / `ModuleFilePath` (absolute path) to `AnalyzedModule`.
  - Optionally add `SourceFilePath` or `ExportHintPath` to `AnalyzedType` if we have a stable mapping to decompiled C# files.
- Extend the JSON export format to include the new fields so the server has access to them.

**3.3 Broad lookup API**

- Endpoint (example): `GET /api/search/broad?pattern={regex}&maxResults=500`
- Request:
  - `pattern` (required): regex pattern (string) for case-insensitive search.
  - `maxResults` (optional): integer, defaults to 500 and capped at 500.
- Behavior:
  - Compile the regex with `RegexOptions.IgnoreCase | RegexOptions.CultureInvariant`.
  - Scan:
    - Module names.
    - Type `FullName`s.
    - Member names and signatures (methods, fields, properties, events).
  - Collect matches in the order of discovery (or by a simple relevance heuristic).
  - Limit to the last/most recent 500 matches (implementation detail: keep a bounded queue or just stop after 500).
- Response:
  - JSON array of objects like:
    - `kind`: `"module" | "type" | "member"`.
    - `name`: simple name.
    - `fullName`: full type/member name (for navigation).
    - `moduleName`: module/assembly name.
    - `assemblyPath`: absolute path to the module file.
    - `signature`: optional, for members.

**3.4 Clear lookup API**

- Endpoint (example): `GET /api/lookup/clear?identifier={id}`
- Request:
  - `identifier`: string describing the target; options:
    - Fully-qualified type name (e.g. `Game.Player` or `Namespace.Sub.Player`).
    - A more detailed descriptor (e.g. method signature) in later iterations.
- Behavior:
  - Normalize the identifier (trim, remove surrounding quotes).
  - Try matching:
    - Exact `AnalyzedType.FullName`.
    - Fallback: case-insensitive contains match on `FullName`.
  - If multiple matches:
    - Return an array, each entry with module/type info.
    - (Later) add additional query parameters like `module` or `namespace` to narrow it down.
  - For each match:
    - Resolve the `assemblyPath` from the `AnalyzedModule`.
    - Optionally resolve `sourcePath` if `SourceFilePath` is available.
- Response:
  - If a single match:
    - `{ "status": "ok", "identifier": "...", "assemblyPath": "C:\\...\\Assembly-CSharp.dll", "typeFullName": "...", "sourcePath": "C:\\...\\Player.cs" (optional) }`
  - If multiple matches:
    - `{ "status": "ambiguous", "candidates": [ ... same fields as above ... ] }`
  - If no matches:
    - `{ "status": "not_found", "identifier": "..." }`

## 4. Automation (Claude / LLM Orchestrator)

**4.1 System prompt + tools**

- Define a stable system prompt for `claude -p` that:
  - Explains the project domain: Unity/.NET reverse engineering, dnSpy analysis model.
  - Describes two tools (without leaking internal implementation):
    - `broad_lookup(pattern: string)`: calls `/api/search/broad`.
    - `clear_lookup(identifier: string)`: calls `/api/lookup/clear`.
  - Instructs the model to:
    - First, interpret the user’s high-level question.
    - Call tools as needed (0 or more calls).
    - Produce a **final JSON** with a strict schema (see below).
- Example final JSON schema (return shape from Claude to the orchestrator/UI):

### 4.1.1 Final JSON schema (Claude → orchestrator/UI)

- The system prompt must enforce that the LLM returns **exactly one JSON object** with this shape (no markdown, no extra text):

```json
{
  "version": 1,
  "question": "string, original user question",
  "summary": "string, short human-readable answer",
  "steps": [
    {
      "description": "string, what the model did in this step",
      "tool": "broad_lookup | clear_lookup | reasoning_only",
      "tool_input": "string (the regex or identifier used, or explanation for reasoning_only)",
      "tool_output_count": 0
    }
  ],
  "findings": [
    {
      "kind": "type | field | property | method | event | other",
      "name": "string, simple symbol name",
      "fullName": "string, fully-qualified type/member name",
      "moduleName": "string, module/assembly name if known",
      "assemblyPath": "string, absolute assembly path if known, else empty string",
      "sourcePath": "string, absolute source/decompiled file path if known, else empty string",
      "notes": "string, short explanation of why this location is relevant",
      "importance": "high | medium | low"
    }
  ]
}
```

- Constraints:
  - `version` must always be `1` for now.
  - `steps` may be empty, but the property must exist.
  - `findings` may be empty, but the property must exist.
  - `assemblyPath` / `sourcePath` **must still be present** even when unknown (set them to an empty string in that case).
  - No extra top-level fields should be added (keep the contract stable and easy to parse).

### 4.1.2 Example JSON for the “Player attack/health” question

Example of the exact JSON Claude should return for a query like:
`"hey can u help me check where the attack power and health vals in the player is?"` (paths and names are illustrative):

```json
{
  "version": 1,
  "question": "hey can u help me check where the attack power and health vals in the player is?",
  "summary": "The Player stats are stored in the PlayerStats type, with fields for health and attack power, and updated in the ApplyDamage and ApplyBuff methods.",
  "steps": [
    {
      "description": "Used a broad regex search for Player.*(Health|Attack) across analyzed types and members.",
      "tool": "broad_lookup",
      "tool_input": "Player.*(Health|Attack)",
      "tool_output_count": 42
    },
    {
      "description": "Resolved the concrete PlayerStats type to its defining assembly.",
      "tool": "clear_lookup",
      "tool_input": "Game.PlayerStats",
      "tool_output_count": 1
    },
    {
      "description": "Summarized the most relevant fields and methods controlling Player health and attack power.",
      "tool": "reasoning_only",
      "tool_input": "N/A",
      "tool_output_count": 0
    }
  ],
  "findings": [
    {
      "kind": "type",
      "name": "PlayerStats",
      "fullName": "Game.PlayerStats",
      "moduleName": "Assembly-CSharp.dll",
      "assemblyPath": "C:\\Games\\MyUnityGame\\Game_Data\\Managed\\Assembly-CSharp.dll",
      "sourcePath": "C:\\Decompiled\\Game\\PlayerStats.cs",
      "notes": "Main container type for Player combat stats including health and attack power.",
      "importance": "high"
    },
    {
      "kind": "field",
      "name": "_health",
      "fullName": "Game.PlayerStats._health",
      "moduleName": "Assembly-CSharp.dll",
      "assemblyPath": "C:\\Games\\MyUnityGame\\Game_Data\\Managed\\Assembly-CSharp.dll",
      "sourcePath": "C:\\Decompiled\\Game\\PlayerStats.cs",
      "notes": "Current Player health value.",
      "importance": "high"
    },
    {
      "kind": "field",
      "name": "_attackPower",
      "fullName": "Game.PlayerStats._attackPower",
      "moduleName": "Assembly-CSharp.dll",
      "assemblyPath": "C:\\Games\\MyUnityGame\\Game_Data\\Managed\\Assembly-CSharp.dll",
      "sourcePath": "C:\\Decompiled\\Game\\PlayerStats.cs",
      "notes": "Base Player attack power used in damage calculations.",
      "importance": "high"
    },
    {
      "kind": "method",
      "name": "ApplyDamage",
      "fullName": "Game.PlayerStats.ApplyDamage",
      "moduleName": "Assembly-CSharp.dll",
      "assemblyPath": "C:\\Games\\MyUnityGame\\Game_Data\\Managed\\Assembly-CSharp.dll",
      "sourcePath": "C:\\Decompiled\\Game\\PlayerStats.cs",
      "notes": "Reduces _health when the Player takes damage.",
      "importance": "medium"
    },
    {
      "kind": "method",
      "name": "ApplyBuff",
      "fullName": "Game.PlayerStats.ApplyBuff",
      "moduleName": "Assembly-CSharp.dll",
      "assemblyPath": "C:\\Games\\MyUnityGame\\Game_Data\\Managed\\Assembly-CSharp.dll",
      "sourcePath": "C:\\Decompiled\\Game\\PlayerStats.cs",
      "notes": "Temporarily modifies _attackPower and related combat stats.",
      "importance": "medium"
    }
  ]
}
```

**4.2 Orchestrator CLI**

- Implement a small console app or script (e.g. `llm-automation-orchestrator.ps1` or a .NET CLI) that:
  - Accepts a user prompt: `llm-automation run "where are attack power and health vals in the player?"`
  - Builds the `claude -p` command with:
    - The system prompt.
    - The user prompt as `{prompt}`.
  - Parses the JSON result from Claude:
    - Optionally logs tool calls and raw HTTP responses for debugging.
    - Outputs a clean JSON (or text) artifact that the dnSpy UI can consume.

## 5. UI Integration

- Phase 1 (minimal):
  - No UI changes; the orchestrator is external-only.
  - Developer manually reads JSON from the orchestrator/script.
- Phase 2:
  - Add an “Automation” mode to `LlmChatWindow`:
    - A toggle or separate tab that:
      - Shows `AutomationHistory` (requests and JSON results).
      - Renders `findings` as clickable items (like `LlmSearchResult`), reusing `NavigateToSearchResult` logic by mapping findings back into `LlmSearchResult`-like objects.
  - Wire a new command (e.g. `StartLlmAutomationCommand`) in `AppMenus.cs` / `ViewCommands.cs` similar to `StartLlmChatCommand`.
- Phase 3:
  - Tighten the loop:
    - Allow sending the current dnSpy selection (module/type/member) as extra context in the automation request.
    - Allow running the orchestrator in-process (e.g. via a `Process` call from dnSpy with a structured API).

## 6. Implementation TODOs

- [ ] **Decide hosting model** for the HTTP server (standalone vs in-process with dnSpy).
- [ ] **Define final API contracts**:
  - [ ] Confirm URL patterns and query parameters for broad and clear lookup.
  - [ ] Lock down JSON response schemas (including error/ambiguous cases).
- [ ] **Extend analyzed project model**:
  - [ ] Add `AssemblyPath` / `ModuleFilePath` to `AnalyzedModule`.
  - [ ] (Optional) Add `SourceFilePath` / `ExportHintPath` to `AnalyzedType`.
  - [ ] Update JSON export code and existing consumers.
- [ ] **Implement HTTP server project**:
  - [ ] Scaffold `dnSpy.LlmAutomation.Server` project.
  - [ ] Implement `BroadLookupController` / `RegexSearchEngine`.
  - [ ] Implement `ClearLookupController` (identifier → module/type mapping).
  - [ ] Add simple logging and health endpoint (`/health`).
- [ ] **Build regex search logic**:
  - [ ] Efficiently scan `AnalyzedProject` with a compiled regex.
  - [ ] Enforce max 500 result cap.
  - [ ] Unit-test typical patterns, including the “Player attack/health” scenario.
- [ ] **Design Claude system prompt and JSON schema**:
  - [ ] Write initial system prompt describing tools and output format.
  - [ ] Create 2–3 example conversations (Unity “Player” stats, Enemy AI, etc.).
- [ ] **Implement automation orchestrator**:
  - [ ] Prototype PowerShell wrapper calling `claude -p ...`.
  - [ ] Parse Claude’s JSON into a strongly-typed model.
  - [ ] Add logging and basic error handling (invalid JSON, tool failures).
- [ ] **UI integration**:
  - [ ] Decide whether to reuse `LlmChatWindow` or create `LlmAutomationWindow`.
  - [ ] Implement view model(s) for automation sessions and results.
  - [ ] Wire clickable findings to `NavigateToSearchResult` or similar navigation helpers.
- [ ] **End-to-end smoke test**:
  - [ ] Run: user prompt → orchestrator → Claude → HTTP APIs → JSON findings → UI render.
  - [ ] Validate the “attack power and health in Player” workflow, including navigation to the right definitions in dnSpy.
## 7. Current Implementation Notes (dnSpy fork)

- This fork currently implements the automation server and UI integration with a **Python HTTP server** and a lightweight **automation mode** in the existing LLM chat window, rather than a dedicated `.NET` server project.

### 7.1 Automation HTTP server (Python)

- File: `llm_automation_server.py` at the repo root.
- Startup:
  - Reads an `AnalyzedProject` JSON payload from `stdin` on launch.
  - Accepts either:
    - `{ "Modules": [ ... ] }` directly, or
    - `{ "Project": { "Modules": [ ... ] }, ... }` and extracts the inner `Project`.
  - Keeps the parsed project in memory for all subsequent HTTP requests.
- Endpoints (default base URL: `http://127.0.0.1:5015/`):
  - `GET /health`
    - Returns `{ "status": "ok" }` as a simple liveness probe.
  - `GET /api/search/broad?pattern=...&maxResults=...`
    - Uses a compiled regex (case-insensitive) to search:
      - Module names and `AssemblyFullName`.
      - Type `FullName`s.
      - Member names and signatures across fields, methods, properties, events.
    - Enforces a `maxResults` cap of 500.
    - Response: JSON array of objects:
      - `kind`: `"module" | "type" | "member"`.
      - `name`: simple name.
      - `fullName`: full type/member name.
      - `moduleName`: owning module name.
      - `assemblyPath`: best-effort absolute module path (`AssemblyPath` / `ModuleFilePath` / `FileName`).
      - `signature`: optional, for members.
  - `GET /api/lookup/clear?identifier=...`
    - Performs a “clear” lookup from an identifier (usually a full type name) to module/type metadata.
    - Behavior:
      - Normalizes the identifier (trim + strip quotes).
      - Looks for exact `Type.FullName` matches first; falls back to case-insensitive contains.
      - If no matches: `{ "status": "not_found", "identifier": ... }`.
      - If one match: `{ "status": "ok", "identifier", "assemblyPath", "typeFullName", "sourcePath" }`.
      - If multiple matches: `{ "status": "ambiguous", "identifier", "candidates": [ ... ] }`.
    - `sourcePath` is populated if the input JSON includes a `SourceFilePath` field on the type (currently optional / not wired from dnSpy).

### 7.2 Integration with dnSpy UI

- **Menu command**:
  - `Start LLM automation server` is exposed under the `LLM Chat` app menu (`StartLlmAutomationServerCommand` in `MainApp/ViewCommands.cs`).
  - When executed:
    - Builds an `AnalyzedProject` via `ProjectAnalysisFactory.Create(documentTreeView)`.
    - Serializes it to JSON (`DataContractJsonSerializer`).
    - Locates `llm_automation_server.py` next to `dnSpy.exe` (copied there via `dnSpy.csproj` as a `None` item with `CopyToOutputDirectory=PreserveNewest`).
    - Starts a Python process (`python llm_automation_server.py`) with:
      - Working directory = `AppDomain.CurrentDomain.BaseDirectory`.
      - JSON sent to the process’s standard input.
    - Assumes the server listens on `http://127.0.0.1:5015/` and logs that URL and process ID.
- **Automation status window**:
  - `LlmAutomationWindow` (`LlmChat/LlmAutomationWindow.xaml`) is a small status dialog:
    - Shows the server URL (default `http://127.0.0.1:5015/`).
    - Shows a `Status` string (`Idle` / `Starting...` / `Running` / `Error` etc.).
    - Displays an `Events` list with textual log entries (e.g., “Preparing analyzed project”, “Automation server started at ...”).
  - Backed by `LlmAutomationViewModel` which provides:
    - `ServerUrl` (string).
    - `Status` (string).
    - `Events` (`ObservableCollection<string>`).

### 7.3 LLM chat “automation mode”

- **Toggle in LLM chat window**:
  - `LlmChatWindow.xaml` contains a checkbox labeled **“Automation mode (use external automation server/tooling)”**.
  - Bound to `LlmChatViewModel.IsAutomationMode` (bool).
- **Backend request mode flag**:
  - `LlmChatContext` carries a boolean `IsAutomationMode`.
  - `LlmBackendRequest.Create(...)` copies this into a string `Mode` field:
    - `"chat"` when normal mode.
    - `"automation"` when the checkbox is enabled.
- **Python backend behavior (`llm_chat_backend.py`)**:
  - Reads `LlmBackendRequest` JSON from stdin, including:
    - `Messages`: chat transcript.
    - `Project`: the analyzed project (possibly compacted to a single type for file-analysis mode).
    - `Mode`: `"chat"` or `"automation"`.
  - For both modes, it:
    - Builds a compact project overview string (`build_project_overview`).
    - Calls `call_openai_structured(last_user, project_overview, mode=Mode)` to get structured JSON from OpenAI/Poe, or falls back to an offline heuristic (`fallback_keywords`) if disabled/unavailable.
    - Expects a JSON payload with fields:
      - `assistant_message`: free-form explanation to show in the chat.
      - `search_keywords`: list of keywords/phrases.
      - `excluded_modules`: module-name substrings to ignore.
      - `keywords`: optional tree-shaped keywords for building paths.
    - Converts keywords into search paths (`build_keyword_paths` / `build_paths_from_tree`).
  - In **automation mode**:
    - The system prompt is specialized for project-wide/gameplay questions (rather than single-file analysis).
    - The backend is expected to:
      - Use `search_keywords` as regex-like search paths over the project.
      - Treat `excluded_modules` as filters for module names.
    - The backend currently:
      - Have the backend (or a dedicated orchestrator script) call the automation HTTP server directly:
        - Ping `/health`.
        - Call `/api/search/broad` with the derived patterns.
        - Optionally call `/api/lookup/clear` for precise type resolution.
      - Summarize these hits (kind, `fullName`, `moduleName`, `assemblyPath`) and append them to the `assistant_message` returned to dnSpy so the UI can eventually render them as clickable findings.

- At the moment, the Python backend focuses on returning:
  - A rich natural-language `AssistantMessage`.
  - Structured `SearchKeywords` and `ExcludedModules` for dnSpy’s internal search engine (`LlmSearchEngine`) rather than directly wiring automation HTTP results back into the UI.
