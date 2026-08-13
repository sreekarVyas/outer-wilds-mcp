"""Tests for the save reader.

The fixture is synthetic — see tools/make_fixture.py. It reproduces the shapes that
actually trip the parser, including facts that are read but never revealed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gcp.adapters.outer_wilds.save_reader import Fact, SaveReader, load

FIXTURE = Path(__file__).parent / "fixtures" / "sample.owsave"


@pytest.fixture
def state():
    return load(FIXTURE)


def test_parses_known_values(state):
    assert state.loop_count == 12
    assert state.full_timeloops == 3
    assert state.save_version == "1.1.10.47"
    assert len(state.facts) == 12


def test_conditions_are_read(state):
    assert state.conditions["LAUNCH_CODES_GIVEN"] is True
    assert state.conditions["MET_RIEBECK"] is True
    assert state.conditions["TEST_CONDITION_FALSE"] is False


def test_signals_and_frequencies_are_read(state):
    assert state.known_signals["11"] is True
    assert state.known_signals["40"] is False
    assert sum(1 for f in state.known_frequencies if f) == 3


def test_read_but_unrevealed_facts_are_not_counted(state):
    """The trap: TEST_GAMMA_* are read == true with revealOrder == -1."""
    revealed = set(state.revealed_facts)
    assert "TEST_GAMMA_R1" not in revealed
    assert "TEST_GAMMA_X1" not in revealed
    assert state.facts["TEST_GAMMA_R1"].read is True


def test_revealed_count_is_exact(state):
    assert len(state.revealed_facts) == 5
    assert state.summary()["facts_revealed"] == 5


def test_reveal_semantics_match_the_game():
    """ShipLogFact.IsRevealed() is `_save.revealOrder > -1`. Nothing else counts."""
    assert Fact("X", reveal_order=0, read=False).revealed is True
    assert Fact("X", reveal_order=83, read=True).revealed is True
    assert Fact("X", reveal_order=-1, read=False).revealed is False

    # The trap: the save carries entries that are read but never revealed.
    assert Fact("X", reveal_order=-1, read=True).revealed is False


def test_revealed_is_a_strict_subset(state):
    revealed = set(state.revealed_facts)
    assert 0 < len(revealed) < len(state.facts)


def test_summary_is_json_serializable(state):
    json.dumps(state.summary())


def test_missing_save_returns_none_and_does_not_raise(tmp_path):
    assert SaveReader(tmp_path / "absent.owsave").get() is None


def test_corrupt_save_keeps_the_last_good_parse(tmp_path):
    path = tmp_path / "data.owsave"
    path.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

    reader = SaveReader(path)
    assert reader.get().loop_count == 12

    # Simulate the game writing the file while we read it.
    path.write_text("{ this is not json", encoding="utf-8")
    assert reader.get().loop_count == 12


def test_reader_caches_until_mtime_changes():
    reader = SaveReader(FIXTURE)
    assert reader.get() is reader.get()
