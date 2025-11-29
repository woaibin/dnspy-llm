#!/usr/bin/env python
"""
Lightweight HTTP server for LLM automation, implemented in Python.

Startup:
  - Reads a JSON payload from stdin that contains either:
      { "Modules": [ ... ] }
    or an LlmBackendRequest-like shape:
      { "Project": { "Modules": [ ... ] }, ... }
  - Keeps the analyzed project in memory for search/lookup.

HTTP endpoints (default: http://127.0.0.1:5015/):
  - GET  /health
      -> { "status": "ok" }
  - GET  /api/search/broad?pattern=...&maxResults=...
      -> [ { kind, name, fullName, moduleName, assemblyPath, signature }, ... ]
  - GET  /api/lookup/clear?identifier=...
      -> { status: "ok" | "ambiguous" | "not_found", ... }
  - GET  /api/search/typeRefs?identifier=...&maxResults=...
      -> { identifier, hits: [ { kind, name, fullName, moduleName, assemblyPath, sourcePath, reasons }, ... ] }

This mirrors the .NET-based design but avoids extra build/restore
complexity by running as a standalone Python script.
"""

import json
import os
import re
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, List, Tuple

PROJECT: Dict[str, Any] = {}


def log(msg: str) -> None:
    try:
        sys.stderr.write(msg + "\n")
        sys.stderr.flush()
    except Exception:
        pass


def read_initial_project_from_stdin() -> None:
    """
    Read the initial analyzed project JSON from stdin.

    Supports two shapes:
      - { "Modules": [ ... ] }
      - { "Project": { "Modules": [ ... ] }, ... }
    """
    global PROJECT

    stdin = sys.stdin.buffer

    if stdin.isatty():
        log("stdin is a TTY, no project JSON provided; starting with empty project.")
        PROJECT = {"Modules": []}
        return

    raw_bytes = stdin.read()
    if not raw_bytes.strip():
        log("stdin is empty/whitespace; starting with empty project.")
        PROJECT = {"Modules": []}
        return

    try:
        text = raw_bytes.decode("utf-8", errors="replace")
        obj = json.loads(text)
    except Exception as ex:
        log(f"failed to parse JSON from stdin: {ex!r}")
        PROJECT = {"Modules": []}
        return

    if isinstance(obj, dict) and "Modules" in obj:
        PROJECT = obj
    elif isinstance(obj, dict) and isinstance(obj.get("Project"), dict):
        PROJECT = obj["Project"]
    else:
        log("unrecognized JSON shape, expected root.Modules or root.Project.Modules; starting with empty project.")
        PROJECT = {"Modules": []}


def _iter_types() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    modules = PROJECT.get("Modules") or []
    for mod in modules:
        types = mod.get("Types") or []
        for t in types:
            yield mod, t


def _iter_members(t: Dict[str, Any]) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for key in ("Fields", "Methods", "Properties", "Events"):
        arr = t.get(key) or []
        for m in arr:
            if isinstance(m, dict):
                result.append(m)
    return result


def broad_search(pattern: str, max_results: int) -> List[Dict[str, Any]]:
    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error as ex:
        raise ValueError(f"invalid regex: {ex}") from ex

    max_results = max(1, min(max_results or 500, 500))
    results: List[Dict[str, Any]] = []

    modules = PROJECT.get("Modules") or []
    for mod in modules:
        mod_name = (mod.get("Name") or "").strip()
        assembly_full = (mod.get("AssemblyFullName") or "").strip()
        assembly_path = (
            (mod.get("AssemblyPath") or "").strip()
            or (mod.get("ModuleFilePath") or "").strip()
            or (mod.get("FileName") or "").strip()
        )

        if regex.search(mod_name) or (assembly_full and regex.search(assembly_full)):
            results.append(
                {
                    "kind": "module",
                    "name": mod_name,
                    "fullName": assembly_full or mod_name,
                    "moduleName": mod_name,
                    "assemblyPath": assembly_path,
                    "signature": "",
                }
            )
            if len(results) >= max_results:
                return results

        for mod_obj, t in _iter_types():
            if mod_obj is not mod:
                continue

            t_name = (t.get("Name") or "").strip()
            t_full = (t.get("FullName") or "").strip()

            if regex.search(t_full) or (t_name and regex.search(t_name)):
                results.append(
                    {
                        "kind": "type",
                        "name": t_name,
                        "fullName": t_full or t_name,
                        "moduleName": mod_name,
                        "assemblyPath": assembly_path,
                        "signature": "",
                    }
                )
                if len(results) >= max_results:
                    return results

            for m in _iter_members(t):
                m_name = (m.get("Name") or "").strip()
                m_full = (m.get("FullName") or "").strip()
                sig = (m.get("Signature") or "").strip()

                if regex.search(m_full) or (m_name and regex.search(m_name)) or (sig and regex.search(sig)):
                    results.append(
                        {
                            "kind": "member",
                            "name": m_name,
                            "fullName": m_full or m_name,
                            "moduleName": mod_name,
                            "assemblyPath": assembly_path,
                            "signature": sig,
                        }
                    )
                    if len(results) >= max_results:
                        return results

    log(f"broad_search(): pattern={pattern!r}, max_results={max_results}, hits={len(results)}")
    return results


def clear_lookup(identifier: str) -> Dict[str, Any]:
    ident = identifier.strip().strip('"')
    if not ident:
        return {"status": "bad_request", "error": "empty identifier"}

    exact_matches: List[Dict[str, Any]] = []
    partial_matches: List[Dict[str, Any]] = []

    for mod, t in _iter_types():
        mod_name = (mod.get("Name") or "").strip()
        assembly_path = (
            (mod.get("AssemblyPath") or "").strip()
            or (mod.get("ModuleFilePath") or "").strip()
            or (mod.get("FileName") or "").strip()
        )
        t_full = (t.get("FullName") or "").strip()

        if t_full == ident:
            exact_matches.append(
                {
                    "moduleName": mod_name,
                    "assemblyPath": assembly_path,
                    "typeFullName": t_full,
                    "sourcePath": (t.get("SourceFilePath") or "").strip(),
                }
            )
        elif t_full and ident.lower() in t_full.lower():
            partial_matches.append(
                {
                    "moduleName": mod_name,
                    "assemblyPath": assembly_path,
                    "typeFullName": t_full,
                    "sourcePath": (t.get("SourceFilePath") or "").strip(),
                }
            )

    matches = exact_matches or partial_matches

    if not matches:
        log(f"clear_lookup(): identifier={ident!r}, status=not_found")
        return {"status": "not_found", "identifier": ident}

    if len(matches) == 1:
        m = matches[0]
        log(f"clear_lookup(): identifier={ident!r}, status=ok, module={m['moduleName']}, type={m['typeFullName']}")
        return {
            "status": "ok",
            "identifier": ident,
            "assemblyPath": m["assemblyPath"],
            "typeFullName": m["typeFullName"],
            "sourcePath": m.get("sourcePath") or "",
        }

    log(f"clear_lookup(): identifier={ident!r}, status=ambiguous, candidates={len(matches)}")
    return {"status": "ambiguous", "identifier": ident, "candidates": matches}


def find_type_references(identifier: str, max_results: int) -> Dict[str, Any]:
    """
    Find types that *use* a given type (by name) in their base type
    or member signatures.

    The identifier is matched case-insensitively against type names and
    full names to discover the "target" types, and then we scan all
    types' BaseType and member Signatures / FullName strings for
    occurrences of those targets (or the raw identifier as a fallback).
    """
    ident = identifier.strip().strip('"')
    if not ident:
        raise ValueError("empty identifier")

    max_results = max(1, min(max_results or 500, 500))
    ident_lower = ident.lower()

    target_names = set()
    target_full_names = set()

    # First pass: discover the concrete type names that correspond to the identifier.
    for _, t in _iter_types():
        t_name = (t.get("Name") or "").strip()
        t_full = (t.get("FullName") or "").strip()
        if not t_name and not t_full:
            continue
        name_lower = t_name.lower() if t_name else ""
        full_lower = t_full.lower() if t_full else ""
        if (
            name_lower == ident_lower
            or full_lower == ident_lower
            or (full_lower and ident_lower in full_lower)
        ):
            if t_name:
                target_names.add(t_name)
            if t_full:
                target_full_names.add(t_full)

    # Always fall back to the raw identifier so "money" still works
    # even if we didn't find an exact type match above.
    tokens = {ident}
    tokens.update(target_names)
    tokens.update(target_full_names)
    tokens = {tok for tok in tokens if tok}

    # Track the exact full names of the "spec" types so we can
    # optionally avoid returning the type itself as a "reference".
    spec_type_full_names = {full for full in target_full_names if full}

    def contains_token(s: str) -> bool:
        if not s:
            return False
        s_lower = s.lower()
        for tok in tokens:
            if tok.lower() in s_lower:
                return True
        return False

    results: List[Dict[str, Any]] = []

    for mod, t in _iter_types():
        t_name = (t.get("Name") or "").strip()
        t_full = (t.get("FullName") or "").strip()

        # Skip the spec type itself unless it references the target via
        # some other path (e.g., it has a field of its own type); this
        # keeps "find refs of Money" focused on *other* types.
        if spec_type_full_names and t_full in spec_type_full_names:
            continue

        mod_name = (mod.get("Name") or "").strip()
        assembly_path = (
            (mod.get("AssemblyPath") or "").strip()
            or (mod.get("ModuleFilePath") or "").strip()
            or (mod.get("FileName") or "").strip()
        )

        reasons: List[str] = []

        base_type = (t.get("BaseType") or "").strip()
        if contains_token(base_type):
            reasons.append(f"baseType={base_type}")

        for m in _iter_members(t):
            m_name = (m.get("Name") or "").strip()
            m_full = (m.get("FullName") or "").strip()
            sig = (m.get("Signature") or "").strip()
            member_type = (m.get("MemberType") or "").strip()

            if contains_token(sig) or contains_token(m_full):
                desc = member_type or "member"
                if m_name:
                    desc += f" {m_name}"
                if sig:
                    desc += f" sig={sig}"
                elif m_full:
                    desc += f" fullName={m_full}"
                reasons.append(desc)

            if len(reasons) >= 10:
                # Avoid unbounded reason lists per type; a few examples are enough.
                break

        if reasons:
            results.append(
                {
                    "kind": "typeRef",
                    "name": t_name,
                    "fullName": t_full or t_name,
                    "moduleName": mod_name,
                    "assemblyPath": assembly_path,
                    "sourcePath": (t.get("SourceFilePath") or "").strip(),
                    "reasons": reasons,
                }
            )
            if len(results) >= max_results:
                break

    log(
        "find_type_references(): identifier=%r, max_results=%d, hits=%d"
        % (ident, max_results, len(results))
    )
    return {"identifier": ident, "hits": results}


def extract_file_to_temp(source_path: str) -> str:
    """
    Read the raw contents of a file (e.g., a DLL-stored resource), write
    it to a temporary file, and return the temp path. The caller is
    responsible for deleting the temp file once the LLM is done with it.
    """
    source_path = os.path.abspath(source_path)
    with open(source_path, "rb") as f:
        data = f.read()

    fd, tmp_path = tempfile.mkstemp(prefix="llm_automation_", suffix=".bin")
    with os.fdopen(fd, "wb") as tmp:
        tmp.write(data)

    return tmp_path


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "LlmAutomationServer/0.1"

    def _send_json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: D401
        # Avoid noisy default logging; send to stderr instead.
        log("%s - %s" % (self.address_string(), fmt % args))

    def do_GET(self) -> None:  # noqa: N802
        path, _, query = self.path.partition("?")

        if path == "/health":
            self._send_json(200, {"status": "ok"})
            return

        if path == "/api/search/broad":
            params = self._parse_query(query)
            pattern = params.get("pattern") or ""
            max_results = int(params.get("maxResults") or "500")
            if not pattern:
                self._send_json(400, {"error": "missing 'pattern' query parameter"})
                return
            try:
                results = broad_search(pattern, max_results)
            except ValueError as ex:
                self._send_json(400, {"error": str(ex)})
                return
            self._send_json(200, results)
            return

        if path == "/api/search/typeRefs":
            params = self._parse_query(query)
            identifier = params.get("identifier") or ""
            max_results = int(params.get("maxResults") or "500")
            if not identifier:
                self._send_json(400, {"error": "missing 'identifier' query parameter"})
                return
            try:
                result = find_type_references(identifier, max_results)
            except ValueError as ex:
                self._send_json(400, {"error": str(ex)})
                return
            self._send_json(200, result)
            return

        if path == "/api/lookup/clear":
            params = self._parse_query(query)
            identifier = params.get("identifier") or ""
            result = clear_lookup(identifier)
            status = 200 if result.get("status") != "bad_request" else 400
            self._send_json(status, result)
            return

        self._send_json(404, {"error": "not found"})

    def _parse_query(self, query: str) -> Dict[str, str]:
        params: Dict[str, str] = {}
        if not query:
            return params
        for part in query.split("&"):
            if not part:
                continue
            if "=" in part:
                k, v = part.split("=", 1)
            else:
                k, v = part, ""
            params[re.sub(r"\+", " ", k)] = re.sub(r"\+", " ", v)
        return params


def run_server(host: str = "127.0.0.1", port: int = 5015) -> None:
    server = HTTPServer((host, port), RequestHandler)
    log(f"llm_automation_server listening on http://{host}:{port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main() -> None:
    read_initial_project_from_stdin()

    host = os.getenv("LLM_AUTOMATION_HOST", "127.0.0.1")
    port_str = os.getenv("LLM_AUTOMATION_PORT", "5015")
    try:
        port = int(port_str)
    except ValueError:
        port = 5015

    run_server(host, port)


if __name__ == "__main__":
    main()
