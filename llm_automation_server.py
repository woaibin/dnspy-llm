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

    if sys.stdin.isatty():
        log("stdin is a TTY, no project JSON provided; starting with empty project.")
        PROJECT = {"Modules": []}
        return

    raw = sys.stdin.read()
    if not raw.strip():
        log("stdin is empty/whitespace; starting with empty project.")
        PROJECT = {"Modules": []}
        return

    try:
        obj = json.loads(raw)
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
