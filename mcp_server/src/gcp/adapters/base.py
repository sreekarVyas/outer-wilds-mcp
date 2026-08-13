"""Game-agnostic adapter contract.

Nothing in this module may mention a specific game. The MCP server talks only to
this interface, so adding a game means adding an adapter, not touching the server.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class Sourced:
    """A payload plus where it came from and how much to trust its freshness.

    An assistant that cannot distinguish live data from a twenty-minute-old
    snapshot will confidently describe where the player used to be. Every
    payload carries its provenance for exactly that reason.
    """

    data: dict[str, Any]
    source: str  # "live" | "save_file" | "none"
    stale: bool = False
    age_seconds: float | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        out = dict(self.data)
        out["_meta"] = {
            "source": self.source,
            "stale": self.stale,
            "age_seconds": round(self.age_seconds, 1) if self.age_seconds is not None else None,
        }
        if self.warnings:
            out["_meta"]["warnings"] = self.warnings
        return out


class GameAdapter(Protocol):
    """One implementation per supported game."""

    game_name: str

    def get_runtime_state(self) -> Sourced:
        """Raw normalized state: position, motion, physical player status."""

    def get_location(self) -> Sourced:
        """Semantically resolved location: named place, not coordinates."""

    def get_nearby_objects(self) -> Sourced:
        """Interactables and landmarks near the player, with distances."""

    def get_progression(self) -> Sourced:
        """Progress through the game: chapters, flags, unlocks."""

    def get_player_known_context(self, spoiler_level: str = "full") -> Sourced:
        """Knowledge the player has actually discovered in-game."""

    def get_current_context(self, spoiler_level: str = "full") -> Sourced:
        """The composed answer. This is what the assistant should normally call."""

    def get_connection_status(self) -> Sourced:
        """Which sources are reachable right now."""
