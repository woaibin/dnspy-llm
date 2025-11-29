#!/usr/bin/env python
"""
Simple example backend for dnSpy's LLM chat.

It reads a JSON LlmBackendRequest from stdin and writes a JSON
LlmBackendResponse to stdout:

Request shape (simplified):
{
  "Messages": [{ "Role": "user|assistant|system-search", "Content": "..." }, ...],
  "Project": { "Modules": [ ... ] }
}

Response shape:
{
  "AssistantMessage": "text to show in the chat",
  "SearchKeywords": ["keyword1", "keyword2"],
  "ExcludedModules": ["System", "UnityEngine.UI"]
}
"""

import json
import os
import sys
from typing import Any, Dict, List
import traceback
import time
import urllib.error
import urllib.request
import urllib.parse
from contextlib import contextmanager
import subprocess
import shutil


# Default Poe/OpenAI API key used if environment variables are not set.
# You can override this at runtime by setting POE_API_KEY or OPENAI_API_KEY.
DEFAULT_POE_API_KEY = "uQA9T24fMZ10fF05WJi79MqlShUGH9ZMM7Ip1dzXgho"

LOG_FILE = os.path.join(os.path.dirname(__file__), "py_llm_backend.log")
REQUEST_DUMP_FILE = os.path.join(os.path.dirname(__file__), "py_llm_backend_request.json")
CLAUDE_STDOUT_FILE = os.path.join(os.path.dirname(__file__), "claude_stdout_raw.txt")
_PROXY_VARS = ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy")
_LOG_INITIALIZED = False


def log(msg: str) -> None:
    """Append a timestamped message to the backend log file."""
    global _LOG_INITIALIZED
    try:
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        line = f"[{ts}] {msg}\n"
        mode = "a" if _LOG_INITIALIZED else "w"
        with open(LOG_FILE, mode, encoding="utf-8") as f:
            f.write(line)
        _LOG_INITIALIZED = True
    except Exception:
        # Never let logging break the backend.
        pass


@contextmanager
def _without_http_proxy() -> Any:
    """
    Temporarily disable HTTP(S) proxy environment variables.

    This is used for localhost calls (e.g., the automation HTTP server)
    so that they don't get routed through the Poe/OpenAI proxy.
    """
    saved: Dict[str, str] = {}
    try:
        for name in _PROXY_VARS:
            if name in os.environ:
                saved[name] = os.environ[name]
                del os.environ[name]
        yield
    finally:
        for name, value in saved.items():
            os.environ[name] = value



def _ensure_claude_env() -> None:
    """
    Ensure required Claude / Anthropic environment variables are present
    before invoking the Claude CLI. These can be overridden by explicitly
    setting them in the environment; otherwise we fall back to the values
    configured for this dnSpy fork.
    """
    default_vars = {
        "ANTHROPIC_AUTH_TOKEN": "sk-OWMXwWM9n3a9ZP0qsnZDfdrsBtRZLKtaS9C0F5ly7iid08rr",
        "ANTHROPIC_BASE_URL": "https://yunwu.ai",
    }
    for key, value in default_vars.items():
        if not os.getenv(key):
            os.environ[key] = value
            log(f"_ensure_claude_env(): set {key} from backend defaults.")


def read_request() -> Dict[str, Any]:
    """Read the JSON LlmBackendRequest from stdin."""
    log("read_request(): start")
    stdin = sys.stdin.buffer
    if stdin.isatty():
        log("read_request(): stdin is TTY, returning empty request")
        return {}

    raw_bytes = stdin.read()
    log(f"read_request(): got {len(raw_bytes)} bytes from stdin")

    if not raw_bytes.strip():
        log("read_request(): empty/whitespace input, returning empty request")
        return {}

    try:
        data = raw_bytes.decode("utf-8", errors="replace")
    except Exception as ex:
        log(f"read_request(): failed to decode stdin as utf-8: {ex!r}")
        # Fall back to default text decoding as a last resort.
        data = raw_bytes.decode(errors="replace")

    # Dump the raw request payload (truncated) to a file so we can inspect
    # what dnSpy sent without writing huge data or failing on bad surrogates.
    try:
        max_dump_bytes = 1_000_000  # ~1MB is plenty for debugging
        dump = data
        if len(dump) > max_dump_bytes:
            dump = dump[:max_dump_bytes]
        with open(REQUEST_DUMP_FILE, "w", encoding="utf-8", errors="replace") as f:
            f.write(dump)
        log(f"read_request(): raw request written to {REQUEST_DUMP_FILE}")
    except Exception as ex:
        log(f"read_request(): failed to write request dump: {ex!r}")
    if not data.strip():
        log("read_request(): empty/whitespace input, returning empty request")
        return {}
    raw = json.loads(data)
    log("read_request(): JSON loaded successfully")

    # Lightweight summary of the request so we can correlate user questions
    # with Claude CLI behavior in the logs without dumping everything.
    try:
        mode = raw.get("Mode", "chat")
        messages = raw.get("Messages") or []
        last_user = ""
        for m in reversed(messages):
            if isinstance(m, dict) and m.get("Role") == "user":
                last_user = (m.get("Content") or "") or ""
                break
        if len(last_user) > 200:
            last_user = last_user[:200] + "... (truncated)"
        log(f"read_request(): summary mode={mode!r}, last_user={last_user!r}, messages={len(messages)}")
    except Exception as ex:
        log(f"read_request(): failed to log request summary: {ex!r}")

    return sanitize_obj(raw)


def sanitize_text(value: str) -> str:
    """
    Ensure a string is safe to send to JSON/HTTP APIs by stripping or replacing
    any invalid surrogate code points while preserving valid Unicode (including
    CJK and other non-ASCII text).
    """
    # Encode with 'replace' to drop any lone surrogates, then decode back.
    return value.encode("utf-8", "replace").decode("utf-8")


def sanitize_obj(obj: Any) -> Any:
    """Recursively sanitize all strings within a nested dict/list structure."""
    if isinstance(obj, str):
        return sanitize_text(obj)
    if isinstance(obj, list):
        return [sanitize_obj(x) for x in obj]
    if isinstance(obj, dict):
        return {k: sanitize_obj(v) for k, v in obj.items()}
    return obj


def extract_last_user_message(messages: List[Dict[str, Any]]) -> str:
    """Return the content of the last user message in the transcript."""
    for msg in reversed(messages):
        if msg.get("Role") == "user":
            return msg.get("Content", "") or ""
    return ""


def build_project_overview(project: Dict[str, Any]) -> str:
    """
    Create a compact text overview of the analyzed project for the prompt.

    Intentionally only lists module names, not individual types or members,
    to keep the prompt small and focused. The detailed search is done on the
    dnSpy side using the structured keywords the model returns.
    """
    modules = project.get("Modules") or []
    lines: List[str] = []

    for mod in modules:
        mod_name = mod.get("Name") or mod.get("FullName") or "<unknown-module>"
        lines.append(f"Module: {mod_name}")

    return "\n".join(lines)


def _extract_type_name_from_prompt(text: str) -> str:
    """
    Try to extract a type name from the user prompt.

    We look for a quoted identifier first (e.g. 'FxPlayer'), otherwise
    we fall back to the first PascalCase-like token.
    """
    import re

    m = re.search(r"'([A-Za-z_][A-Za-z0-9_\.]*)'", text)
    if m:
        return m.group(1)

    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text)
    for t in tokens:
        if len(t) > 1 and t[0].isupper():
            return t

    return ""


def build_type_outline(project: Dict[str, Any], last_user: str) -> str:
    """
    Build a compact outline of a single type:
      - Type name and namespace
      - Base type (inheritance root)
      - Names and signatures of fields, methods, properties, and events

    No method bodies or other implementation details are included.
    """
    type_name = _extract_type_name_from_prompt(last_user)
    if not type_name:
        return ""

    modules = project.get("Modules") or []
    best_mod: Dict[str, Any] | None = None
    best_type: Dict[str, Any] | None = None

    # Try to find an exact or suffix match for the type name
    for mod in modules:
        types = mod.get("Types") or []
        for t in types:
            name = (t.get("Name") or "").strip()
            full = (t.get("FullName") or "").strip()
            if not name and not full:
                continue
            if name == type_name or full == type_name or full.endswith("." + type_name):
                best_mod = mod
                best_type = t
                break
        if best_type is not None:
            break

    if best_type is None:
        return ""

    mod_name = best_mod.get("Name") or "<unknown-module>"
    ns = best_type.get("Namespace") or ""
    full_name = best_type.get("FullName") or type_name
    base_type = best_type.get("BaseType") or ""

    lines: List[str] = []
    header = f"Module={mod_name} | Type={full_name}"
    if base_type:
        header += f" | BaseType={base_type}"
    if ns:
        header += f" | Namespace={ns}"
    lines.append(header)

    def add_members(kind_label: str, members_key: str, max_count: int = 80, max_sig_len: int = 80) -> None:
        members = best_type.get(members_key) or []
        items: List[str] = []
        count = 0
        for m in members:
            name = (m.get("Name") or "").strip()
            sig = (m.get("Signature") or "").strip()
            if not name and not sig:
                continue
            if max_sig_len > 0 and len(sig) > max_sig_len:
                sig = sig[:max_sig_len] + "..."
            if sig:
                items.append(f"{name}:{sig}")
            else:
                items.append(name)
            count += 1
            if count >= max_count:
                break
        if items:
            # Single compact line per kind, eg:
            # Fields: health:int; maxHealth:int; ...
            lines.append(f"{kind_label}: " + "; ".join(items))

    add_members("Fields", "Fields", max_count=80)
    add_members("Methods", "Methods", max_count=120)
    add_members("Properties", "Properties", max_count=80)
    add_members("Events", "Events", max_count=40)

    return "\n".join(lines)


def fallback_keywords(text: str) -> List[str]:
    """Simple local keyword extractor used if OpenAI is unavailable."""
    tokens = [
        t.strip(".,;:()[]{}<>\"'").lower()
        for t in text.split()
        if t.strip()
    ]
    seen = set()
    keywords: List[str] = []
    for t in tokens:
        if t and t not in seen:
            seen.add(t)
            keywords.append(t)
    return keywords[:8]


def build_keyword_paths(keywords: List[str], last_user: str) -> List[str]:
    """
    Turn a flat list of keywords into path-style phrases.

    If the model already returns phrases (items containing spaces), they are
    kept as-is. If it returns only single tokens like
    ['Player', 'Health', 'AttackSpeed'], we synthesize paths such as:
      ['Player Health', 'Player AttackSpeed']
    using the first capitalized token (or first token) as the root.
    """
    if not keywords:
        return []

    # If we already have phrases, assume the model followed the contract.
    if any(" " in kw for kw in keywords):
        return keywords

    # Pick a root token: first capitalized keyword, otherwise the first one.
    root = None
    for kw in keywords:
        if kw and kw[0].isupper():
            root = kw
            break
    if root is None:
        root = keywords[0]

    attrs = [k for k in keywords if k != root]

    paths: List[str] = []

    # Always keep a broad path for the root alone.
    paths.append(root)

    # Add root+attribute paths like "Player Health", "Player AttackSpeed".
    for attr in attrs:
        paths.append(f"{root} {attr}")

    return paths


def build_paths_from_tree(tree: List[Dict[str, Any]]) -> List[str]:
    """
    Build root-to-leaf keyword paths from a simple keyword tree.

    Each node in ``tree`` is expected to be a dict with:
      { "keyword": str, "parent": str | null, "layer": int }

    The result is a list of space-joined paths, e.g.:
      ["Player Health Recover", "Player Attack Power", ...]
    """
    if not tree:
        return []

    # Normalize structure and filter out invalid entries.
    nodes: List[Dict[str, Any]] = []
    for n in tree:
        if not isinstance(n, dict):
            continue
        kw = n.get("keyword")
        if not isinstance(kw, str) or not kw.strip():
            continue
        parent = n.get("parent")
        if parent is not None and not isinstance(parent, str):
            parent = None
        nodes.append({"keyword": kw.strip(), "parent": parent})

    if not nodes:
        return []

    # Build adjacency map: parent keyword -> list of child keywords.
    children: Dict[Any, List[str]] = {}
    parent_of: Dict[str, Any] = {}
    for n in nodes:
        parent = n["parent"]
        kw = n["keyword"]
        children.setdefault(parent, []).append(kw)
        parent_of[kw] = parent

    roots = children.get(None, []) + children.get("", [])
    if not roots:
        # Fallback: treat all nodes as roots.
        roots = [n["keyword"] for n in nodes]

    paths: List[str] = []

    def dfs(current_kw: str, acc: List[str], parent_kw: Any) -> None:
        # If the child keyword contains the parent keyword as a prefix
        # (e.g., PlayerAttack / AttackSpeed), remove the parent portion
        # from the child token to avoid duplicated words in the path.
        display_kw = current_kw
        if isinstance(parent_kw, str) and parent_kw:
            lower_parent = parent_kw.lower()
            lower_child = current_kw.lower()
            if lower_child.startswith(lower_parent):
                trimmed = current_kw[len(parent_kw) :].lstrip("_ .")
                if trimmed:
                    display_kw = trimmed

        acc.append(display_kw)
        kids = children.get(current_kw)
        if not kids:
            paths.append(" ".join(acc))
        else:
            for child in kids:
                dfs(child, acc[:], current_kw)

    for root in roots:
        dfs(root, [], parent_of.get(root))

    return paths


def _strip_markdown_fence(text: str) -> str:
    """Strip a leading/trailing ``` code fence if present."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped

    # Remove first fence line
    first_newline = stripped.find("\n")
    if first_newline != -1:
        stripped = stripped[first_newline + 1 :]
    # Remove trailing fence
    end = stripped.rfind("```")
    if end != -1:
        stripped = stripped[:end]
    return stripped.strip()


def call_openai_structured(last_user: str, project_overview: str, *, mode: str = "chat") -> Dict[str, Any]:
    """
    Call OpenAI (via Poe-compatible endpoint) to get an assistant reply,
    structured search keywords, and module-exclusion hints.

    The model is instructed to respond with JSON of the form:
      {
        "assistant_message": "...",
        "search_keywords": ["...", ...],
        "excluded_modules": ["...", ...],
        "keywords": [
          { "keyword": "Player", "parent": null, "layer": 0 },
          { "keyword": "Health", "parent": "Player", "layer": 1 },
          { "keyword": "Attack", "parent": "Player", "layer": 1 },
          { "keyword": "Power", "parent": "Attack", "layer": 2 }
        ]
      }
    """
    # In automation mode, delegate to the local Claude CLI instead of Poe/OpenAI.
    # This lets Claude directly drive the automation HTTP server using its own
    # tool / HTTP capabilities, while we simply pass through its structured JSON
    # response into dnSpy.
    if mode == "automation":
        log("call_openai_structured(): mode=automation, calling local Claude CLI for structured automation response.")

        def _call_claude_cli_automation(prompt_user: str, prompt_overview: str) -> Dict[str, Any]:
            # Keep the API description short and precise so the model
            # focuses on using the automation server effectively.
            # Use an explicit, absolute path in the instructions so the model
            # doesn't have to reason about "current working directory".
            base_dir = os.path.dirname(__file__)
            temp_prompt_path = os.path.join(base_dir, "temp_prompts.md")
            result_json_path = os.path.join(base_dir, "claude_automation_result.json")
            result_json_display = result_json_path.replace("\\", "/")

            system_prompt = (
                "# Overall Characteristics"
                "You are a professional Unity/.NET reverse-engineering assistant.\n"
                "You are here to help user analyze the unity game with the info and intel it wants.\n"

                "# Tools"
                "You are provided with a HTTP look up server to look up the unity symbols according to the user's request"
                "A local automation HTTP server is available at http://127.0.0.1:5015.\n"
                "It exposes three endpoints:\n"
                "  - GET /api/search/broad?pattern=...&maxResults=...       : regex search over modules, types, and members.\n"
                "  - GET /api/lookup/clear?identifier=...                   : resolve an identifier to an exact type.\n"
                "  - GET /api/search/typeRefs?identifier=...&maxResults=... : find types that *use* a given spec type via base type or member signatures.\n"
                "Use these APIs as needed to locate gameplay-relevant types and members.\n"
                
                "# Overall Workflow\n"
                "1. So First of all, ure gonne intepret the user's request, like if user's tryna say attack power, u might wanna intepret it to possible classes names modules types and shits.\n"
                "2. Then, u should go use the tool i provide u, like http://127.0.0.1:5015/api/search/broad?pattern=.*attack.*&maxResults=100\n"
                "3. By retrieving the result, u can consider to refine based on the first results or broad search again with more results to locate the ones we want\n"
                "4. in the mean time, u can use the clear search api to gain more of a clear view of a spec type or class and shtis\n"

                "# Rules\n"
                "Here're some rules dat u should obey when u exec the reversing:\n"
                "1. if the users tryna get info related to gameplay logic, we shouldnt look for stuff related to current:\n"
                "    a. Unity Engine itself, inner types and classes and stuff\n"
                "    b. 3rdparty shits, famous opensource stuff\n"
                "    b. UI stuff, audio stuff, video stuff etc.\n"
                "2. when the users tryna locate properties like attack power, health and stuff, most closest to the player class, we should not consider:\n"
                "    a. types and classes dat are too basic and abstract, go look further and deeper, research into the real player class dats using this logic\n"
                "    b. stuff far away or seems not relevent to the essential player class\n"
                "    c. UI stuff, audio/video stuff, animation stuff, infrastructure/engine stuff etc\n"
                "    d. for explanatory text, consider using Chinese."

                "# Finalized Results\n"
                f"Write ONLY a single JSON object with this exact shape into the file at path '{result_json_display}' "
                "and nothing else:\n"
                "{\n"
                '  \"AssistantMessage\": \"free-form explanation text\",\n'
                '  \"SearchKeywords\": [\"keyword1\", \"keyword2\", ...],\n'
                '  \"ExcludedModules\": [\"substring1\", \"substring2\", ...]\n'
                "}\n"
            )

            user_prompt = (
                f"{prompt_overview}\n\n"
                "# User question and context:\n"
                f"{prompt_user}\n"
            )

            full_prompt = system_prompt + "\n" + user_prompt

            # Log a short preview of the combined prompt so we can understand
            # what context was sent without dumping the entire file.
            try:
                preview = full_prompt
                if len(preview) > 400:
                    preview = preview[:400] + "... (truncated)"
                log(f"_call_claude_cli_automation(): full_prompt preview: {preview!r}")
            except Exception as ex: 
                log(f"_call_claude_cli_automation(): failed to log full_prompt preview: {ex!r}")

            # To avoid extremely long -p command-line arguments and give Claude
            # a stable place to read the full context from, write the combined
            # prompt to a temporary markdown file and pass a short pointer
            # prompt that tells it to read that file instead.
            try:
                with open(temp_prompt_path, "w", encoding="utf-8") as f:
                    f.write(full_prompt)
                log(f"_call_claude_cli_automation(): wrote combined prompt to {temp_prompt_path}")
            except Exception as ex:
                log(f"_call_claude_cli_automation(): failed to write {temp_prompt_path}: {ex!r}")

            # Ensure we start from a clean result file so we don't accidentally
            # read stale data if Claude fails to write a new result.
            try:
                if os.path.exists(result_json_path):
                    os.remove(result_json_path)
                    log(f"_call_claude_cli_automation(): deleted existing result file {result_json_path}")
            except Exception as ex:
                log(f"_call_claude_cli_automation(): failed to delete old result file {result_json_path}: {ex!r}")

            short_prompt = (
                f"The file 'temp_prompts.md' in the current working directory "
                f"Carefully read that file, then follow its instructions."
            )

            # Ensure required Claude/Anthropic environment variables are present
            # in this Python process before invoking the CLI.
            _ensure_claude_env()

            # Resolve the Claude CLI executable name: allow overriding via
            # CLAUDE_CLI but invoke it through the shell so that any wrapper
            # scripts (eg. claude.CMD) and PATH logic behave exactly as in an
            # interactive terminal.
            env_cli = os.getenv("CLAUDE_CLI")
            path_env = os.getenv("PATH", "")
            which_claude = shutil.which("claude")
            cli_exe = env_cli or "claude"

            log(
                "call_openai_structured(): invoking Claude CLI in automation mode "
                f"using command prefix '{cli_exe}', PATH length={len(path_env)}, "
                f"shutil.which('claude')={which_claude!r}, CLAUDE_CLI={env_cli!r}."
            )

            # Escape any double quotes so the prompt can be passed as a single
            # argument in a shell command string.
            escaped_prompt = short_prompt.replace('"', '\\"')
            cmd = (
                f'{cli_exe} -p "{escaped_prompt}" '
                "--dangerously-skip-permissions --output-format json --model claude-sonnet-4-5-20250929"
            )
            log(f"call_openai_structured(): Claude CLI full command: {cmd}")

            # Ensure localhost calls to the automation server do not go through
            # any configured HTTP proxy.
            with _without_http_proxy():
                proc = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    shell=True,
                    cwd=base_dir,
                    encoding="utf-8",
                    errors="replace",
                )

            log(f"call_openai_structured(): Claude CLI exited with code {proc.returncode}.")
            stderr_text = proc.stderr.strip() if proc.stderr else ""
            if stderr_text:
                log(f"call_openai_structured(): Claude CLI stderr: {stderr_text}")

            raw_output = proc.stdout or ""
            try:
                with open(CLAUDE_STDOUT_FILE, "w", encoding="utf-8", errors="replace") as f:
                    f.write(raw_output)
                log(f"call_openai_structured(): wrote full Claude stdout to {CLAUDE_STDOUT_FILE}")
            except Exception as ex:
                log(f"call_openai_structured(): failed to write {CLAUDE_STDOUT_FILE}: {ex!r}")
            preview = raw_output
            if len(preview) > 4000:
                preview = preview[:4000] + "... (truncated)"
            log(f"call_openai_structured(): Claude CLI stdout preview: {preview!r}")

            if proc.returncode != 0:
                raise RuntimeError(f"Claude CLI failed with exit code {proc.returncode}")

            # Prefer the JSON file result if Claude was able to write it;
            # otherwise, fall back to parsing stdout as before so we still
            # get a usable response.
            data: Dict[str, Any]
            if os.path.exists(result_json_path):
                try:
                    with open(result_json_path, "r", encoding="utf-8", errors="replace") as f:
                        file_text = f.read()

                    try:
                        data = json.loads(file_text)
                    except Exception as ex:
                        raise RuntimeError(f"Failed to parse Claude result JSON from {result_json_path}: {ex!r}")
                finally:
                    # Best-effort cleanup of the result file so each run starts fresh.
                    try:
                        if os.path.exists(result_json_path):
                            os.remove(result_json_path)
                            log(f"_call_claude_cli_automation(): deleted result file {result_json_path}")
                    except Exception as ex:
                        log(f"_call_claude_cli_automation(): failed to delete result file {result_json_path}: {ex!r}")
            else:
                log(
                    f"_call_claude_cli_automation(): result JSON file {result_json_path} "
                    "not found; falling back to parsing stdout."
                )
                output = raw_output.strip()
                if not output:
                    raise RuntimeError(
                        "Claude CLI did not write result JSON file and stdout is empty; "
                        "cannot obtain automation result."
                    )

                text = _strip_markdown_fence(output)

                try:
                    obj = json.loads(text)
                    if isinstance(obj, dict) and "result" in obj and isinstance(obj["result"], str):
                        inner = _strip_markdown_fence(obj["result"])
                        data = json.loads(inner)
                    else:
                        data = obj
                except Exception:
                    # As a final fallback, surface the raw text as the assistant
                    # message instead of raising, so the user can inspect it.
                    return {
                        "AssistantMessage": output,
                        "SearchKeywords": [],
                        "ExcludedModules": [],
                    }

            if not isinstance(data, dict):
                raise ValueError("Claude result JSON is not an object")

            return data

        try:
            data = _call_claude_cli_automation(last_user, project_overview)
        except Exception as ex:
            # Let the caller decide how to surface automation errors; do not
            # silently fall back to any offline heuristic in automation mode.
            log(f"call_openai_structured(): Claude CLI automation path failed: {ex!r}")
            raise

        # Normalize Claude's response into the expected shape.
        assistant_message = data.get("AssistantMessage") or ""
        search_keywords = data.get("SearchKeywords") or []
        excluded_modules = data.get("ExcludedModules") or []

        if not isinstance(search_keywords, list):
            search_keywords = []
        if not isinstance(excluded_modules, list):
            excluded_modules = []

        norm_search: List[str] = []
        for kw in search_keywords:
            if isinstance(kw, str):
                kw = kw.strip()
                if kw:
                    norm_search.append(kw)

        norm_excluded: List[str] = []
        for m in excluded_modules:
            if isinstance(m, str):
                m = m.strip()
                if m:
                    norm_excluded.append(m)

        return {
            "AssistantMessage": assistant_message,
            "SearchKeywords": norm_search,
            "ExcludedModules": norm_excluded,
        }

    # By default (chat / file modes), enable the Poe/OpenAI backend.
    # You can force offline mode by setting POE_ENABLED to 0/false/no.
    poe_enabled = os.getenv("POE_ENABLED", "1").lower()
    if poe_enabled in ("0", "false", "no", "n"):
        log("call_openai_structured(): POE_ENABLED is disabled, using offline fallback.")
        keywords = fallback_keywords(last_user)
        paths = build_keyword_paths(keywords, last_user)
        assistant_msg = (
            "Analyzing your request using an offline heuristic (no network backend enabled).\n\n"
            "I will infer important type and member names from your question and the current class/file "
            "and use them as search keywords inside dnSpy."
        )
        return {
            "AssistantMessage": assistant_msg,
            "SearchKeywords": paths,
            "ExcludedModules": [],
        }

    api_key = os.getenv("POE_API_KEY") or os.getenv("OPENAI_API_KEY") or DEFAULT_POE_API_KEY
    if not api_key:
        raise RuntimeError("POE_API_KEY/OPENAI_API_KEY is not set")

    # Force all HTTP(S) traffic through the local proxy, ignoring
    # any existing proxy-related environment variables.
    proxy_url = "http://127.0.0.1:2805"
    os.environ["HTTP_PROXY"] = proxy_url
    os.environ["http_proxy"] = proxy_url
    os.environ["HTTPS_PROXY"] = proxy_url
    os.environ["https_proxy"] = proxy_url

    import openai  # type: ignore

    client = openai.OpenAI(  # type: ignore[attr-defined]
        api_key=api_key,
        base_url=os.getenv("POE_BASE_URL", "https://api.poe.com/v1"),
    )

    # Allow overriding the network timeout from the environment,
    # but keep it reasonably small so dnSpy won't appear frozen
    # if the Poe/OpenAI endpoint is unreachable.
    try:
        # Default timeout (seconds) for Poe/OpenAI calls.
        # You can override this with POE_TIMEOUT_SECONDS.
        timeout_seconds = float(os.getenv("POE_TIMEOUT_SECONDS", "60"))
    except Exception:
        timeout_seconds = 60.0

    log(f"call_openai_structured(): mode={mode}, len(last_user)={len(last_user)}, "
        f"project_overview_len={len(project_overview)}, timeout={timeout_seconds}")

    if mode == "file":
        system_prompt = (
            "You are a Unity / C# reverse-engineering assistant integrated into dnSpy.\n"
            "The user has opened a specific decompiled C# class or file in the dnSpy code editor\n"
            "and is asking you to analyze that current class.\n"
            "Your job is to:\n"
            "  1) Explain in detail what this class does in the game's logic (gameplay, UI, systems, etc.).\n"
            "  2) Highlight important methods, fields, properties, and events, and how they interact.\n"
            "  3) Suggest concrete hooks or modification points that a modder or reverser might use.\n"
            "  4) Propose short search keywords (type names, method names, namespaces, etc.) that dnSpy\n"
            "     can use to search the rest of the project for related code.\n"
            "Return ONLY a JSON object with the following shape and nothing else:\n"
            "{\n"
            '  \"assistant_message\": \"free-form answer text\",\n'
            '  \"search_keywords\": [\"keyword1\", \"keyword2\", ...],\n'
            '  \"excluded_modules\": [\"module-substring-1\", \"module-substring-2\", ...],\n'
            '  \"keywords\": [\n'
            '    {\"keyword\": \"Player\", \"parent\": null, \"layer\": 0},\n'
            '    {\"keyword\": \"Health\", \"parent\": \"Player\", \"layer\": 1},\n'
            '    {\"keyword\": \"Attack\", \"parent\": \"Player\", \"layer\": 1},\n'
            '    {\"keyword\": \"Power\", \"parent\": \"Attack\", \"layer\": 2}\n'
            "  ]\n"
            "}\n"
            "When suggesting search keywords, prefer ones that include the class name and the most\n"
            "important methods or properties from the provided code so dnSpy's search can easily\n"
            "jump to related logic.\n"
        )
    else:
        system_prompt = (
            "You are a Unity game reverse-engineering assistant integrated into dnSpy.\n"
            "The user is inspecting a Unity or .NET game and asking about types, methods, "
            "assemblies, and modules in the loaded project.\n"
            "Your job is to:\n"
            "  1) Explain the likely game logic or behavior in clear language.\n"
            "  2) Propose short search keywords (type names, method names, namespaces, etc.) "
            "     that dnSpy can use to search the project.\n"
            "  3) Suggest module name patterns that should be excluded from search results "
            "     (for example engine/framework/system/UI assemblies) when they are not "
            "     relevant to gameplay code.\n"
            "Return ONLY a JSON object with the following shape and nothing else:\n"
            "{\n"
            '  \"assistant_message\": \"free-form answer text\",\n'
            '  \"search_keywords\": [\"keyword1\", \"keyword2\", ...],\n'
            '  \"excluded_modules\": [\"module-substring-1\", \"module-substring-2\", ...],\n'
            '  \"keywords\": [\n'
            '    {\"keyword\": \"Player\", \"parent\": null, \"layer\": 0},\n'
            '    {\"keyword\": \"Health\", \"parent\": \"Player\", \"layer\": 1},\n'
            '    {\"keyword\": \"Attack\", \"parent\": \"Player\", \"layer\": 1},\n'
            '    {\"keyword\": \"Power\", \"parent\": \"Attack\", \"layer\": 2}\n'
            "  ]\n"
            "}\n"
            "When the user is asking specifically about gameplay or mission logic, prefer to "
            "exclude generic system/framework/UI modules such as those containing names like:\n"
            "  \"System\", \"mscorlib\", \"UnityEngine\", \"UnityEditor\", \"UnityEngine.UI\", "
            "\"TMPro\", \"TextMeshPro\", \"Newtonsoft\", \"DOTween\", or obvious plugin names.\n"
            "Use short substrings that will match the module names, not full paths.\n"
        )

    user_prompt = (
        "Project overview (truncated):\n"
        f"{project_overview}\n\n"
        "User question and context:\n"
        f"{last_user}\n"
    )

    # Write minimal progress information to stderr so the host can
    # surface it in the LLM log window when troubleshooting.
    log("call_openai_structured(): calling Poe/OpenAI chat.completions.create()")
    print("[llm-backend] Calling Poe/OpenAI for structured response...", file=sys.stderr, flush=True)

    try:
        chat = client.chat.completions.create(
            model=os.getenv("POE_MODEL", "claude-sonnet-4.5"),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            timeout=timeout_seconds,
        )
    except Exception as ex:
        log(f"call_openai_structured(): OpenAI call failed: {ex!r}, falling back to offline heuristic.")
        keywords = fallback_keywords(last_user)
        paths = build_keyword_paths(keywords, last_user)
        assistant_msg = (
            "Analyzing your request using an offline heuristic because the Poe/OpenAI "
            f"backend call failed or timed out (error: {ex})."
        )
        return {
            "AssistantMessage": assistant_msg,
            "SearchKeywords": paths,
            "ExcludedModules": [],
        }

    content = chat.choices[0].message.content
    if isinstance(content, str):
        raw = content
    else:
        # Newer SDKs may return a list of content parts
        raw = "".join(getattr(part, "text", "") for part in content)  # type: ignore[assignment]

    raw = _strip_markdown_fence(raw)

    log(f"call_openai_structured(): OpenAI response length={len(raw)} characters")
    data = json.loads(raw)
    assistant_message = data.get("assistant_message") or ""
    search_keywords = data.get("search_keywords") or []
    excluded_modules = data.get("excluded_modules") or []
    keyword_tree = data.get("keywords") or []

    if not isinstance(search_keywords, list):
        search_keywords = []
    if not isinstance(excluded_modules, list):
        excluded_modules = []

    # Normalize keywords and excluded module patterns to strings.
    normalized_keywords: List[str] = []
    for kw in search_keywords:
        if isinstance(kw, str):
            kw = kw.strip()
            if kw:
                normalized_keywords.append(kw)

    # Prefer explicit keyword tree paths if provided.
    paths_from_tree = build_paths_from_tree(keyword_tree) if keyword_tree else []
    if paths_from_tree:
        normalized_keywords = paths_from_tree
    else:
        # Convert flat keywords into path-style phrases when needed.
        normalized_keywords = build_keyword_paths(normalized_keywords, last_user)

    normalized_excluded: List[str] = []
    for m in excluded_modules:
        if isinstance(m, str):
            m = m.strip()
            if m:
                normalized_excluded.append(m)

    log("call_openai_structured(): building normalized response")
    print("[llm-backend] Poe/OpenAI call succeeded, building response JSON.", file=sys.stderr, flush=True)

    return {
        "AssistantMessage": assistant_message,
        "SearchKeywords": normalized_keywords,
        "ExcludedModules": normalized_excluded,
    }


def ping_automation_server(base_url: str = "http://127.0.0.1:5015") -> str:
    """
    Try to contact the local automation HTTP server's /health endpoint.

    Returns a short status string describing the result, but never raises.
    """
    url = base_url.rstrip("/") + "/health"
    try:
        with _without_http_proxy():
            with urllib.request.urlopen(url, timeout=2.0) as resp:
                data = resp.read()
        try:
            payload = json.loads(data.decode("utf-8", "replace"))
        except Exception:
            payload = {}
        status = payload.get("status") or "unknown"
        msg = f"automation server reachable at {url} (status={status})"
        log(f"ping_automation_server(): {msg}")
        return msg
    except urllib.error.URLError as ex:
        msg = f"automation server NOT reachable at {url}: {ex!r}"
        log(f"ping_automation_server(): {msg}")
        return msg
    except Exception as ex:  # pragma: no cover - best-effort only
        msg = f"automation server check failed at {url}: {ex!r}"
        log(f"ping_automation_server(): {msg}")
        return msg


def automation_search_with_keywords(
    keywords: List[str],
    base_url: str = "http://127.0.0.1:5015",
    max_results_per_keyword: int = 10,
    max_total_results: int = 50,
) -> List[Dict[str, Any]]:
    """
    Query the local automation HTTP server's broad-search endpoint
    for each keyword and aggregate a small set of hits.

    Returns a list of result dicts with an extra '_pattern' field
    indicating which keyword produced the hit. Any network / JSON
    errors are logged and ignored.
    """
    results: List[Dict[str, Any]] = []
    if not keywords:
        return results

    base = base_url.rstrip("/")
    for kw in keywords:
        if len(results) >= max_total_results:
            break
        if not isinstance(kw, str):
            continue
        pattern = kw.strip()
        if not pattern:
            continue

        try:
            query = urllib.parse.urlencode(
                {"pattern": pattern, "maxResults": str(max_results_per_keyword)}
            )
            url = f"{base}/api/search/broad?{query}"
            log(f"automation_search_with_keywords(): GET {url}")
            with _without_http_proxy():
                with urllib.request.urlopen(url, timeout=5.0) as resp:
                    data = resp.read()
            payload = json.loads(data.decode("utf-8", "replace"))
            if isinstance(payload, list):
                for item in payload:
                    if not isinstance(item, dict):
                        continue
                    item = dict(item)
                    item["_pattern"] = pattern
                    results.append(item)
                    if len(results) >= max_total_results:
                        break
        except Exception as ex:  # pragma: no cover - best-effort only
            log(f"automation_search_with_keywords(): error querying automation server for pattern '{pattern}': {ex!r}")

    log(f"automation_search_with_keywords(): collected {len(results)} total hits from automation server")
    return results


def main() -> None:
    req = read_request()
    messages = req.get("Messages", []) or []
    project = req.get("Project", {}) or {}
    debug_mode = bool(req.get("DebugMode"))
    log(f"main(): debug_mode={debug_mode}")

    last_user_raw = extract_last_user_message(messages)
    if not last_user_raw:
        resp = {
            "AssistantMessage": (
                "I don't see any user message yet. "
                "Ask me about types, methods, or modules in the loaded assemblies."
            ),
            "SearchKeywords": [],
            "ExcludedModules": [],
        }
        json.dump(resp, sys.stdout)
        return

    # In debug mode, bypass any Claude/OpenAI calls and just echo the
    # raw user message back as a single keyword path. This lets the host
    # app drive searches directly without consuming LLM tokens.
    if debug_mode:
        log("main(): debug_mode is true, echoing last user message as SearchKeywords without calling OpenAI/Claude.")
        resp = {
            "AssistantMessage": "",
            "SearchKeywords": [last_user_raw],
            "ExcludedModules": [],
        }
        json.dump(resp, sys.stdout)
        return

    FILE_ANALYZE_PREFIX = "[[FILE_ANALYZE]]"

    mode = req.get("Mode") or "chat"
    last_user = last_user_raw
    if last_user.startswith(FILE_ANALYZE_PREFIX):
        mode = "file"
        last_user = last_user[len(FILE_ANALYZE_PREFIX) :].lstrip()

    if mode == "file":
        overview = build_type_outline(project, last_user)
        if not overview:
            overview = build_project_overview(project)
        project_overview = overview
    else:
        project_overview = build_project_overview(project)

    if mode == "automation":
        # Best-effort ping of the local automation server so that
        # the model can be told whether it is available.
        status_msg = ping_automation_server()
        if project_overview:
            project_overview = status_msg + "\n\n" + project_overview
        else:
            project_overview = status_msg

    # Try OpenAI/Claude for structured output; fall back to local keyword
    # extraction in non-automation modes. For automation, surface errors
    # directly to the user instead of silently using heuristics.
    try:
        resp = call_openai_structured(last_user, project_overview, mode=mode)
    except Exception as ex:
        # Log full traceback to stderr so the host app can surface it.
        traceback.print_exc()
        if mode == "automation":
            # In automation mode, do not use any offline heuristic. Return
            # a clear error message so the user understands what failed.
            assistant_msg = (
                "Automation backend error while invoking Claude or the automation tooling.\n"
                f"{ex}"
            )
            resp = {
                "AssistantMessage": assistant_msg,
                "SearchKeywords": [],
                "ExcludedModules": [],
            }
        else:
            keywords = fallback_keywords(last_user)
            assistant_msg = (
                "Analyzing your question and the loaded modules. "
                "I'm using a local keyword heuristic because the Poe/OpenAI "
                "backend is not available or returned an error."
            )
            resp = {
                "AssistantMessage": assistant_msg,
                "SearchKeywords": keywords,
                "ExcludedModules": [],
            }

    # In automation mode, augment the assistant message with concrete hits
    # from the local automation HTTP server, using the search keywords that
    # Claude produced.
    if mode == "automation":
        try:
            keywords = resp.get("SearchKeywords") or []
            if isinstance(keywords, list) and keywords:
                auto_hits = automation_search_with_keywords(
                    [kw for kw in keywords if isinstance(kw, str)],
                    base_url=os.getenv("LLM_AUTOMATION_BASE_URL", "http://127.0.0.1:5015"),
                )
            else:
                auto_hits = []

            if auto_hits:
                # Build a compact, human-readable summary of the first few hits.
                lines: List[str] = []
                lines.append("Automation server matches (first results):")
                for hit in auto_hits[:10]:
                    kind = hit.get("kind") or "?"
                    full_name = hit.get("fullName") or hit.get("name") or "<?>"
                    module_name = hit.get("moduleName") or "<?>"
                    pattern = hit.get("_pattern") or ""
                    if pattern:
                        lines.append(f"- [{kind}] {full_name} (module {module_name}) via pattern '{pattern}'")
                    else:
                        lines.append(f"- [{kind}] {full_name} (module {module_name})")

                extra = "\n".join(lines)
                assistant_msg = resp.get("AssistantMessage") or ""
                if assistant_msg:
                    assistant_msg = assistant_msg.rstrip() + "\n\n" + extra
                else:
                    assistant_msg = extra
                resp["AssistantMessage"] = assistant_msg
        except Exception as ex:  # pragma: no cover - best-effort only
            # Never let automation enrichment break the core chat flow.
            log(f"main(): automation enrichment failed: {ex!r}")

    json.dump(resp, sys.stdout)


if __name__ == "__main__":
    main()
