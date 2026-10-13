"""Unit tests for the Claude Code CLI backend; the CLI itself is replaced by a fake."""

import json
import socket
import subprocess
from pathlib import Path

import pytest

from meal_planner.constraint_parser import ParserOutput
from meal_planner.llm import LLMError, Tool, create_backend
from meal_planner.llm import claude_cli
from meal_planner.llm.claude_cli import ClaudeCliBackend, cli_schema

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}}


@pytest.fixture
def fake_run(monkeypatch):
    """Replace subprocess.run; `fake_run.reply` sets what the CLI returns."""

    class Fake:
        def __init__(self):
            self.calls = []
            self.reply = {"is_error": False, "subtype": "success", "structured_output": {"ok": True}}
            self.returncode = 0
            self.during_call = None

        def __call__(self, cmd, **kwargs):
            self.calls.append({"cmd": cmd, **kwargs})
            if self.during_call:
                self.during_call(cmd)
            stdout = self.reply if isinstance(self.reply, str) else json.dumps(self.reply)
            return subprocess.CompletedProcess(cmd, self.returncode, stdout=stdout, stderr="boom")

    fake = Fake()
    monkeypatch.setattr(claude_cli.subprocess, "run", fake)
    return fake


@pytest.fixture
def backend():
    return ClaudeCliBackend(executable="claude-test")


def _flag(cmd, name):
    return cmd[cmd.index(name) + 1]


def test_create_backend_by_name():
    assert isinstance(create_backend("claude_cli"), ClaudeCliBackend)
    with pytest.raises(ValueError):
        create_backend("local")


def test_structured_call_isolates_the_cli(fake_run, backend):
    assert backend.structured("system text", "prompt text", SCHEMA) == {"ok": True}
    call = fake_run.calls[0]
    cmd = call["cmd"]
    assert cmd[:2] == ["claude-test", "-p"]
    assert _flag(cmd, "--tools") == ""  # no built-in tools: no file or shell access
    assert _flag(cmd, "--setting-sources") == ""
    assert "--strict-mcp-config" in cmd and "--no-session-persistence" in cmd
    assert "--mcp-config" not in cmd
    assert _flag(cmd, "--system-prompt") == "system text"
    assert json.loads(_flag(cmd, "--json-schema")) == SCHEMA
    assert call["input"] == "prompt text"
    assert not (Path(call["cwd"]) / "CLAUDE.md").exists()
    assert Path(call["cwd"]).resolve() != Path.cwd().resolve()


def test_web_search_enables_only_the_search_tool(fake_run, backend):
    backend.structured("s", "p", SCHEMA, web_search=True)
    cmd = fake_run.calls[0]["cmd"]
    assert _flag(cmd, "--tools") == "WebSearch" and _flag(cmd, "--allowedTools") == "WebSearch"
    assert _flag(cmd, "--setting-sources") == "" and "--strict-mcp-config" in cmd


def test_model_option_is_passed(fake_run):
    ClaudeCliBackend(executable="claude-test", model="sonnet").structured("s", "p", SCHEMA)
    assert _flag(fake_run.calls[0]["cmd"], "--model") == "sonnet"


def test_pydantic_schema_is_made_cli_compatible():
    schema = ParserOutput.model_json_schema()
    assert "discriminator" in json.dumps(schema)
    assert "discriminator" not in json.dumps(cli_schema(schema))


@pytest.mark.parametrize(
    "reply, returncode, message",
    [
        ({"is_error": True, "subtype": "error_max_turns", "result": "x"}, 1, "error_max_turns"),
        ({"is_error": False, "subtype": "success", "result": "text only"}, 0, "no structured output"),
        ("Error: not logged in", 1, "not logged in"),
    ],
)
def test_cli_failures_raise_llm_error(fake_run, backend, reply, returncode, message):
    fake_run.reply, fake_run.returncode = reply, returncode
    with pytest.raises(LLMError, match=message):
        backend.structured("s", "p", SCHEMA)


def test_cli_stderr_is_reported_when_stdout_is_not_json(fake_run, backend):
    fake_run.reply = ""
    with pytest.raises(LLMError, match="boom"):
        backend.structured("s", "p", SCHEMA)


def test_timeout_raises_llm_error(monkeypatch, backend):
    def timeout(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

    monkeypatch.setattr(claude_cli.subprocess, "run", timeout)
    with pytest.raises(LLMError, match="timed out"):
        backend.structured("s", "p", SCHEMA)


def test_missing_cli_raises_llm_error(monkeypatch):
    monkeypatch.setattr(claude_cli.shutil, "which", lambda name: None)
    with pytest.raises(LLMError, match="not found"):
        ClaudeCliBackend().structured("s", "p", SCHEMA)


def test_agent_call_serves_tools_only_during_the_call(fake_run, backend):
    def find(keyword: str) -> list[str]:
        return [keyword]

    seen = {}

    def check_server(cmd):
        url = json.loads(_flag(cmd, "--mcp-config"))["mcpServers"]["app"]["url"]
        seen["port"] = int(url.split(":")[2].split("/")[0])
        with socket.create_connection(("127.0.0.1", seen["port"]), timeout=2):
            pass

    fake_run.during_call = check_server
    backend.agent("s", "p", [Tool("find", "Find things.", find)], SCHEMA)

    cmd = fake_run.calls[0]["cmd"]
    assert _flag(cmd, "--allowedTools") == "mcp__app__find"
    assert _flag(cmd, "--tools") == ""
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", seen["port"]), timeout=1)
