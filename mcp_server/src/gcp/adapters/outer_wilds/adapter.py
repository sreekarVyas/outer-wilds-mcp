"""Outer Wilds adapter: merges the live plugin snapshot with the save file."""

from __future__ import annotations

from typing import Any

from gcp import voice
from gcp.adapters.base import Sourced

from . import direction
from .resolver import Resolver
from .save_reader import SaveReader
from .shiplog_text import ShipLogText
from .snapshot_source import SnapshotSource

PROCESS_NAME = "OuterWilds"


def game_is_running() -> bool:
    """True while the game process exists, whether or not it is focused."""
    import subprocess

    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {PROCESS_NAME}.exe", "/NH"],
            capture_output=True, text=True, timeout=5,
        )
        return PROCESS_NAME.lower() in out.stdout.lower()
    except (OSError, subprocess.SubprocessError):
        return False


class OuterWildsAdapter:
    game_name = "Outer Wilds"

    def __init__(self) -> None:
        self.snapshots = SnapshotSource()
        self.saves = SaveReader()
        self.resolver = Resolver()
        self.text = ShipLogText()

    # --- source handling -------------------------------------------------

    def _live(self) -> tuple[dict[str, Any] | None, list[str], bool, float | None]:
        """Returns (snapshot, warnings, stale, age). Snapshot is None when unavailable.

        Outer Wilds pauses when it loses focus, which is exactly what happens while the
        player is talking to the assistant. An old snapshot is therefore the normal case
        and the data is still accurate — so age alone must not be reported as staleness.
        Only treat it as stale when the game process is actually gone.
        """
        snapshot, warnings = self.snapshots.read()
        if snapshot is None:
            return None, warnings, True, None

        age = self.snapshots.age(snapshot)
        old = self.snapshots.is_stale(snapshot)

        if not old:
            return snapshot, warnings, False, age

        if game_is_running():
            # Paused or alt-tabbed: frozen, not wrong.
            warnings.append(f"game paused or unfocused for {age:.0f}s — state is accurate as of then")
            return snapshot, warnings, False, age

        warnings.append(f"game is not running; snapshot is {age:.0f}s old and may be wrong")
        return snapshot, warnings, True, age

    @staticmethod
    def _unavailable(warnings: list[str]) -> Sourced:
        return Sourced(
            data={"available": False, "reason": "no live game data"},
            source="none",
            stale=True,
            warnings=warnings,
        )

    # --- GameAdapter -----------------------------------------------------

    def get_runtime_state(self) -> Sourced:
        snapshot, warnings, stale, age = self._live()
        if snapshot is None:
            return self._unavailable(warnings)

        return Sourced(
            data={
                "in_game": snapshot.get("in_game", False),
                "scene": snapshot.get("scene"),
                "body": snapshot.get("body"),
                "player": snapshot.get("player"),
                "loop": snapshot.get("loop"),
            },
            source="live",
            stale=stale,
            age_seconds=age,
            warnings=warnings,
        )

    def get_location(self) -> Sourced:
        snapshot, warnings, stale, age = self._live()
        if snapshot is None:
            return self._unavailable(warnings)

        return Sourced(
            data=self.resolver.resolve(snapshot),
            source="live",
            stale=stale,
            age_seconds=age,
            warnings=warnings,
        )

    def get_nearby_objects(self) -> Sourced:
        # Not implemented in schema 1. The plugin currently reports only ship and probe;
        # a real proximity query needs a physics sweep plus an ontology of what counts
        # as interesting, which is deliberately deferred.
        snapshot, warnings, stale, age = self._live()
        if snapshot is None:
            return self._unavailable(warnings)

        return Sourced(
            data={
                "ship": direction.annotate(snapshot.get("ship")),
                "probe": direction.annotate(snapshot.get("probe")),
                "markers": [direction.annotate(e) for e in (snapshot.get("nearby_entries") or [])],
            },
            source="live",
            stale=stale,
            age_seconds=age,
            warnings=warnings,
        )

    def get_progression(self, include_internals: bool = False) -> Sourced:
        """How far along the player is — deliberately vague.

        A percentage is a spoiler in both directions: it reveals the size of the game,
        and "you are 64% done" flattens a story about discovery into a progress bar.
        The internal summary is still available for debugging.
        """
        save = self.saves.get()
        if save is None:
            return self._unavailable(["no save file found"])

        if include_internals:
            data = save.summary()
        else:
            data = {
                "note": (
                    "Progress is deliberately not reported as a number. Ask about what "
                    "the player has found instead."
                ),
            }

        return Sourced(
            data=data,
            source="save_file",
            stale=True,  # always: the save is only written at loop end and on quit
            age_seconds=save.age_seconds,
            warnings=["saved progress reflects the last write, not this moment"],
        )

    def get_player_known_context(self, spoiler_level: str = "player_known",
                                 include_internals: bool = False) -> Sourced:
        save = self.saves.get()
        if save is None:
            return self._unavailable(["no Outer Wilds save file found"])

        # Defaults to what the player has actually found. "full" exposes the whole log
        # including undiscovered entries, and exists for debugging, not for play.
        facts = list(save.facts) if spoiler_level == "full" else save.revealed_facts

        data: dict[str, Any] = {"spoiler_level": spoiler_level, "count": len(facts)}

        if self.text.available:
            # Grouped under entry names and carrying the game's own wording — this is
            # what the player would read in their own ship log, nothing more.
            data["entries"] = self.text.group_by_entry(facts)
        elif include_internals:
            data["fact_ids"] = facts
        else:
            # Bare ids are meaningless to a player and pure machine talk. Say what is
            # missing instead of dumping 371 identifiers.
            data["note"] = (
                "The written notes are not available yet. Start the game and load your "
                "save once, and they will be."
            )

        if not include_internals:
            data = voice.strip_internals(data)

        return Sourced(
            data=data,
            source="save_file",
            stale=True,
            age_seconds=save.age_seconds,
            warnings=self.text.warnings,
        )

    def get_current_context(self, spoiler_level: str = "player_known",
                            include_internals: bool = False) -> Sourced:
        """The composed answer — the tool the assistant should normally call.

        Player-facing by default: no counts, no ids, no save flags. Those are stripped
        rather than merely discouraged, because an assistant repeats whatever it is
        given, and "239 of 371 facts" tells the player how big the game is in the
        vocabulary of a save file.
        """
        snapshot, warnings, stale, age = self._live()
        save = self.saves.get()

        data: dict[str, Any] = {"game": self.game_name}

        if snapshot is None or not snapshot.get("in_game"):
            data["live"] = False
            data["note"] = "the game is not running, or you are not in the world yet"
        else:
            player = snapshot.get("player") or {}
            loop = snapshot.get("loop") or {}
            location = self.resolver.resolve(snapshot)

            data["live"] = True
            data["planet"] = location.get("body")
            data["location"] = location.get("location")
            data["sub_location"] = location.get("sub_location")
            data["inside"] = location.get("inside")  # the ship or a shuttle, when applicable
            data["hazards"] = location.get("hazards")
            data["landmarks"] = location.get("landmarks")
            data["resolved_by"] = location.get("resolved_by")
            if location.get("resolved_by") == "unresolved":
                data["unresolved_sectors"] = location.get("unresolved_sectors")
                data["position_hint"] = location.get("hint")

            data["player_state"] = _describe_player(player)
            data["time_left"] = voice.time_left(loop.get("remaining"))
            data["loop"] = {
                "count": loop.get("count"),
                "seconds_remaining": round(loop.get("remaining", 0)),
                "flowing": loop.get("flowing"),
            }
            ship = direction.annotate(snapshot.get("ship")) or {}
            data["ship_distance"] = ship.get("distance")
            data["ship_direction"] = ship.get("direction")

            # Markers with directions: the answer to "where do I go from here".
            #
            # These carry the game's own name for a place, which is exactly why they
            # have to be filtered: a marker exists for every location in the game,
            # discovered or not. Naming an undiscovered one is a spoiler delivered by
            # the tool itself, which no instruction to the assistant can undo.
            markers = [direction.annotate(e) for e in (snapshot.get("nearby_entries") or [])]
            if spoiler_level != "full":
                known = self._known_entry_ids(save)
                markers = [m for m in markers if m.get("id") in known]

            data["nearby"] = [
                {"name": m.get("name"), "direction": m.get("direction")}
                for m in markers if m.get("direction")
            ]

        if not include_internals:
            data = voice.strip_internals(data)

        return Sourced(
            data=data,
            source="live" if snapshot is not None else "save_file",
            stale=stale if snapshot is not None else True,
            age_seconds=age,
            warnings=warnings,
        )

    def _known_entry_ids(self, save) -> set[str]:
        """Ship log entries the player has found at least one fact for.

        Entry ids are not in the save, only fact ids — so this maps facts back to their
        entry through the dump. With no dump available, nothing can be shown to be known,
        and the safe answer is to show nothing rather than everything.
        """
        if save is None or not self.text.available:
            return set()

        known: set[str] = set()
        for fact_id in save.revealed_facts:
            fact = self.text.fact(fact_id)
            if fact is not None:
                known.add(fact.entry_id)
        return known

    def get_connection_status(self) -> Sourced:
        snapshot, warnings, stale, age = self._live()
        save = self.saves.get()

        return Sourced(
            data={
                "live_plugin": {
                    "connected": snapshot is not None,
                    "path": str(self.snapshots.path),
                    "age_seconds": round(age, 1) if age is not None else None,
                    "stale": stale,
                },
                "save_file": {
                    "found": save is not None,
                    "profile": save.profile if save else None,
                    "age_seconds": round(save.age_seconds) if save else None,
                },
            },
            source="live" if snapshot is not None else "none",
            stale=stale,
            warnings=warnings,
        )


def _describe_player(player: dict[str, Any]) -> str:
    """Collapse the boolean soup into one phrase the assistant can act on."""
    if player.get("dead"):
        return "dead"
    if player.get("in_ship"):
        return "at the flight console" if player.get("at_flight_console") else "inside the ship"
    if player.get("in_dream"):
        return "in the dream world"
    if player.get("underwater"):
        return "underwater"
    if player.get("grounded"):
        return "on foot" if player.get("suited") else "on foot, no suit"
    if player.get("zero_g"):
        return "floating in zero gravity"
    return "in flight"
