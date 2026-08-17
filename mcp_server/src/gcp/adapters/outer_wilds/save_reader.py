"""Reads Outer Wilds save data.

The save is plaintext JSON — no decryption, no mod, no running game required.
It carries knowledge (ship log, conditions, signals) but never live position,
because it is only flushed at loop boundaries and on quit.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gcp import config


@dataclass
class Fact:
    id: str
    reveal_order: int
    read: bool

    @property
    def revealed(self) -> bool:
        # Matches ShipLogFact.IsRevealed(), which is `_save.revealOrder > -1`.
        # The save pre-seeds undiscovered facts at -1, some with read == true, so
        # `read` alone is not a reveal signal.
        return self.reveal_order > -1


@dataclass
class KnowledgeState:
    loop_count: int = 0
    full_timeloops: int = 0
    facts: dict[str, Fact] = field(default_factory=dict)
    conditions: dict[str, bool] = field(default_factory=dict)
    known_signals: dict[str, bool] = field(default_factory=dict)
    known_frequencies: list[bool] = field(default_factory=list)
    last_death_type: int | None = None
    warped_to_the_eye: bool = False
    save_version: str | None = None

    profile: str | None = None
    mtime: float = 0.0

    @property
    def age_seconds(self) -> float:
        return time.time() - self.mtime

    @property
    def revealed_facts(self) -> list[str]:
        return [f.id for f in self.facts.values() if f.revealed]

    def summary(self) -> dict[str, Any]:
        revealed = self.revealed_facts
        return {
            "profile": self.profile,
            "loop_count": self.loop_count,
            "full_timeloops": self.full_timeloops,
            "facts_revealed": len(revealed),
            "facts_total_tracked": len(self.facts),
            "conditions": {k: v for k, v in self.conditions.items() if v},
            "known_frequencies": sum(1 for f in self.known_frequencies if f),
            "warped_to_the_eye": self.warped_to_the_eye,
            "save_version": self.save_version,
        }


def find_profiles(root: Path | None = None) -> list[Path]:
    """All save directories, newest first. Covers Steam, Epic, and any other store layout."""
    if root is None:
        root = config.save_root().value
    if root is None or not root.exists():
        return []
    saves = [p for p in root.glob("*Saves/*/data.owsave") if p.is_file()]
    return sorted(saves, key=lambda p: p.stat().st_mtime, reverse=True)


def load(path: Path | None = None) -> KnowledgeState | None:
    """Load the most recently written profile, or a specific save if given."""
    if path is None:
        profiles = find_profiles()
        if not profiles:
            return None
        path = profiles[0]

    raw = json.loads(path.read_text(encoding="utf-8"))

    facts = {
        fid: Fact(id=fid, reveal_order=v.get("revealOrder", -1), read=v.get("read", False))
        for fid, v in raw.get("shipLogFactSaves", {}).items()
    }

    return KnowledgeState(
        loop_count=raw.get("loopCount", 0),
        full_timeloops=raw.get("fullTimeloops", 0),
        facts=facts,
        conditions=raw.get("dictConditions", {}),
        known_signals=raw.get("knownSignals", {}),
        known_frequencies=raw.get("knownFrequencies", []),
        last_death_type=raw.get("lastDeathType"),
        warped_to_the_eye=raw.get("warpedToTheEye", False),
        save_version=raw.get("version"),
        profile=path.parent.name,
        mtime=path.stat().st_mtime,
    )


class SaveReader:
    """Caches the parse and re-reads only when the file changes on disk."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        self._cached: KnowledgeState | None = None
        self._cached_mtime: float = -1.0

    def get(self) -> KnowledgeState | None:
        path = self._path
        if path is None:
            profiles = find_profiles()
            if not profiles:
                return None
            path = profiles[0]

        try:
            mtime = path.stat().st_mtime
        except OSError:
            # Deleted, renamed, or never there. Keep any cached copy rather than
            # throwing: stale knowledge beats no knowledge, and the caller labels it.
            return self._cached

        if self._cached is not None and mtime == self._cached_mtime:
            return self._cached

        try:
            self._cached = load(path)
            self._cached_mtime = mtime
        except (OSError, json.JSONDecodeError):
            # A save being written mid-read, or a corrupt file. Keep the last good parse.
            pass

        return self._cached
