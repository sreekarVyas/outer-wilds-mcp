"""Reads the ship log text dumped by the plugin.

The save file says which fact ids a player holds. It never says what they mean.
`CT_SUNLESS_CITY_X3` is a label. This turns it back into a sentence.

The dump is static reference data describing the game, not the player, so it is
written once by the plugin and reused. It contains every fact, including ones the
player has not revealed — filtering by discovery happens here, at the boundary.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gcp import config

SUPPORTED_SCHEMA = 1


@dataclass(frozen=True)
class FactText:
    id: str
    text: str
    rumor: bool
    entry_id: str
    entry_name: str
    astro_object: str | None
    source: str | None


class ShipLogText:
    """Fact id and entry id lookups, loaded once and refreshed if the dump changes."""

    def __init__(self, path: Path | None = None) -> None:
        self.resolved = config.shiplog_path(path)
        self.path = self.resolved.value
        self._facts: dict[str, FactText] = {}
        self._entries: dict[str, str] = {}
        self._mtime: float = -1.0
        self._warnings: list[str] = []

    @property
    def available(self) -> bool:
        self._load_if_changed()
        return bool(self._facts)

    @property
    def warnings(self) -> list[str]:
        self._load_if_changed()
        return list(self._warnings)

    def _load_if_changed(self) -> None:
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            if not self._warnings:
                self._warnings = [
                    f"no ship log dump at {self.path} — fact ids will have no text. "
                    "Run the game once with the plugin to generate it."
                ]
            return

        if mtime == self._mtime:
            return

        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self._warnings = [f"ship log dump unreadable: {exc}"]
            return

        warnings: list[str] = []
        if data.get("schema") != SUPPORTED_SCHEMA:
            warnings.append(
                f"ship log dump schema {data.get('schema')}, expected {SUPPORTED_SCHEMA}"
            )

        facts: dict[str, FactText] = {}
        entries: dict[str, str] = {}

        for entry in data.get("entries", []):
            entry_id = entry.get("id")
            entry_name = entry.get("name") or entry_id
            entries[entry_id] = entry_name

            for fact in entry.get("facts", []):
                fact_id = fact.get("id")
                if not fact_id:
                    continue
                facts[fact_id] = FactText(
                    id=fact_id,
                    text=(fact.get("text") or "").strip(),
                    rumor=bool(fact.get("rumor")),
                    entry_id=entry_id,
                    entry_name=entry_name,
                    astro_object=entry.get("astro_object"),
                    source=fact.get("source"),
                )

        self._facts = facts
        self._entries = entries
        self._mtime = mtime
        self._warnings = warnings

    def fact(self, fact_id: str) -> FactText | None:
        self._load_if_changed()
        return self._facts.get(fact_id)

    def entry_name(self, entry_id: str) -> str | None:
        self._load_if_changed()
        return self._entries.get(entry_id)

    def describe(self, fact_ids: list[str]) -> list[dict[str, Any]]:
        """Attach text to ids. Ids with no dump entry still come back, marked."""
        self._load_if_changed()

        out: list[dict[str, Any]] = []
        for fact_id in fact_ids:
            known = self._facts.get(fact_id)
            if known is None:
                out.append({"id": fact_id, "text": None, "note": "not in ship log dump"})
                continue
            out.append({
                "id": fact_id,
                "entry": known.entry_name,
                "text": known.text,
                "rumor": known.rumor,
            })
        return out

    def group_by_entry(self, fact_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        """Facts collected under their entry name — how a player actually reads the log."""
        self._load_if_changed()

        grouped: dict[str, list[dict[str, Any]]] = {}
        for fact_id in fact_ids:
            known = self._facts.get(fact_id)
            name = known.entry_name if known else "unknown"
            grouped.setdefault(name, []).append({
                "id": fact_id,
                "text": known.text if known else None,
                "rumor": known.rumor if known else None,
            })
        return grouped
