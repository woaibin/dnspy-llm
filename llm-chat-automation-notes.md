# LLM Chat Automation – Current Implementation Notes (Fork)

This file captures the **actual behavior** of the current fork as implemented in code, independent of the original planning document.

## 1. High-level wiring

- dnSpy UI entry points:
  - **LLM Chat window** (`LlmChatWindow` / `LlmChatViewModel`):
    - Has an **“Automation mode (use external automation server/tooling)”** checkbox.
    - When checked, passes `IsAutomationMode = true` into `LlmChatContext`.
  - **Start LLM automation server** menu item (`StartLlmAutomationServerCommand` in `ViewCommands.cs`):
    - Builds an `AnalyzedProject` via `ProjectAnalysisFactory.Create(documentTreeView)`.
    - Serializes it to JSON with `DataContractJsonSerializer`.
    - Starts `python llm_automation_server.py` in the dnSpy `baseDir`.
    - Writes the JSON into the server process’s stdin.
    - Shows `LlmAutomationWindow` with URL `http://127.0.0.1:5015/` and basic status/events text.

- Processes involved:
  - `dnSpy.exe` (WPF app).
  - `python llm_chat_backend.py` (LLM chat backend / keyword generator).
  - `python llm_automation_server.py` (HTTP server for automation search).

## 2. Backend request/response (llm_chat_backend.py)

- **Request shape** (`LlmBackendRequest`, serialized from dnSpy):
  - `Messages`: array of `{ Role, Content }` from the chat transcript.
  - `Project`:
    - In **chat/file** modes: full `AnalyzedProject` (possibly compacted to one type in file mode).
    - In **automation** mode: an **empty** `AnalyzedProject` stub; the real project graph lives only inside the automation HTTP server.
  - `Mode`: `"chat"`, `"automation"`, or `"file"`.

- **Mode selection in dnSpy**:
  - `LlmChatViewModel` constructs `LlmChatContext(project, messages, isAutomationMode)`.
  - `LlmBackendRequest.Create(...)` copies `IsAutomationMode` to `Mode`:
    - `"chat"` – normal chat.
    - `"automation"` – chat with automation enabled.
    - `"file"` – special file-analysis requests (not directly relevant to automation).

- **Backend behavior by mode**:

  ### 2.1 Chat / file modes

  - Builds `project_overview` string (or a focused `build_type_outline` in file mode).
  - Calls `call_openai_structured(last_user, project_overview, mode=Mode)`:
    - If `POE_ENABLED` is on, uses Poe/OpenAI (Claude) via `openai.OpenAI` client.
    - Otherwise uses a local heuristic (`fallback_keywords`) and returns JSON.
  - `call_openai_structured` returns:
    - `AssistantMessage`: free-form assistant text.
    - `SearchKeywords`: list/paths for dnSpy search.
    - `ExcludedModules`: substrings for module filtering.
  - dnSpy:
    - Shows `AssistantMessage` as a chat bubble.
    - Shows `SearchKeywords` in a `system-search` line.
    - Runs `LlmSearchEngine.Search(...)` to generate clickable `LlmSearchResult` items from the in-process `AnalyzedProject`.

  ### 2.2 Automation mode (current fork)

  - `Mode == "automation"` short-circuits `call_openai_structured`:
    - **Never** calls Poe/OpenAI.
    - Logs: `mode=automation, forcing offline heuristic (no Poe/OpenAI) and no assistant text.`
    - Uses `fallback_keywords(last_user)` → `build_keyword_paths(...)` to compute keyword paths.
    - Returns:
      - `AssistantMessage`: `""` (empty string).
      - `SearchKeywords`: the keyword paths.
      - `ExcludedModules`: `[]` (currently none).
  - After that, the backend:
    - Calls `ping_automation_server(base_url="http://127.0.0.1:5015")`:
      - Uses a `_without_http_proxy()` context manager to temporarily clear `HTTP_PROXY`, `HTTPS_PROXY`, `http_proxy`, `https_proxy` so localhost calls bypass any Poe proxy.
      - Logs whether `/health` is reachable and the returned status.
    - Calls `automation_search_with_keywords(...)`:
      - For each keyword path (string):
        - Builds `GET /api/search/broad?pattern=...&maxResults=...`.
        - Uses `_without_http_proxy()` again to hit `http://127.0.0.1:5015` directly.
        - Parses the JSON array response, tagging each hit with `_pattern`.
      - Logs each GET and a summary:
        - `automation_search_with_keywords(): collected N total hits from automation server`.
      - Currently, the collected hits are **not** converted to clickable items or appended to any assistant text; they exist only in logs.
  - Result returned to dnSpy in automation mode:
    - `AssistantMessage` is empty ⇒ no assistant bubble added.
    - `SearchKeywords` still flow into:
      - The `system-search` “Search keyword paths: ...” line.
      - A `LlmSearchEngine.Search(...)` call over the in-memory `AnalyzedProject`, generating `LlmSearchResult` items as usual.
    - Automation HTTP hits do **not** appear directly in the UI yet.

## 3. Automation HTTP server (llm_automation_server.py)

- **Startup JSON**:
  - Reads stdin once at startup.
  - Supports:
    - `{ "Modules": [ ... ] }` → `PROJECT = obj`.
    - `{ "Project": { "Modules": [ ... ] }, ... }` → `PROJECT = obj["Project"]`.
  - If shape doesn’t match, logs and falls back to `PROJECT = { "Modules": [] }`.

- **Data model expectations** (roughly matches `AnalyzedProject`):
  - Each module:
    - `Name`, `AssemblyFullName`, `FileName`.
    - `AssemblyPath`/`ModuleFilePath` may be present.
    - `Types`: array of type dicts.
  - Each type:
    - `Name`, `Namespace`, `FullName`.
    - `Fields`, `Methods`, `Properties`, `Events`, each an array of member dicts:
      - `Name`, `FullName`, `Signature`, `MemberType`, `IsStatic`, `IsPublic`.

- **Endpoints**:
  - `/health`:
    - Always returns `{"status": "ok"}`.
  - `/api/search/broad`:
    - Query:
      - `pattern` – raw regex string (case-insensitive).
      - `maxResults` – optional, capped at 500.
    - Search behavior:
      - Compiles `pattern` with `re.IGNORECASE`.
      - For each module in `PROJECT.Modules`:
        - If `pattern` matches module `Name` or `AssemblyFullName`, adds a `"module"` hit.
        - For each type in that module:
          - If `pattern` matches type `Name` or `FullName`, adds a `"type"` hit.
          - For each member of that type:
            - If `pattern` matches member `Name`, `FullName`, or `Signature`, adds a `"member"` hit.
      - Stops when `maxResults` reached.
    - Logging (added in this fork):
      - After each search: `broad_search(): pattern='...', max_results=..., hits=N`.
    - Response: array of:
      - `kind`: `"module" | "type" | "member"`.
      - `name`, `fullName`, `moduleName`, `assemblyPath`, `signature`.
  - `/api/lookup/clear`:
    - Query:
      - `identifier`: string, usually a type `FullName`.
    - Behavior:
      - Normalizes identifier (strip, trim quotes).
      - Exact matches on type `FullName` preferred; falls back to case-insensitive contains.
      - Returns:
        - `status: "ok"` with a single match.
        - `status: "ambiguous"` with `candidates` array.
        - `status: "not_found"` when nothing matches.
    - Logging (added):
      - `clear_lookup(): identifier='...', status=ok, module=..., type=...`.
      - Or `status=not_found` / `status=ambiguous` with candidate count.

- **Logging sink**:
  - All server logs go to **stderr** of the `llm_automation_server.py` process.
  - They are not yet surfaced in `LlmAutomationWindow`; you see them only if you capture or view the server’s console output.

## 4. What automation currently does *not* do

- Does **not** call Poe/OpenAI (Claude) when `Mode == "automation"`.
- Does **not** generate any assistant-style explanation messages in automation mode.
- Does **not** turn automation HTTP hits into clickable results in the chat UI; only the standard `LlmSearchEngine` results appear there.
- Does **not** yet have a separate “Claude orchestrator” process that owns:
  - Talking to Claude with a tools spec.
  - Calling `/api/search/broad` and `/api/lookup/clear` directly from Claude/tooling.
  - Returning a structured JSON summary for dnSpy to display.

## 5. Intended future direction (high level)

- **Split chat and automation cleanly**:
  - Keep `llm_chat_backend.py` strictly for interactive chat/file analysis (can use Poe/OpenAI).
  - Move automation into a separate orchestrator (Claude-only) that:
    - Accepts a user prompt + compact project summary.
    - Uses tools to call the automation HTTP server:
      - `/api/search/broad` for broad searches.
      - `/api/lookup/clear` for precise type/module resolution.
    - Returns a clean JSON `findings` payload.
  - Have dnSpy’s automation UI:
    - Launch the orchestrator process.
    - Show the `findings` and wire them to `NavigateToSearchResult` without going through `llm_chat_backend.py` at all.

- **Keep automation independent of Poe/OpenAI**:
  - Automation should work entirely offline as long as:
    - The analyzed project exists.
    - `llm_automation_server.py` is running.
  - Claude/Poe becomes an optional external helper, not a dependency for automation.
