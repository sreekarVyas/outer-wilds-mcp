"""Smoke test: exercise every adapter method and print the result.

Run with the game closed to check the save-file path, and again with the game
running and the plugin loaded to check the live path.

    python tools/smoke.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gcp.adapters.outer_wilds.adapter import OuterWildsAdapter  # noqa: E402


def show(title: str, result) -> None:
    print(f"\n===== {title} =====")
    print(json.dumps(result.to_dict(), indent=2)[:1200])


def main() -> None:
    adapter = OuterWildsAdapter()
    show("connection status", adapter.get_connection_status())
    show("progression", adapter.get_progression())
    show("runtime state", adapter.get_runtime_state())
    show("location", adapter.get_location())
    show("current context", adapter.get_current_context())


if __name__ == "__main__":
    main()
