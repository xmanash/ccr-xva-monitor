"""Newline-delimited JSON-RPC MCP server over stdio.

Cursor launches this with `python -m ccr_xva.mcp.server`. Tool results are the
same dictionaries the API returns.
"""

from __future__ import annotations

import json
import sys
import traceback

from ccr_xva import __version__
from ccr_xva.mcp.tools import (
    ask_risk,
    calculate_exposure,
    calculate_xva,
    list_agents,
    list_book,
    load_sample_book,
    recall_memory,
    search_methodology,
)

_PROTOCOL_VERSIONS = {"2024-11-05", "2025-03-26", "2025-06-18"}

_TOOLS = [
    {
        "name": "list_agents",
        "description": list_agents.__doc__ or "",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "fn": list_agents,
    },
    {
        "name": "recall_memory",
        "description": recall_memory.__doc__ or "",
        "inputSchema": {
            "type": "object",
            "properties": {
                "counterparty": {"type": "string", "default": ""},
                "session_id": {"type": "string", "default": "mcp"},
            },
            "additionalProperties": False,
        },
        "fn": recall_memory,
    },
    {
        "name": "search_methodology",
        "description": search_methodology.__doc__ or "",
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
        "fn": search_methodology,
    },
    {
        "name": "list_book",
        "description": list_book.__doc__ or "",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "fn": list_book,
    },
    {
        "name": "load_sample_book",
        "description": load_sample_book.__doc__ or "",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "fn": load_sample_book,
    },
    {
        "name": "calculate_exposure",
        "description": calculate_exposure.__doc__ or "",
        "inputSchema": {
            "type": "object",
            "properties": {
                "netting_set_id": {"type": "string"},
                "as_of": {"type": "string", "default": "2026-10-05"},
                "n_paths": {"type": "integer", "default": 200},
            },
            "required": ["netting_set_id"],
            "additionalProperties": False,
        },
        "fn": calculate_exposure,
    },
    {
        "name": "calculate_xva",
        "description": calculate_xva.__doc__ or "",
        "inputSchema": {
            "type": "object",
            "properties": {
                "netting_set_id": {"type": "string"},
                "as_of": {"type": "string", "default": "2026-10-05"},
                "n_paths": {"type": "integer", "default": 200},
            },
            "required": ["netting_set_id"],
            "additionalProperties": False,
        },
        "fn": calculate_xva,
    },
    {
        "name": "ask_risk",
        "description": ask_risk.__doc__ or "",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "as_of": {"type": "string", "default": "2026-10-05"},
                "n_paths": {"type": "integer", "default": 120},
                "session_id": {"type": "string", "default": "mcp"},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        "fn": ask_risk,
    },
]
_BY_NAME = {tool["name"]: tool for tool in _TOOLS}


def main() -> None:
    while True:
        line = sys.stdin.readline()
        if not line:
            return
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            _send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
            continue
        response = _handle(message)
        if response is not None:
            _send(response)


def _handle(message: dict) -> dict | None:
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") or {}
    if request_id is None:
        return None
    try:
        result = _dispatch(method, params)
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32000, "message": str(exc)}}
    if result is _NOT_FOUND:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"Unknown method {method}"}}
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _dispatch(method: str | None, params: dict):
    if method == "initialize":
        version = params.get("protocolVersion")
        if version not in _PROTOCOL_VERSIONS:
            version = "2024-11-05"
        return {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "ccr-xva", "version": __version__},
        }
    if method == "ping":
        return {}
    if method == "tools/list":
        return {
            "tools": [
                {"name": tool["name"], "description": tool["description"].strip(), "inputSchema": tool["inputSchema"]}
                for tool in _TOOLS
            ]
        }
    if method == "tools/call":
        return _call_tool(params.get("name"), params.get("arguments") or {})
    if method in {"resources/list", "prompts/list"}:
        return {method.split("/")[0]: []}
    return _NOT_FOUND


def _call_tool(name: str | None, arguments: dict) -> dict:
    tool = _BY_NAME.get(name or "")
    if tool is None:
        return {"content": [{"type": "text", "text": f"Unknown tool {name}"}], "isError": True}
    try:
        payload = tool["fn"](**arguments)
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        return {"content": [{"type": "text", "text": str(exc)}], "isError": True}
    return {"content": [{"type": "text", "text": json.dumps(payload)}], "isError": False}


def _send(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
    sys.stdout.flush()


class _Missing:
    pass


_NOT_FOUND = _Missing()


if __name__ == "__main__":
    main()
