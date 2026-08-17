"""Reads the live snapshot file written by the in-game plugin."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from gcp import config

# Past this, the game is closed, paused, or the plugin died. The snapshot is written
# at 10 Hz, so anything older than a couple of seconds means something stopped.
STALE_AFTER_SECONDS = 3.0

SUPPORTED_SCHEMA = 1


class SnapshotSource:
    def __init__(self, path: Path | None = None) -> None:
        self.resolved = config.snapshot_path(path)
        self.path = self.resolved.value

    # The writer replaces the file atomically, but Windows can still deny a read that
    # lands exactly on the replace. Retrying beats reporting the game as closed.
    READ_ATTEMPTS = 3
    RETRY_DELAY_SECONDS = 0.05

    def read(self) -> tuple[dict[str, Any] | None, list[str]]:
        """Return (snapshot, warnings). Snapshot is None when the plugin is not running."""
        warnings: list[str] = []
        last_error: Exception | None = None

        for attempt in range(self.READ_ATTEMPTS):
            if not self.path.exists():
                return None, [
                    f"no snapshot at {self.path} (from {self.resolved.source}) — "
                    "is the game running with the plugin? Run `gcp doctor` for details."
                ]

            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                break
            except (OSError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt < self.READ_ATTEMPTS - 1:
                    time.sleep(self.RETRY_DELAY_SECONDS)
        else:
            return None, [f"snapshot unreadable after {self.READ_ATTEMPTS} attempts: {last_error}"]

        schema = data.get("schema")
        if schema != SUPPORTED_SCHEMA:
            warnings.append(
                f"snapshot schema {schema}, expected {SUPPORTED_SCHEMA} — "
                "the plugin and the server are different versions; rebuild the plugin"
            )

        # A snapshot with no sectors while in game means the reflection broke. Say so
        # rather than letting it look like an unnamed place.
        if data.get("in_game") and not data.get("sectors"):
            warnings.append("in game but no sectors reported — check BepInEx log for SELF-CHECK FAILED")

        return data, warnings

    @staticmethod
    def age(snapshot: dict[str, Any]) -> float:
        return time.time() - snapshot.get("t", 0)

    @classmethod
    def is_stale(cls, snapshot: dict[str, Any]) -> bool:
        return cls.age(snapshot) > STALE_AFTER_SECONDS
