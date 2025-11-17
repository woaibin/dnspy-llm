# LLM Chat Feature Logic Overview (dnSpy Integration)

This document summarizes how the LLM chat system in this repository works, from menu entry to search over the analyzed project model.

## Entry Points & UI Flow

- Top-level menu: a new **LLM Chat** menu is registered in `AppMenus.cs` using `APP_MENU_LLMCHAT_GUID` / `ORDER_APP_MENU_LLMCHAT`.
- Menu item: **Start a new LLM chat** (`StartLlmChatCommand` in `MainApp/ViewCommands.cs`) is exported under `GROUP_APP_MENU_LLMCHAT_COMMANDS`.
- When the item is clicked, the command:
  - Verifies there are loaded modules in `IDocumentTreeView`.
  - Creates an `LlmChatViewModel` (passing `IDocumentTreeView` and an `ILlmBackend` implementation).
  - Creates and shows `LlmChatWindow` (XAML UI in `LlmChat/LlmChatWindow.xaml`), owned by the main window.

## Project Snapshot & In-Memory Cache

- On `LlmChatViewModel` construction, the current assemblies are analyzed via `ProjectAnalysisFactory.Create(documentTreeView)`.
- This uses the shared `AnalyzedProject` model (`Documents/Tabs/ProjectAnalysis.cs`) that was also introduced for the JSON export:
  - `AnalyzedProject` → array of `AnalyzedModule` → array of `AnalyzedType` → arrays of `AnalyzedMember` (fields/methods/properties/events).
- The resulting `AnalyzedProject` is kept in-memory as the searchable cache for the whole chat session (no file writes).

## Chat Loop & LLM Backend

- The chat window binds to:
  - `Messages`: `ObservableCollection<LlmChatMessageViewModel>` representing the transcript (`role` + `content`).
  - `CurrentUserMessage`: text box content.
  - `SendMessageCommand`: triggered by the **Send** button.
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

- `LlmSearchEngine.Search(AnalyzedProject, keywords, excludedModules)` scans the cached model:
  - `keywords` is an array of *paths* such as
    `"Player Health MaxHealth"` or `"Player Attack AttackSpeed"`.
  - Each path is split into tokens; for a symbol to match, **all** tokens
    from **at least one** path must be present (case-insensitive) in the
    symbol's `Name` or `FullName`.
  - Single-token paths (e.g., just `"Player"`) are ignored when there are
    any multi-token paths available, to avoid overly fuzzy matches.
  - `excludedModules` is an array of substrings; any module whose name
    contains one of these substrings is skipped entirely.
  - Returns an array of `LlmSearchResult` with `Kind`, `Name`, `FullName`,
    `ModuleName`, and optional `Signature`.
- `LlmSearchFormatter.FormatResults(...)` now only emits a short header line
  (`"Search results from dnSpy analysis cache (click an item below to navigate):"`),
  while each individual `LlmSearchResult` exposes a `DisplayText` property
  that is used by the UI as the clickable label.

## Search Result Rendering & Navigation

- `LlmChatMessageViewModel` can optionally carry a `SearchResults` array
  alongside `Role` and `Content`:
  - The textual results summary is still stored in `Content` as a
    `system-search` message.
  - The structured `LlmSearchResult[]` is stored in `SearchResults` and is
    used by the UI to build clickable entries.
- `LlmChatWindow.xaml` renders each message as:
  - A bold `Role` label.
  - The `Content` text block.
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
  - Resolves the corresponding `DocumentTreeNodeData` by matching the
    `FullName` of the target type/member.
  - When a node is found, it first navigates to the declaring type and then
    to the specific member:
    - Uses `GetDeclaringType(...)` to map `TypeNode`, `MethodNode`,
      `FieldNode`, `PropertyNode`, and `EventNode` back to their
      `TypeDef`.
    - Selects the type node in the `IDocumentTreeView`.
    - Selects the final member node and calls `Activate()` on it.
  - This reuses `DocumentTabService`’s existing selection logic so the
    main code editor behaves as if the user navigated via the Assembly
    Explorer tree.

## Build Helper Script

- `build_and_open_force.ps1` provides a “strict” build+run path for iterating
  on the LLM chat feature:
  - Calls `dotnet build dnSpy\dnSpy.sln -c Release --no-restore` and fails
    fast if the build fails (no reuse of stale binaries).
  - Verifies and then launches
    `dnSpy\dnSpy\dnSpy\bin\Release\net5.0-windows\dnSpy.exe`.
  - Optional `-WaitForClose` parameter waits for the dnSpy process to exit.
