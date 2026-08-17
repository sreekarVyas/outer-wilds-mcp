"""MCP server exposing game context.

Game-agnostic: it talks only to the GameAdapter interface. Adding a game means
writing an adapter, not editing this file.
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server.mcpserver import MCPServer

from gcp import voice
from gcp.adapters.base import GameAdapter
from gcp.adapters.outer_wilds.adapter import OuterWildsAdapter

# Sent to the client when it connects. This is the behavioural contract for any
# assistant using these tools, and it is the reason the tools exist at all: a companion
# that spoils the game or reads out save-file internals is worse than no companion.
INSTRUCTIONS = """\
You are helping someone play a game they are discovering for themselves. Two rules
matter more than being helpful.

**Never spoil.** Only speak about things the player has already found. Never name a
place, an object, or an answer they have not reached yet, and never say how much of the
game is left. If they ask something whose answer they have not earned, say you would
rather not spoil it and point them at somewhere they could look.

**Nudge, do not instruct.** Give the smallest push that could unstick them — a place
worth a second look, a question worth asking, something they noted and did not follow
up. One or two sentences. Do not write step-by-step directions, do not order their next
few hours, and do not solve a puzzle for them. If they ask outright for the full answer,
give it; until then, let them find it.

**Speak like a person, not a save file.** These tools return the player's situation in
plain words, and that is how to pass it on. Never mention counts, percentages, progress
totals, internal names, ids, flags, or field names — not even in passing, and not even
if the player asks how you know. A child should follow every answer. Say "you are in the
village, in your ship" and "you have around twenty minutes", never "loop 95" or
"239 of 371".

Call get_current_context before answering anything about where the player is or what to
do next. If a tool returns nothing, call diagnose — the cause is usually a wrong path,
not a closed game.
"""

# MCP SDK 2.x. FastMCP was removed in 2.0; MCPServer is its replacement and keeps the
# same .tool() decorator and stdio-by-default .run().
mcp = MCPServer("game-context-provider", instructions=INSTRUCTIONS)

adapter: GameAdapter = OuterWildsAdapter()


def _json(result: Any, include_internals: bool = False) -> str:
    """Serialize a Sourced result, replacing machine provenance with plain wording.

    `_meta` carries source, stale and age_seconds — useful for debugging, but the sort
    of thing an assistant repeats verbatim. Player-facing responses get one sentence
    saying whether to trust the reading instead.
    """
    payload = result.to_dict()

    if not include_internals:
        meta = payload.pop("_meta", {})
        payload = voice.strip_internals(payload)
        payload["freshness"] = voice.freshness(
            meta.get("age_seconds"),
            live=meta.get("source") == "live",
            running=not meta.get("stale", True),
        )

    return json.dumps(payload, indent=2)


@mcp.tool()
def get_current_context(include_internals: bool = False) -> str:
    """Where the player is right now, in plain words. Call this before answering any
    question about their situation or what to do next.

    Returns only places the player has already found, and describes time and distance
    the way a person would. Pass these straight through — do not translate them back
    into numbers.

    include_internals is for debugging this tool, not for play. It exposes raw
    coordinates, sector ids and undiscovered places; never use it to answer a player.
    """
    spoiler_level = "full" if include_internals else "player_known"
    return _json(adapter.get_current_context(spoiler_level, include_internals),
                 include_internals)


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
def get_ship_log(include_internals: bool = False) -> str:
    """What the player has written down so far, in their own log's words.

    Grouped by place, using the game's own wording. Only entries they have actually
    found. Use this to remind someone of a lead they noted and did not follow up —
    that is usually the best nudge available, because it is already theirs.

    include_internals exposes undiscovered entries. Never use it to answer a player.
    """
    spoiler_level = "full" if include_internals else "player_known"
    return _json(adapter.get_player_known_context(spoiler_level, include_internals),
                 include_internals)


@mcp.tool()
def get_progression(include_internals: bool = False) -> str:
    """How far along the player is. Deliberately returns no number.

    A percentage spoils in both directions: it reveals how large the game is, and it
    turns a story about discovery into a progress bar. Ask about what they have found
    instead, via get_ship_log.
    """
    return _json(adapter.get_progression(include_internals), include_internals)


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
