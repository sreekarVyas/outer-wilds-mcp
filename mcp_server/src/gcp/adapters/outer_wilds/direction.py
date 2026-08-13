"""Turns bearing and elevation angles into words a player can act on.

"61 metres away" does not help anyone find anything. "Just right, below you, 61 m"
does. The plugin supplies the angles; this turns them into an instruction.

Bearing is degrees around the local up axis from where the camera looks:
0 ahead, +90 right, -90 left, ±180 behind. Elevation is degrees above the local
horizon.
"""

from __future__ import annotations

from typing import Any

# Bearing bands, as (upper bound on |bearing|, phrase for that band).
# The first band is deliberately wide: inside 20 degrees a player reads it as "ahead"
# and a more precise word would be false precision.
_BEARING_BANDS = [
    (20.0, "straight ahead"),
    (65.0, "ahead and to your {side}"),
    (115.0, "to your {side}"),
    (160.0, "behind you and to your {side}"),
    (180.0, "directly behind you"),
]

_ELEVATION_BANDS = [
    (15.0, ""),
    (50.0, "{updown} you"),
    (90.0, "{updown}, steeply"),
]


def describe(bearing: float | None, elevation: float | None, distance: float | None) -> str | None:
    """One phrase combining direction, slope, and range. None when direction is unknown."""
    if bearing is None:
        return None

    parts = [_bearing_phrase(bearing)]

    vertical = _elevation_phrase(elevation)
    if vertical:
        parts.append(vertical)

    if distance is not None:
        parts.append(_distance_phrase(distance))

    return ", ".join(parts)


def _bearing_phrase(bearing: float) -> str:
    side = "right" if bearing >= 0 else "left"
    magnitude = abs(bearing)

    for limit, template in _BEARING_BANDS:
        if magnitude <= limit:
            return template.format(side=side)

    return "directly behind you"


def _elevation_phrase(elevation: float | None) -> str:
    if elevation is None:
        return ""

    updown = "above" if elevation >= 0 else "below"
    magnitude = abs(elevation)

    for limit, template in _ELEVATION_BANDS:
        if magnitude <= limit:
            return template.format(updown=updown)

    return f"{updown}, steeply"


def _distance_phrase(distance: float) -> str:
    if distance < 1000:
        return f"{round(distance)} m"
    return f"{distance / 1000:.1f} km"


def annotate(target: dict[str, Any] | None) -> dict[str, Any] | None:
    """Add a `direction` phrase to a marker or object, leaving the raw angles intact."""
    if not target:
        return target

    phrase = describe(target.get("bearing"), target.get("elevation"), target.get("distance"))
    if phrase is not None:
        target = {**target, "direction": phrase}
    return target
