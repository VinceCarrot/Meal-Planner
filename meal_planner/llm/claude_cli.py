"""LLM backend that runs the Claude Code CLI in non-interactive mode (ADR-003).

Each call starts `claude -p` in an empty temporary directory, with all built-in
tools disabled (except WebSearch when a structured call asks for it) and
user/project settings ignored. Structured output is enforced
with `--json-schema`. For agent calls the application tools are served from this
process over a local MCP endpoint, so they run with the application's in-memory
read-only data.
"""

import json
import logging
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from collections.abc import Sequence
from contextlib import contextmanager

from .base import LLMError, Tool

log = logging.getLogger(__name__)

_MCP_SERVER_NAME = "app"


class ClaudeCliBackend:
    def __init__(self, executable: str | None = None, model: str | None = None, timeout_s: float = 300):
        self.executable = executable
        self.model = model
        self.timeout_s = timeout_s

    def structured(self, system: str, prompt: str, output_schema: dict, web_search: bool = False) -> dict:
        if web_search:  # only the search tool; file and shell tools stay disabled
            return self._run(system, prompt, output_schema, ["--allowedTools", "WebSearch"], tools="WebSearch")
        return self._run(system, prompt, output_schema, [])

    def agent(self, system: str, prompt: str, tools: Sequence[Tool], output_schema: dict) -> dict:
        with _tool_server(tools) as url:
            config = {"mcpServers": {_MCP_SERVER_NAME: {"type": "http", "url": url}}}
            allowed = [f"mcp__{_MCP_SERVER_NAME}__{t.name}" for t in tools]
            extra = ["--mcp-config", json.dumps(config), "--allowedTools", *allowed]
            return self._run(system, prompt, output_schema, extra)

    def _run(self, system: str, prompt: str, output_schema: dict, extra_args: list[str], tools: str = "") -> dict:
        executable = self.executable or shutil.which("claude")
        if not executable:
            raise LLMError("Claude Code CLI not found; install it and make sure 'claude' is on PATH")
        cmd = [
            executable, "-p",
            "--output-format", "json",
            "--json-schema", json.dumps(cli_schema(output_schema)),
            "--system-prompt", system,
            "--tools", tools,
            "--strict-mcp-config",
            "--setting-sources", "",
            "--no-session-persistence",
        ]
        if self.model:
            cmd += ["--model", self.model]
        cmd += extra_args

        started = time.monotonic()
        with tempfile.TemporaryDirectory() as workdir:
            try:
                proc = subprocess.run(
                    cmd, input=prompt, capture_output=True, text=True, encoding="utf-8",
                    cwd=workdir, timeout=self.timeout_s,
                )
            except subprocess.TimeoutExpired:
                raise LLMError(f"Claude Code CLI timed out after {self.timeout_s:.0f}s") from None
        return _parse_result(proc, time.monotonic() - started)


def cli_schema(schema):
    """Drop keywords the CLI's strict JSON Schema check rejects (pydantic emits `discriminator`)."""
    if isinstance(schema, dict):
        return {k: cli_schema(v) for k, v in schema.items() if k != "discriminator"}
    if isinstance(schema, list):
        return [cli_schema(v) for v in schema]
    return schema


def _parse_result(proc: subprocess.CompletedProcess, seconds: float) -> dict:
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError:
        detail = " | ".join(s.strip() for s in (proc.stderr, proc.stdout) if s and s.strip())[:500]
        raise LLMError(f"Claude Code CLI failed (exit {proc.returncode}): {detail}") from None
    log.info("claude -p finished in %.1fs, turns=%s, error=%s", seconds, result.get("num_turns"), result.get("is_error"))
    if result.get("is_error") or proc.returncode != 0:
        raise LLMError(f"Claude Code CLI returned an error: {result.get('subtype')}: {str(result.get('result'))[:500]}")
    output = result.get("structured_output")
    if not isinstance(output, dict):
        raise LLMError("Claude Code CLI returned no structured output")
    return output


@contextmanager
def _tool_server(tools: Sequence[Tool]):
    """Serve `tools` over MCP (streamable HTTP) on a local port for the duration of one call."""
    import uvicorn
    from mcp.server.mcpserver import MCPServer

    server = MCPServer(_MCP_SERVER_NAME)
    for tool in tools:
        server.add_tool(tool.fn, name=tool.name, description=tool.description)

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    http = uvicorn.Server(uvicorn.Config(server.streamable_http_app(), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=http.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not http.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            raise LLMError("could not start the local tool server")
        time.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        http.should_exit = True
        thread.join(timeout=5)
