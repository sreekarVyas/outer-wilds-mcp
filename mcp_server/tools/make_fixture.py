"""Generates the synthetic save fixture used by the tests.

The tests originally ran against a real `data.owsave`, which meant publishing the
author's playthrough. This builds a structurally identical file with invented
content, so the suite stays honest without exposing anyone's progress.

It reproduces the shapes that actually trip the parser:

  * facts with `revealOrder: -1` **and** `read: true` — undiscovered but touched,
    the case that makes `read` useless as a reveal signal
  * facts revealed out of order, as the game writes them
  * conditions that are present but false
  * a signal dictionary keyed by strings, not ints

Run:  python tools/make_fixture.py
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "sample.owsave"

# (id, revealOrder, read)
FACTS: list[tuple[str, int, bool]] = [
    # A fully explored place.
    ("TEST_ALPHA_R1", 0, True),
    ("TEST_ALPHA_R2", 4, True),
    ("TEST_ALPHA_X1", 7, True),
    # Partly explored.
    ("TEST_BETA_R1", 2, True),
    ("TEST_BETA_X1", 9, False),
    ("TEST_BETA_X2", -1, False),
    ("TEST_BETA_X3", -1, False),
    # The trap: touched but never revealed.
    ("TEST_GAMMA_R1", -1, True),
    ("TEST_GAMMA_X1", -1, True),
    ("TEST_GAMMA_X2", -1, False),
    # Never approached.
    ("TEST_DELTA_R1", -1, False),
    ("TEST_DELTA_X1", -1, False),
]

SAVE = {
    "loopCount": 12,
    "knownFrequencies": [True, True, True, False, False, False, False],
    "knownSignals": {"11": True, "20": True, "23": False, "40": False},
    "dictConditions": {
        "LAUNCH_CODES_GIVEN": True,
        "MET_RIEBECK": True,
        "HAS_USED_TRANSLATOR": True,
        "TEST_CONDITION_FALSE": False,
    },
    "shipLogFactSaves": {
        fid: {"id": fid, "revealOrder": order, "read": read, "newlyRevealed": False}
        for fid, order, read in FACTS
    },
    "newlyRevealedFactIDs": [],
    "lastDeathType": 4,
    "burnedMarshmallowEaten": 1,
    "fullTimeloops": 3,
    "perfectMarshmallowsEaten": 0,
    "warpedToTheEye": False,
    "secondsRemainingOnWarp": 0.0,
    "loopCountOnParadox": 0,
    "shownPopups": 6,
    "version": "1.1.10.47",
}


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(SAVE, indent=2), encoding="utf-8")

    revealed = sum(1 for _, order, _ in FACTS if order > -1)
    print(f"wrote {OUT}")
    print(f"  {len(FACTS)} facts, {revealed} revealed, loop {SAVE['loopCount']}")


if __name__ == "__main__":
    main()
