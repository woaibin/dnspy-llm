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


# Default Poe/OpenAI API key used if environment variables are not set.
# You can override this at runtime by setting POE_API_KEY or OPENAI_API_KEY.
DEFAULT_POE_API_KEY = "uQA9T24fMZ10fF05WJi79MqlShUGH9ZMM7Ip1dzXgho"


def read_request() -> Dict[str, Any]:
    """Read the JSON LlmBackendRequest from stdin."""
    if sys.stdin.isatty():
        return {}
    data = sys.stdin.read()
    if not data.strip():
        return {}
    raw = json.loads(data)
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


def call_openai_structured(last_user: str, project_overview: str) -> Dict[str, Any]:
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
        "User question:\n"
        f"{last_user}\n"
    )

    chat = client.chat.completions.create(
        model=os.getenv("POE_MODEL", "claude-sonnet-4.5"),
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )

    content = chat.choices[0].message.content
    if isinstance(content, str):
        raw = content
    else:
        # Newer SDKs may return a list of content parts
        raw = "".join(getattr(part, "text", "") for part in content)  # type: ignore[assignment]

    raw = _strip_markdown_fence(raw)

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

    return {
        "AssistantMessage": assistant_message,
        "SearchKeywords": normalized_keywords,
        "ExcludedModules": normalized_excluded,
    }


def main() -> None:
    req = read_request()
    messages = req.get("Messages", []) or []
    project = req.get("Project", {}) or {}

    last_user = extract_last_user_message(messages)
    if not last_user:
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

    project_overview = build_project_overview(project)

    # Try OpenAI for structured output; fall back to local keyword extraction.
    try:
        resp = call_openai_structured(last_user, project_overview)
    except Exception:
        # Log full traceback to stderr so the host app can surface it.
        traceback.print_exc()
        keywords = fallback_keywords(last_user)
        assistant_msg = (
            "Analyzing your question and the loaded modules. "
            "I'm using a local keyword heuristic because the OpenAI backend "
            "is not available or returned an error."
        )
        resp = {
            "AssistantMessage": assistant_msg,
            "SearchKeywords": keywords,
            "ExcludedModules": [],
        }

    json.dump(resp, sys.stdout)


if __name__ == "__main__":
    main()
