"""Turns machine state into a place name.

Resolution order, first match wins:
  1. innermost sector id present in the ontology
  2. successively outer sectors in the stack
  3. a body-local region rule (lat/lon band with a radial range)
  4. the body name, marked unresolved

The ontology is a JSON file, hot-reloaded on mtime, so naming a new place never
needs a mod rebuild or a game restart.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ONTOLOGY_DIR = Path(__file__).resolve().parents[2] / "ontology" / "outer_wilds"

# A ship-log marker further away than this describes somewhere else, not here.
NEAR_ENTRY_METRES = 200.0


def _apply_container(result: dict[str, Any], container: dict[str, Any] | None) -> None:
    """Record the vehicle the player is inside without letting it hide the place."""
    if container is None:
        return
    result["inside"] = container.get("name")
    result["landmarks"] = list(result.get("landmarks") or []) + list(container.get("landmarks") or [])


class Resolver:
    def __init__(self, ontology_dir: Path | None = None) -> None:
        self.dir = ontology_dir or ONTOLOGY_DIR
        self._locations: dict[str, Any] = {}
        self._bodies: dict[str, Any] = {}
        self._mtimes: dict[str, float] = {}
        self.reload_if_changed()

    def reload_if_changed(self) -> None:
        for name, target in (("locations", "_locations"), ("bodies", "_bodies")):
            path = self.dir / f"{name}.json"
            if not path.exists():
                continue
            mtime = path.stat().st_mtime
            if self._mtimes.get(name) == mtime:
                continue
            setattr(self, target, json.loads(path.read_text(encoding="utf-8")))
            self._mtimes[name] = mtime

    def resolve(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        self.reload_if_changed()

        body_key = snapshot.get("body")
        body = self._bodies.get(body_key, {})
        sectors = snapshot.get("sectors") or []
        player = snapshot.get("player") or {}

        result: dict[str, Any] = {
            "body": body.get("name", body_key),
            "body_key": body_key,
            "location": None,
            "sub_location": None,
            "landmarks": [],
            "hazards": list(snapshot.get("hazards") or []),
            "resolved_by": None,
        }

        # Sort the sector stack into three kinds, innermost first.
        #
        #   container — the ship or a shuttle. Travels with the player, so it says what
        #               they are inside, never where they are.
        #   broad     — the whole celestial body. True, but no more precise than a marker
        #               40 m away, so it must not outrank one.
        #   specific  — an actual named place. Always wins.
        container: dict[str, Any] | None = None
        broad: dict[str, Any] | None = None
        specific: dict[str, Any] | None = None

        for sector_id in reversed(sectors):
            entry = self._locations.get(sector_id)
            if entry is None:
                continue

            if entry.get("container"):
                container = container or {"id": sector_id, **entry}
            elif entry.get("broad") or sector_id == body_key:
                broad = broad or {"id": sector_id, **entry}
            elif specific is None:
                specific = {"id": sector_id, **entry}

        # 1 — a specific named sector.
        if specific is not None:
            self._fill(result, specific, f"sector:{specific['id']}")
            _apply_container(result, container)
            return result

        # 2 — the game's own name for this place. ShipLogEntryLocation markers are placed
        # by the designers and carry the official display name, so they beat both a broad
        # sector and any name a human infers from a sector id.
        entries = snapshot.get("nearby_entries") or []
        if entries and entries[0].get("distance", 1e9) <= NEAR_ENTRY_METRES:
            nearest = entries[0]
            result["location"] = nearest.get("name")
            result["landmarks"] = [e["name"] for e in entries[1:] if e.get("name")]
            result["resolved_by"] = f"ship_log_entry:{nearest.get('id')}"
            result["entry_distance"] = round(nearest.get("distance", 0), 1)
            _apply_container(result, container)
            return result

        # 3 — the body itself.
        if broad is not None:
            self._fill(result, broad, f"sector:{broad['id']}")
            _apply_container(result, container)
            return result

        # 4 — geometric fallback, in the body's own frame so it survives orbit and spin.
        region = self._match_region(body, player)
        if region is not None:
            result["location"] = region.get("name")
            result["landmarks"] = region.get("landmarks", [])
            result["hazards"] = sorted(set(result["hazards"]) | set(region.get("hazards", [])))
            result["resolved_by"] = "region"
            _apply_container(result, container)
            return result

        # 4 — honest failure. The unresolved sector ids are exactly what you paste
        # into locations.json to name this place.
        result["location"] = body.get("name", body_key)
        result["resolved_by"] = "unresolved"
        result["unresolved_sectors"] = sectors
        _apply_container(result, container)
        result["hint"] = {
            "lat": player.get("lat"),
            "lon": player.get("lon"),
            "radial": player.get("radial"),
        }
        return result

    @staticmethod
    def _fill(result: dict[str, Any], entry: dict[str, Any], resolved_by: str) -> None:
        result["location"] = entry.get("name", entry.get("id"))
        result["sub_location"] = entry.get("sub_location")
        result["landmarks"] = entry.get("landmarks", [])
        result["hazards"] = sorted(set(result["hazards"]) | set(entry.get("hazards", [])))
        result["resolved_by"] = resolved_by

    @staticmethod
    def _match_region(body: dict[str, Any], player: dict[str, Any]) -> dict[str, Any] | None:
        lat, lon, radial = player.get("lat"), player.get("lon"), player.get("radial")
        if lat is None or lon is None or radial is None:
            return None

        for region in body.get("regions", []):
            lat_min, lat_max = region.get("lat", [-90, 90])
            lon_min, lon_max = region.get("lon", [-180, 180])
            r_min, r_max = region.get("radial", [0, float("inf")])

            if not (lat_min <= lat <= lat_max and r_min <= radial <= r_max):
                continue
            # Longitude bands may wrap past the antimeridian.
            if lon_min <= lon_max:
                if not lon_min <= lon <= lon_max:
                    continue
            elif not (lon >= lon_min or lon <= lon_max):
                continue

            return region

        return None
