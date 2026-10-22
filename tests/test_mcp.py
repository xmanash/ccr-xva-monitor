import json
import os
import subprocess
import sys

from ccr_xva.utils.paths import repo_root


def _request(proc, message: dict) -> dict:
    proc.stdin.write(json.dumps(message) + "\n")
    proc.stdin.flush()
    line = proc.stdout.readline()
    assert line, proc.stderr.read() if proc.stderr else "MCP server closed stdout"
    return json.loads(line)


def test_mcp_server_lists_tools_and_answers(tmp_path):
    database = tmp_path / "mcp.db"
    env = os.environ.copy()
    env["CCR_DATABASE_URL"] = f"sqlite:///{database.as_posix()}"
    env["CCR_CHROMA_PATH"] = str(tmp_path / "chroma")
    env["CCR_LLM_ENABLED"] = "false"
    env["CCR_ROOT"] = str(repo_root())
    proc = subprocess.Popen(
        [sys.executable, "-m", "ccr_xva.mcp.server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        cwd=repo_root(),
    )
    try:
        started = _request(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}},
            },
        )
        assert started["result"]["serverInfo"]["name"] == "ccr-xva"
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        proc.stdin.flush()
        listed = _request(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        names = {tool["name"] for tool in listed["result"]["tools"]}
        assert {"list_book", "load_sample_book", "calculate_exposure", "calculate_xva", "ask_risk"} <= names
        loaded = _request(proc, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "load_sample_book", "arguments": {}}})
        assert loaded["result"]["isError"] is False
        asked = _request(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "ask_risk",
                    "arguments": {"query": "What is the current peak PFE for ABC bank and risk driver", "n_paths": 20},
                },
            },
        )
        assert asked["result"]["isError"] is False
        body = json.loads(asked["result"]["content"][0]["text"])
        assert "ABC Bank" in body["answer"]
        assert body["calculation_id"]
    finally:
        proc.stdin.close()
        proc.wait(timeout=20)
