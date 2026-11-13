"""The agent: an LLM that chooses tools exposed by the MCP server, reads results, and answers.

The agent is an MCP *client*: it launches the server as a subprocess (stdio), discovers its
tools, hands them to the model in Anthropic tool-use format, and runs the tool-use loop.
"""
from __future__ import annotations

import json
import os
import sys
from contextlib import AsyncExitStack
from dataclasses import dataclass, field

from anthropic import AsyncAnthropic
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import get_default_environment, stdio_client

from drivefleet.config import SRC_DIR, get_settings
from drivefleet.tools.sql_tool import run_readonly_query

SYSTEM_PROMPT = """You are the DriveFleet Assistant, answering questions about a fleet of hard drives.
Dataset as-of date ("today"): {as_of}. "Last quarter" means the most recent complete calendar
quarter before that date.

You have tools. Pick the right one(s); never guess facts a tool can give you:
- query_fleet_db: counts, rankings, failures, SMART stats, warranty dates/status (SQL, read-only).
- predict_drive_risk: failure risk for ONE drive serial.
- list_high_risk_drives: model-scored list of active drives at/above a risk tier.
- search_datasheets: product specs and warranty TERMS for drive models (not in the database).
- describe_schema: table/column details if you are unsure before writing SQL.

Rules:
- For questions that need several sources (e.g. high-risk drives that are still under warranty),
  call the tools in sequence and combine the results. Warranty status for specific drives comes
  from the database (drive_status view), not from the datasheet.
- If a tool returns an error, read it, fix your call, and retry.
- You can only read data. If asked to change, delete or update anything, say you cannot.
- Base every number on tool output. Be concise: lead with the answer, then brief supporting
  detail (and which source it came from). If the data cannot answer, say so.
"""


@dataclass
class AgentResult:
    answer: str
    tool_calls: list[dict] = field(default_factory=list)
    steps: int = 0

    @property
    def tools_used(self) -> list[str]:
        return [c["name"] for c in self.tool_calls]


def _server_env() -> dict[str, str]:
    env = dict(get_default_environment())
    for key, val in os.environ.items():
        if key.startswith("DRIVEFLEET_"):
            env[key] = val
    existing = os.environ.get("PYTHONPATH")
    env["PYTHONPATH"] = os.pathsep.join(p for p in [str(SRC_DIR), existing] if p)
    return env


class FleetAgent:
    """Use as an async context manager:  async with FleetAgent() as agent: await agent.ask(...)"""

    def __init__(self, model: str | None = None, max_steps: int | None = None, client=None):
        s = get_settings()
        self.model = model or s.anthropic_model
        self.max_steps = max_steps or s.max_agent_steps
        self.client = client or AsyncAnthropic()
        self._stack = AsyncExitStack()
        self.session: ClientSession | None = None
        self.tools: list[dict] = []
        self.system = ""

    async def __aenter__(self) -> FleetAgent:
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "drivefleet.mcp_server.server"], env=_server_env()
        )
        read, write = await self._stack.enter_async_context(stdio_client(params))
        self.session = await self._stack.enter_async_context(ClientSession(read, write))
        await self.session.initialize()
        listed = await self.session.list_tools()
        self.tools = [
            {"name": t.name, "description": t.description or "", "input_schema": t.inputSchema}
            for t in listed.tools
        ]
        as_of = run_readonly_query("SELECT value FROM meta WHERE key='as_of_date'")["rows"][0][0]
        self.system = SYSTEM_PROMPT.format(as_of=as_of)
        return self

    async def __aexit__(self, *exc) -> None:
        await self._stack.aclose()

    async def _call_tool(self, name: str, args: dict) -> tuple[str, bool]:
        result = await self.session.call_tool(name, args)
        text = "".join(c.text for c in result.content if getattr(c, "type", "") == "text")
        return text, bool(result.isError)

    async def ask(self, question: str, history: list[dict] | None = None) -> AgentResult:
        """Answer one question. Pass `history` (mutated in place) to keep a conversation."""
        messages = history if history is not None else []
        messages.append({"role": "user", "content": question})
        calls: list[dict] = []
        for step in range(1, self.max_steps + 1):
            resp = await self.client.messages.create(
                model=self.model, max_tokens=1500, system=self.system,
                tools=self.tools, messages=messages,
            )
            messages.append({"role": "assistant", "content": resp.content})
            if resp.stop_reason != "tool_use":
                answer = "".join(b.text for b in resp.content if b.type == "text").strip()
                return AgentResult(answer, calls, step)
            results = []
            for block in resp.content:
                if block.type != "tool_use":
                    continue
                text, is_error = await self._call_tool(block.name, block.input)
                calls.append({"name": block.name, "input": block.input, "output": text[:2000]})
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": text, "is_error": is_error})
            messages.append({"role": "user", "content": results})
        return AgentResult("I could not finish within the step limit.", calls, self.max_steps)


def format_trace(result: AgentResult) -> str:
    lines = []
    for c in result.tool_calls:
        lines.append(f"  -> {c['name']}({json.dumps(c['input'])[:160]})")
    return "\n".join(lines)
