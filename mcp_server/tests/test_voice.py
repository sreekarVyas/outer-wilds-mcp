"""Tests that internals never reach a player-facing payload.

These are the load-bearing tests for the spoiler-free promise. Instructions to an
assistant are advisory; what a tool actually returns is not.
"""

from __future__ import annotations

import json

import pytest

from gcp import voice


class TestStripInternals:
    def test_removes_save_file_shape(self):
        result = voice.strip_internals({
            "location": "the Village",
            "loop_count": 95,
            "facts_revealed": 239,
            "warped_to_the_eye": False,
        })
        assert result == {"location": "the Village"}

    def test_removes_resolver_workings(self):
        result = voice.strip_internals({
            "location": "the Village",
            "resolved_by": "sector:Sector_Village",
            "unresolved_sectors": ["Sector_X"],
            "body_key": "TimberHearth",
        })
        assert result == {"location": "the Village"}

    def test_removes_raw_measurements_but_keeps_phrasings(self):
        result = voice.strip_internals({
            "time_left": "about 20 minutes left",
            "ship_direction": "behind you, 4 m",
            "seconds_remaining": 1287,
            "ship_distance": 4.162,
            "lat": -13.7,
            "lon": 83.5,
        })
        assert result == {
            "time_left": "about 20 minutes left",
            "ship_direction": "behind you, 4 m",
        }

    def test_recurses_into_nested_dicts(self):
        result = voice.strip_internals({
            "player": {"state": "on foot", "lat": 12.0, "speed": 3.0},
        })
        assert result == {"player": {"state": "on foot"}}

    def test_recurses_into_lists_of_dicts(self):
        result = voice.strip_internals({
            "nearby": [
                {"name": "VILLAGE", "direction": "ahead", "distance": 49.0, "id": "TH_V"},
            ],
        })
        assert result == {"nearby": [{"name": "VILLAGE", "direction": "ahead"}]}

    def test_leaves_plain_content_alone(self):
        payload = {
            "planet": "Timber Hearth",
            "location": "the Village",
            "hazards": ["ghost matter"],
            "landmarks": ["Observatory"],
        }
        assert voice.strip_internals(payload) == payload

    def test_no_number_survives_a_realistic_payload(self):
        """The regression this whole module exists to prevent."""
        payload = voice.strip_internals({
            "planet": "Timber Hearth",
            "location": "the Village",
            "loop": {"count": 95, "seconds_remaining": 1287, "flowing": True},
            "progression": {"loop_count": 95, "facts_revealed": 239},
            "ship_distance": 4.16,
            "resolved_by": "sector:Sector_Village",
        })
        serialized = json.dumps(payload)
        for leak in ("95", "1287", "239", "4.16", "Sector_"):
            assert leak not in serialized, f"leaked {leak!r}: {serialized}"


class TestTimeLeft:
    @pytest.mark.parametrize("seconds,expected", [
        (None, None),
        (0, "no time left"),
        (-5, "no time left"),
        (30, "less than a minute left"),
        (90, "about a minute left"),
        (240, "only 4 minutes left"),
        (600, "about 10 minutes left"),
        (1000, "around 17 minutes left"),
        (1287, "the loop has just started"),
    ])
    def test_phrases(self, seconds, expected):
        assert voice.time_left(seconds) == expected

    def test_never_returns_a_bare_number(self):
        for seconds in range(0, 1300, 17):
            phrase = voice.time_left(seconds)
            assert not phrase.replace(".", "").isdigit()


class TestFreshness:
    def test_live_and_current(self):
        assert voice.freshness(1.0, live=True, running=True) == "current"

    def test_paused_says_where_you_were(self):
        text = voice.freshness(480, live=True, running=True)
        assert "paused" in text and "8 minutes" in text

    def test_one_minute_is_singular(self):
        assert "1 minute," in voice.freshness(60, live=True, running=True)

    def test_save_sourced_does_not_claim_the_game_is_closed(self):
        """Saved progress is save-sourced even while the game is running."""
        text = voice.freshness(None, live=False, running=True)
        assert "not running" not in text
        assert "saved progress" in text

    def test_closed_game_is_flagged_as_possibly_wrong(self):
        text = voice.freshness(9000, live=True, running=False)
        assert "closed" in text


class TestDistance:
    @pytest.mark.parametrize("metres,expected", [
        (None, None),
        (5, "right here"),
        (49, "a short walk"),
        (277, "a few minutes on foot"),
        (1500, "a long way — you will want your jetpack"),
        (22000, "far enough that you will need the ship"),
    ])
    def test_phrases(self, metres, expected):
        assert voice.distance(metres) == expected
