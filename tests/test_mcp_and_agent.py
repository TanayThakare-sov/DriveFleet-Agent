"""End-to-end through a real MCP stdio server subprocess; the LLM is scripted (no API key)."""
import asyncio
import json
import sys
from types import SimpleNamespace as NS

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from drivefleet.agent.agent import FleetAgent, _server_env

EXPECTED_TOOLS = {"describe_schema", "query_fleet_db", "predict_drive_risk",
                  "list_high_risk_drives", "search_datasheets"}


def _params():
    return StdioServerParameters(command=sys.executable, args=["-m", "drivefleet.mcp_server.server"],
                                 env=_server_env())


def test_server_lists_and_runs_tools():
    async def go():
        async with stdio_client(_params()) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            names = {t.name for t in (await s.list_tools()).tools}
            assert names == EXPECTED_TOOLS
            res = await s.call_tool("query_fleet_db", {"sql": "SELECT COUNT(*) FROM drives"})
            assert json.loads(res.content[0].text)["rows"] == [[600]]
            bad = await s.call_tool("query_fleet_db", {"sql": "DROP TABLE drives"})
            assert "error" in json.loads(bad.content[0].text)
            again = await s.call_tool("query_fleet_db", {"sql": "SELECT COUNT(*) FROM drives"})
            assert json.loads(again.content[0].text)["rows"] == [[600]]
    asyncio.run(go())


class FakeClient:
    """Scripted stand-in for AsyncAnthropic: tool call first, then a final answer."""

    def __init__(self):
        self.calls = 0
        self.messages = NS(create=self._create)

    async def _create(self, **kw):
        self.calls += 1
        if self.calls == 1:
            blk = NS(type="tool_use", id="t1", name="predict_drive_risk", input={"serial": "SN00157"})
            return NS(stop_reason="tool_use", content=[blk])
        last = kw["messages"][-1]["content"][0]
        assert last["tool_use_id"] == "t1" and "risk_tier" in last["content"]
        return NS(stop_reason="end_turn", content=[NS(type="text", text="SN00157 is high risk.")])


def test_agent_tool_loop():
    async def go():
        async with FleetAgent(client=FakeClient()) as agent:
            assert {t["name"] for t in agent.tools} == EXPECTED_TOOLS
            assert "2025-07-15" in agent.system
            res = await agent.ask("Is drive SN00157 at risk?")
            assert res.tools_used == ["predict_drive_risk"]
            assert "high risk" in res.answer and res.steps == 2
    asyncio.run(go())
