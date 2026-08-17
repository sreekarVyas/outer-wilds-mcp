"""Turns internal state into plain language, and strips what a player never sees.

Two separate jobs, and only the second one is about wording.

**Hiding internals.** The game never shows a fact id, a fact count, a sector id, or a
save flag. If a tool returns `facts_revealed: 239/371`, an assistant will repeat it, and
the player learns there are 371 things to find — which is itself a spoiler about the
size of the game, delivered in the vocabulary of a save file. Instructions to the
assistant are not enough here: the fix is to not send the numbers.

**Plain language.** What survives is phrased the way the game itself would put it — "a
bit over twenty minutes left", not `seconds_remaining: 1287`.

Internals are still available behind `include_internals=True`, because debugging the
resolver needs the sector id that plain output deliberately drops.
"""

from __future__ import annotations

from typing import Any

# Keys that must never reach a player-facing payload. Anything describing the save
# format, the resolver's workings, or a count the game does not display.
INTERNAL_KEYS = frozenset({
    # Save-file shape
    "loop_count", "full_timeloops", "facts_revealed", "facts_total_tracked",
    "fact_ids", "count", "revealOrder", "reveal_order", "read", "id",
    "warped_to_the_eye", "save_version", "conditions", "known_frequencies",
    "known_signals", "last_death_type", "spoiler_level", "profile",

    # Resolver workings
    "resolved_by", "unresolved_sectors", "sectors", "position_hint", "hint",
    "body_key", "entry_distance", "schema", "scene", "in_game",

    # Raw measurements. The phrased forms — time_left, direction, freshness — say the
    # same thing in words, so keeping both invites the assistant to read out the number.
    "loop", "seconds_remaining", "elapsed", "remaining", "flowing",
    "ship_distance", "distance", "bearing", "elevation",
    "local", "lat", "lon", "radial", "speed",
})


def strip_internals(data: dict[str, Any]) -> dict[str, Any]:
    """Remove internal keys, recursively, including inside lists of dicts."""
    out: dict[str, Any] = {}

    for key, value in data.items():
        if key in INTERNAL_KEYS:
            continue
        if isinstance(value, dict):
            out[key] = strip_internals(value)
        elif isinstance(value, list):
            out[key] = [strip_internals(v) if isinstance(v, dict) else v for v in value]
        else:
            out[key] = value

    return out


def time_left(seconds: float | None) -> str | None:
    """The loop timer as a person would say it.

    The player can see the sun and feel the time, so this is not a spoiler — but the
    exact second count is machine talk, and false precision besides.
    """
    if seconds is None:
        return None
    if seconds <= 0:
        return "no time left"
    if seconds < 60:
        return "less than a minute left"
    if seconds < 120:
        return "about a minute left"

    minutes = round(seconds / 60)
    if minutes >= 21:
        return "the loop has just started"
    if minutes >= 15:
        return f"around {minutes} minutes left"
    if minutes >= 5:
        return f"about {minutes} minutes left"
    return f"only {minutes} minutes left"


def freshness(age_seconds: float | None, live: bool, running: bool) -> str:
    """Whether to trust this reading, said plainly.

    `live` means the reading came from the running game rather than the save file. It
    is not evidence the game is closed — saved progress is save-sourced even mid-play —
    so the wording must not claim otherwise.
    """
    if not live:
        return "this comes from your last saved progress, not from this moment"
    if age_seconds is None or age_seconds < 5:
        return "current"
    if running:
        minutes = max(1, round(age_seconds / 60))
        unit = "minute" if minutes == 1 else "minutes"
        return f"the game has been paused for about {minutes} {unit}, so this is where you were then"
    return "the game has closed, so this may be out of date"


def distance(metres: float | None) -> str | None:
    """Distance in words. The game gives no readout, so exact metres are machine talk."""
    if metres is None:
        return None
    if metres < 15:
        return "right here"
    if metres < 60:
        return "a short walk"
    if metres < 300:
        return "a few minutes on foot"
    if metres < 2000:
        return "a long way — you will want your jetpack"
    return "far enough that you will need the ship"
