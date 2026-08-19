"""Tests for the disclosure contract.

The design separates two things that are easy to conflate:

  knowledge  — the assistant sees the whole world, so it can tell a real lead from an
               empty direction. Not filtered.
  vocabulary — player-facing payloads never carry counts, ids, flags or raw numbers.
               Enforced in the data, not requested of the assistant.

What makes the first safe is labelling: every place carries `discovered`, and unfound
notes arrive under their own key. These tests pin that labelling, because losing it
would turn full knowledge into a spoiler machine.
"""

from __future__ import annotations

import json

import pytest

from gcp.adapters.outer_wilds.adapter import OuterWildsAdapter


class FakeText:
    """Stands in for the ship log dump."""

    available = True
    warnings: list[str] = []

    def __init__(self, entry_of: dict[str, str]) -> None:
        self._entry_of = entry_of

    def fact(self, fact_id):
        entry = self._entry_of.get(fact_id)
        if entry is None:
            return None
        return type("F", (), {"entry_id": entry, "entry_name": entry, "text": "...",
                              "rumor": False})()

    def group_by_entry(self, fact_ids):
        grouped: dict[str, list] = {}
        for fid in fact_ids:
            grouped.setdefault(self._entry_of.get(fid, "unknown"), []).append({"id": fid})
        return grouped


class FakeSave:
    age_seconds = 10.0
    loop_count = 5

    def __init__(self, all_facts, revealed):
        self.facts = {f: None for f in all_facts}
        self.revealed_facts = list(revealed)

    def summary(self):
        return {"loop_count": self.loop_count}


@pytest.fixture
def adapter(monkeypatch):
    a = OuterWildsAdapter()
    a.text = FakeText({"A1": "KNOWN PLACE", "B1": "UNKNOWN PLACE"})
    monkeypatch.setattr(a.saves, "get", lambda: FakeSave(["A1", "B1"], ["A1"]))
    return a


SNAPSHOT = {
    "schema": 1, "t": 9e9, "in_game": True, "scene": "SolarSystem",
    "body": "TimberHearth", "sectors": ["TimberHearth"],
    "player": {"grounded": True, "suited": True},
    "hazards": [], "loop": {"count": 5, "remaining": 600.0, "flowing": True},
    "ship": {"distance": 10.0, "bearing": 0.0, "elevation": 0.0},
    "nearby_entries": [
        {"id": "KNOWN PLACE", "name": "KNOWN PLACE", "distance": 40.0,
         "bearing": 0.0, "elevation": 0.0},
        {"id": "UNKNOWN PLACE", "name": "UNKNOWN PLACE", "distance": 80.0,
         "bearing": 90.0, "elevation": 0.0},
    ],
}


@pytest.fixture
def context(adapter, monkeypatch):
    monkeypatch.setattr(adapter.snapshots, "read", lambda: (SNAPSHOT, []))
    monkeypatch.setattr("gcp.adapters.outer_wilds.adapter.game_is_running", lambda: True)
    return adapter.get_current_context().data


class TestKnowledgeIsNotWithheld:
    def test_undiscovered_places_are_still_reported(self, context):
        """The assistant needs them to aim a nudge; hiding them makes it guess."""
        names = {m["name"] for m in context["nearby"]}
        assert names == {"KNOWN PLACE", "UNKNOWN PLACE"}

    def test_every_place_says_whether_it_is_safe_to_name(self, context):
        by_name = {m["name"]: m["discovered"] for m in context["nearby"]}
        assert by_name["KNOWN PLACE"] is True
        assert by_name["UNKNOWN PLACE"] is False

    def test_ship_log_returns_both_halves_separately(self, adapter):
        data = adapter.get_player_known_context().data
        assert "KNOWN PLACE" in data["found"]
        assert "UNKNOWN PLACE" in data["not_yet_found"]
        assert "UNKNOWN PLACE" not in data["found"]

    def test_ship_log_explains_how_to_treat_each_half(self, adapter):
        assert "Never name" in adapter.get_player_known_context().data["how_to_use"]


class TestVocabularyIsEnforced:
    def test_no_internals_in_context(self, context):
        for banned in ("loop", "resolved_by", "sectors", "ship_distance",
                       "seconds_remaining", "progression"):
            assert banned not in context, f"{banned} leaked"

    def test_time_is_phrased_not_counted(self, context):
        assert context["time_left"] == "about 10 minutes left"

    def test_no_raw_numbers_survive_serialization(self, context):
        serialized = json.dumps(context)
        for leak in ("600", "1287", "TimberHearth", "Sector_"):
            assert leak not in serialized, f"leaked {leak!r}"

    def test_internals_are_available_when_asked_for(self, adapter, monkeypatch):
        monkeypatch.setattr(adapter.snapshots, "read", lambda: (SNAPSHOT, []))
        monkeypatch.setattr("gcp.adapters.outer_wilds.adapter.game_is_running", lambda: True)
        data = adapter.get_current_context(include_internals=True).data
        assert "resolved_by" in data

    def test_progression_reports_no_number(self, adapter):
        data = adapter.get_progression().data
        assert "loop_count" not in data
        assert not any(isinstance(v, (int, float)) for v in data.values())
