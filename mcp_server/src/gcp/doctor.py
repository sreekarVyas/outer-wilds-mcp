"""Reports every path the server resolved, how, and what to do when one is wrong.

A wrong path is the most likely failure on a fresh install, and its symptom is
misleading: the server says "game not running" when the truth is "I looked in the wrong
place". This names the actual problem.

One report function, two callers — the `gcp doctor` console script and an MCP tool — so
the assistant can diagnose itself with exactly what a human would see.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gcp import config


@dataclass
class Check:
    name: str
    path: Path | None
    source: str
    ok: bool
    detail: str | None = None
    fix: str | None = None
    age_seconds: float | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "name": self.name,
            "path": str(self.path) if self.path else None,
            "resolved_from": self.source,
            "ok": self.ok,
        }
        if self.detail:
            out["detail"] = self.detail
        if self.fix:
            out["fix"] = self.fix
        if self.age_seconds is not None:
            out["age_seconds"] = round(self.age_seconds, 1)
        return out


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "checks": [c.to_dict() for c in self.checks],
            "config_file": str(config.config_file_path()),
        }


def _age(path: Path) -> float | None:
    try:
        return time.time() - path.stat().st_mtime
    except OSError:
        return None


def run() -> Report:
    report = Report()

    # --- game install ----------------------------------------------------------
    game = config.find_game_dir()
    report.checks.append(Check(
        name="game install",
        path=game.value,
        source=game.source,
        ok=game.ok,
        detail=game.problem,
        fix=None if game.ok else (
            "Launch the game once so Unity writes Player.log, or set game_dir in the "
            f"config file at {config.config_file_path()}, or set GCP_GAME_DIR."
        ),
    ))

    # --- data directory --------------------------------------------------------
    data = config.data_dir()
    report.checks.append(Check(
        name="data directory",
        path=data.value,
        source=data.source,
        ok=data.exists,
        fix=None if data.exists else (
            "Created by the plugin on first run. Install the plugin into BepInEx/plugins "
            "and launch the game."
        ),
    ))

    # --- snapshot --------------------------------------------------------------
    snapshot = config.snapshot_path()
    age = _age(snapshot.value) if snapshot.value else None
    report.checks.append(Check(
        name="live snapshot",
        path=snapshot.value,
        source=snapshot.source,
        ok=snapshot.exists,
        age_seconds=age,
        detail=None if not snapshot.exists else _snapshot_detail(age),
        fix=None if snapshot.exists else (
            "Written by the plugin while the game runs. Check BepInEx/LogOutput.log for "
            "'GameContextProvider ... running'."
        ),
    ))

    # --- ship log dump ---------------------------------------------------------
    shiplog = config.shiplog_path()
    report.checks.append(Check(
        name="ship log text",
        path=shiplog.value,
        source=shiplog.source,
        ok=shiplog.exists,
        fix=None if shiplog.exists else (
            "Written once when a save is loaded. Start the game and load a save. Without "
            "it, fact ids have no readable text."
        ),
    ))

    # --- save file -------------------------------------------------------------
    report.checks.append(_check_save())

    # --- ontology --------------------------------------------------------------
    report.checks.append(_check_ontology())

    return report


def _snapshot_detail(age: float | None) -> str | None:
    if age is None:
        return None
    if age < 5:
        return "live"
    # The game pauses when unfocused, so an old snapshot is normal, not broken.
    return f"{age:.0f}s old — normal if the game is paused or unfocused"


def _check_save() -> Check:
    from gcp.adapters.outer_wilds.save_reader import find_profiles

    root = config.save_root()
    profiles = find_profiles(root.value) if root.value else []

    if not profiles:
        return Check(
            name="save file",
            path=root.value,
            source=root.source,
            ok=False,
            fix=(
                "No data.owsave found. Play the game at least once, or set save_path in "
                "the config file if your saves live elsewhere."
            ),
        )

    newest = profiles[0]
    return Check(
        name="save file",
        path=newest,
        source=f"{root.source} (profile '{newest.parent.name}', {len(profiles)} found)",
        ok=True,
        age_seconds=_age(newest),
        detail="written at loop end and on quit, so it is always somewhat behind",
    )


def _check_ontology() -> Check:
    from gcp.adapters.outer_wilds.resolver import ONTOLOGY_DIR

    locations = ONTOLOGY_DIR / "locations.json"
    ok = locations.is_file()
    return Check(
        name="ontology",
        path=ONTOLOGY_DIR,
        source="package data",
        ok=ok,
        fix=None if ok else (
            "locations.json missing from the installed package — reinstall with "
            "`pip install -e .` from mcp_server/."
        ),
    )


def format_text(report: Report) -> str:
    """Human-readable report for the console."""
    lines = ["Game Context Provider — diagnostics", ""]

    for check in report.checks:
        mark = "OK  " if check.ok else "FAIL"
        lines.append(f"[{mark}] {check.name}")
        lines.append(f"        path:  {check.path or '<unresolved>'}")
        lines.append(f"        from:  {check.source}")
        if check.detail:
            lines.append(f"        note:  {check.detail}")
        if check.fix:
            lines.append(f"        fix:   {check.fix}")
        lines.append("")

    lines.append(f"config file: {config.config_file_path()}")
    lines.append("")
    lines.append("All checks passed." if report.ok else "Some checks failed. See 'fix' lines above.")
    return "\n".join(lines)


def main() -> int:
    report = run()
    print(format_text(report))
    return 0 if report.ok else 1
