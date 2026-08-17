"""MCP server exposing game context.

Game-agnostic: it talks only to the GameAdapter interface. Adding a game means
writing an adapter, not editing this file.
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server.mcpserver import MCPServer

from gcp.adapters.base import GameAdapter
from gcp.adapters.outer_wilds.adapter import OuterWildsAdapter

# MCP SDK 2.x. FastMCP was removed in 2.0; MCPServer is its replacement and keeps the
# same .tool() decorator and stdio-by-default .run().
mcp = MCPServer("game-context-provider")

adapter: GameAdapter = OuterWildsAdapter()


def _json(result: Any) -> str:
    return json.dumps(result.to_dict(), indent=2)


@mcp.tool()
def get_current_context(spoiler_level: str = "full") -> str:
    """Where the player is and what matters right now. Call this before answering
    any question about the player's current situation in the game.

    spoiler_level: "full" exposes everything; "player_known" limits knowledge to
    facts the player has actually discovered.
    """
    return _json(adapter.get_current_context(spoiler_level))


@mcp.tool()
def get_game_state() -> str:
    """High-level runtime state: scene, body, player status, time loop."""
    return _json(adapter.get_runtime_state())


@mcp.tool()
def get_player_position() -> str:
    """Semantically resolved location, plus body-local coordinates."""
    return _json(adapter.get_location())


@mcp.tool()
def get_nearby_objects() -> str:
    """Tracked objects near the player, with distances."""
    return _json(adapter.get_nearby_objects())


@mcp.tool()
def get_ship_log(spoiler_level: str = "full") -> str:
    """Knowledge the player has discovered, from the save file."""
    return _json(adapter.get_player_known_context(spoiler_level))


@mcp.tool()
def get_progression() -> str:
    """Overall progress: loop count, revealed facts, story conditions."""
    return _json(adapter.get_progression())


@mcp.tool()
def get_connection_status() -> str:
    """Which data sources are reachable and how fresh they are. Check this when
    the context looks wrong or empty."""
    return _json(adapter.get_connection_status())


@mcp.tool()
def diagnose() -> str:
    """Every path the server resolved, how it was resolved, and how to fix what is
    missing. Call this when a tool reports no data — the cause is usually a path,
    and 'game not running' points at the wrong problem."""
    from gcp import doctor

    return json.dumps(doctor.run().to_dict(), indent=2)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
