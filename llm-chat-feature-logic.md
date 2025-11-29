# LLM Chat Feature Logic Overview (dnSpy Integration)

This document summarizes how the LLM chat system in this repository works, from menu entry to search over the analyzed project model and navigation back into dnSpy.

## Entry Points & UI Flow

- Top-level menu: a new **LLM Chat** menu is registered in `AppMenus.cs` using `APP_MENU_LLMCHAT_GUID` / `ORDER_APP_MENU_LLMCHAT`.
- Menu item: **Start a new LLM chat** (`StartLlmChatCommand` in `MainApp/ViewCommands.cs`) is exported under `GROUP_APP_MENU_LLMCHAT_COMMANDS`.
- When the item is clicked, the command:
  - Verifies there are loaded modules in `IDocumentTreeView`.
  - Creates an `LlmChatViewModel` (passing `IDocumentTreeView`, `IDocumentTabService`, and an `ILlmBackend` implementation).
  - Creates and shows `LlmChatWindow` (XAML UI in `LlmChat/LlmChatWindow.xaml`), owned by the main window.

## Project Snapshot & In-Memory Cache

- On `LlmChatViewModel` construction, the current assemblies are analyzed via `ProjectAnalysisFactory.Create(documentTreeView)`.
- This uses the shared `AnalyzedProject` model (`Documents/Tabs/ProjectAnalysis.cs`) that was also introduced for the JSON export:
  - `AnalyzedProject` → array of `AnalyzedModule` → array of `AnalyzedType` → arrays of `AnalyzedMember` (fields/methods/properties/events).
- The resulting `AnalyzedProject` is kept in-memory as the searchable cache for the whole chat session (no file writes).

## Chat Loop & LLM Backend

- The chat window binds to:
  - `Messages`: `ObservableCollection<LlmChatMessageViewModel>` representing the transcript (`Role` + `Content` + optional `SearchResults`).
  - `CurrentUserMessage`: text box content.
  - `IncludedModulesText`: advanced filter input (comma-separated module-name substrings to include).
  - `ExcludedModulesText`: advanced filter input (comma-separated module-name substrings to exclude).
  - `SendMessageCommand`: triggered by the **Send** button.
  - `RefineSearchCommand`: triggered by the **Refine** button.
- On send:
  - The view model adds a user message to `Messages` and clears the input.
  - Builds an `LlmChatContext` (current `AnalyzedProject` + message history).
  - Calls `ILlmBackend.GetResponseAsync(context, cancellationToken)`.
- Two backends are provided:
  - `NullLlmBackend`: a stub that generates a placeholder assistant reply and infers `SearchKeywords` by tokenizing the last user message.
  - `PythonLlmBackend`: a bridge to a Python script (e.g., OpenAI client):
    - Serializes an `LlmBackendRequest` (conversation + analyzed project) as JSON to stdin.
    - Expects a JSON `LlmBackendResponse` on stdout with:
      - `AssistantMessage` (free-form text for the UI).
      - `SearchKeywords` (keyword *paths* used by the search engine).
      - `ExcludedModules` (array of module-name substrings to skip in search).
    - Internally, the Python backend can also return a richer `keywords` tree
      (keyword + parent + layer), which it converts into `SearchKeywords`
      before sending the response back to dnSpy.

## Search Over Analyzed Project

- `LlmSearchEngine.Search(AnalyzedProject, keywords, includedModules, excludedModules, excludedTypes)` scans the cached model:
  - `keywords` is an array of *paths* such as
    `"Player Health MaxHealth"` or `"Player Attack AttackSpeed"`.
  - Each path is split into tokens; for a symbol to match a given *fuzzy*
    path, **all** tokens from that path must be present (case-insensitive)
    in the symbol's `Name` or `FullName`.
  - Single-token paths (e.g. just `"Player"`) are now used, they are no
    longer ignored when multi-token paths are present:
    - In normal **chat** mode, they behave like any other fuzzy path
      (substring match against names / full names).
    - In **DAT / automation mode**, single-token paths are treated as
      *exact type-name* queries, while multi-token paths stay fuzzy:
      - All one-token paths are collected (e.g. `"Money"`, `"Player"`,
        `"Weapon"` from `["Money", "Player", "Weapon", "Play Effect"]`).
      - For each such token, only **types** whose simple name or last
        `FullName` segment equals the token (case-insensitive) are
        returned (e.g. `Player` or `MyGame.Player` match `"player"`).
      - Types whose names only *contain* the token as a substring, such
        as `MyPlayer`, `LocalPlayer`, or `Remoteplayer`, are **not**
        returned for that exact-token query.
      - Multi-token paths such as `"Play Effect"` continue to use the
        fuzzy matching rule and can match both types and members.
  - `includedModules` is an array of substrings; if non-empty, only modules
    whose names contain at least one of these substrings are considered.
  - `excludedModules` is an array of substrings; any module whose name
    contains one of these substrings is skipped entirely.
  - `excludedTypes` is an array of substrings; any type whose `FullName`
    contains one of these substrings is skipped entirely (along with its
    fields/methods/properties/events).
  - Returns an array of `LlmSearchResult` with `Kind`, `Name`, `FullName`,
    `ModuleName`, and optional `Signature`.
- `LlmSearchFormatter.FormatResults(...)` only emits a short header line
  (`"Search results from dnSpy analysis cache (click an item below to navigate):"`),
  while each individual `LlmSearchResult` exposes a `DisplayText` property
  that is used by the UI as the clickable label.

## Search Result Rendering & Navigation

- `LlmChatMessageViewModel` can optionally carry a `SearchResults` array
  alongside `Role` and `Content`:
  - The textual results summary is still stored in `Content` as a
    `system-search` message.
  - The structured `LlmSearchResult[]` is stored in `SearchResults` and is
    used by the UI to build clickable entries under that message.
- `LlmChatWindow.xaml` renders each message as:
  - A bold `Role` label.
  - The `Content` text block, inside a colored “bubble” chosen by `LlmChatRoleToBrushConverter`
    based on the message `Role` (`user`, `assistant`, `system-search`).
  - An optional `ItemsControl` bound to `SearchResults`, where each item is a
    `Hyperlink` (`DisplayText` as the label) that calls back into the window’s
    `SearchResultHyperlink_Click` handler.
- The click handler in `LlmChatWindow.xaml.cs`:
  - Retrieves the clicked `LlmSearchResult` from the hyperlink’s
    `DataContext`.
  - Forwards it to `LlmChatViewModel.NavigateToSearchResult` and logs some
    `[debug] ...` messages into the `LLM Logs` tool window so navigation
    can be debugged.
- `LlmChatViewModel.NavigateToSearchResult` now:
  - Finds the matching dnlib module in the current `IDocumentTreeView` by
    comparing `ModuleName` with the loaded modules.
  - Resolves the corresponding dnlib definition (`TypeDef`, `MethodDef`,
    `FieldDef`, `PropertyDef`, or `EventDef`) by matching the `FullName`
    of the target type/member.
  - When a definition is found, it calls
    `IDocumentTabService.FollowReference(definition)`:
    - This reuses dnSpy’s standard reference-navigation pipeline
      (`TreeNodeReferenceDocumentTabContentProvider` etc.).
    - If *Decompile full type* is enabled in settings, the editor opens
      the full declaring type as context and moves the caret to the exact
      member (e.g., `MyClass::MyFunc`) inside that type.
    - The behavior is identical to clicking a reference hyperlink in the
      decompiled code: existing tabs, navigation history, and caret
      centering all behave consistently.

## Advanced Include/Exclude Filtering

- The bottom of `LlmChatWindow.xaml` exposes an advanced filter section:
  - A **Refine** button (`RefineSearchCommand`).
  - A **Debug mode** checkbox (`IsDebugMode` on the view model):
    - When enabled, dnSpy sends `DebugMode: true` in the backend request.
    - The Python backend (`llm_chat_backend.py`) skips Claude/OpenAI and
      simply echoes the last user message as a single keyword path in
      `SearchKeywords`, so you can drive searches directly without using
      LLM tokens.
  - An `Include modules` text box (`IncludedModulesText`) where the user can
    enter comma-separated substrings; if any are present, only modules whose
    names contain at least one of these substrings are included in search.
  - An `Exclude modules` text box (`ExcludedModulesText`) where the user can
    enter comma-separated substrings (for example: `Unity`, `System`, `Engine`).
  - An editable `ComboBox` bound to `ModuleNames` (all currently loaded module
    names). Typing filters the list; selecting a module appends it to
    either `IncludedModulesText` or `ExcludedModulesText` depending on which
    drop-down is used, via `AppendIncludedModule(...)` /
    `AppendExcludedModule(...)`.
  - An `Exclude types` text box (`ExcludedTypesText`) where the user can
    enter comma-separated substrings of type names/FullNames (e.g. `Player`,
    `Enemy`, `HealthSystem`).
  - An editable `ComboBox` bound to `TypeSuggestions`. The view model does
    not pre-cache all type names; instead, when `TypeSearchText` has at least
    3 characters, it searches `AnalyzedProject` for matching type full names
    and populates `TypeSuggestions` with up to 100 matches. Selecting a type
    appends it to either `IncludedTypesText` or `ExcludedTypesText` depending
    on which drop-down is used, via `AppendIncludedType(...)` /
    `AppendExcludedType(...)`.
- On send:
  - The backend still returns `SearchKeywords` and optional `ExcludedModules`.
  - `LlmChatViewModel`:
    - Stores the latest `SearchKeywords` and backend-specified `ExcludedModules`
      in `lastSearchKeywords` / `lastBackendExcludedModules`.
    - Parses `ExcludedModulesText` and `ExcludedTypesText` into `userExcluded`
      arrays.
    - Merges backend- and user-specified module filters (distinct,
      case-insensitive) and passes the combined module list plus the type
      exclusions into `LlmSearchEngine.Search(...)`.
    - Appends the resulting clickable search results as before.
- On **Refine**:
  - If there is a previous search (`lastSearchKeywords`), the view model:
    - Rebuilds the combined excluded-modules list from
      `lastBackendExcludedModules` + current `ExcludedModulesText`.
    - Parses the current `ExcludedTypesText` into a type-exclusion list.
    - Re-runs `LlmSearchEngine.Search(...)` with the same keywords but the
      updated module and type exclusions.
    - Adds a new `system-search` message summarizing the refined results (or
      a short message if no results remain).
    - Logs the applied exclusions (modules and types) into `LLM Logs` so the
      refinement step can be debugged.

## Build Helper Script

- `build_and_open_force.ps1` provides a “strict” build+run path for iterating
  on the LLM chat feature:
  - Calls `dotnet build dnSpy\dnSpy.sln -c Release --no-restore` and fails
    fast if the build fails (no reuse of stale binaries).
  - Verifies and then launches
    `dnSpy\dnSpy\dnSpy\bin\Release\net5.0-windows\dnSpy.exe`.
  - Optional `-WaitForClose` parameter waits for the dnSpy process to exit.
