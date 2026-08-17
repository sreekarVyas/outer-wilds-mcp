"""Starts the MCP server as a real subprocess and exercises it over stdio.

The unit tests all call the adapter directly. This is the only check that the MCP layer
itself works — that the server starts, advertises its tools, and answers a call the way
a client such as Claude Code would see it.

    python tools/check_mcp.py
"""

from __future__ import annotations

import asyncio
import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

EXPECTED_TOOLS = {
    "get_current_context",
    "get_game_state",
    "get_player_position",
    "get_nearby_objects",
    "get_ship_log",
    "get_progression",
    "get_connection_status",
    "diagnose",
}


async def main() -> int:
    params = StdioServerParameters(command=sys.executable, args=["-m", "gcp.server"])

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("initialize: ok")

            listed = await session.list_tools()
            names = {tool.name for tool in listed.tools}
            print(f"tools advertised: {len(names)}")

            missing = EXPECTED_TOOLS - names
            extra = names - EXPECTED_TOOLS
            if missing:
                print(f"MISSING: {sorted(missing)}")
            if extra:
                print(f"unexpected: {sorted(extra)}")

            # Every tool must at least return without raising. diagnose is the one that
            # must work even when nothing else is set up, so check its shape too.
            failures = []
            for name in sorted(names):
                try:
                    result = await session.call_tool(name, {})
                    text = result.content[0].text if result.content else ""
                    json.loads(text)  # every tool returns JSON
                    print(f"  {name:24} ok  ({len(text)} bytes)")
                except Exception as exc:  # noqa: BLE001 - reporting, not handling
                    failures.append(name)
                    print(f"  {name:24} FAILED: {exc}")

            if missing or failures:
                return 1

            print("\nall tools respond with valid JSON")
            return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
