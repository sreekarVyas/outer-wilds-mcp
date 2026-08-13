"""Tests for turning bearing and elevation into words."""

from __future__ import annotations

import pytest

from gcp.adapters.outer_wilds import direction


@pytest.mark.parametrize("bearing,expected", [
    (0.0, "straight ahead"),
    (10.0, "straight ahead"),
    (-10.0, "straight ahead"),
    (45.0, "ahead and to your right"),
    (-45.0, "ahead and to your left"),
    (90.0, "to your right"),
    (-90.0, "to your left"),
    (140.0, "behind you and to your right"),
    (-140.0, "behind you and to your left"),
    (180.0, "directly behind you"),
    (-180.0, "directly behind you"),
])
def test_bearing_phrases(bearing, expected):
    assert direction._bearing_phrase(bearing) == expected


@pytest.mark.parametrize("elevation,expected", [
    (0.0, ""),
    (10.0, ""),
    (-10.0, ""),        # near the horizon, saying nothing is better than false precision
    (30.0, "above you"),
    (-30.0, "below you"),
    (70.0, "above, steeply"),
    (-70.0, "below, steeply"),
])
def test_elevation_phrases(elevation, expected):
    assert direction._elevation_phrase(elevation) == expected


def test_full_phrase():
    assert direction.describe(45.0, -30.0, 61.0) == "ahead and to your right, below you, 61 m"


def test_horizon_level_target_omits_vertical():
    assert direction.describe(0.0, 2.0, 12.0) == "straight ahead, 12 m"


def test_long_distances_use_kilometres():
    assert direction.describe(0.0, 0.0, 22014.0) == "straight ahead, 22.0 km"


def test_unknown_bearing_gives_no_phrase():
    """Looking straight up leaves no horizontal component, so bearing is null."""
    assert direction.describe(None, 45.0, 100.0) is None


def test_missing_elevation_is_tolerated():
    assert direction.describe(90.0, None, 50.0) == "to your right, 50 m"


def test_annotate_preserves_raw_angles():
    marker = {"id": "BH_FORGE", "name": "BLACK HOLE FORGE",
              "distance": 61.0, "bearing": 45.0, "elevation": -30.0}
    result = direction.annotate(marker)

    assert result["direction"] == "ahead and to your right, below you, 61 m"
    assert result["bearing"] == 45.0      # raw values survive for any other consumer
    assert result["elevation"] == -30.0
    assert marker.get("direction") is None  # input is not mutated


def test_annotate_without_direction_data_is_a_no_op():
    marker = {"name": "X", "distance": 10.0}
    assert direction.annotate(marker) == marker


def test_annotate_handles_empty():
    assert direction.annotate(None) is None
    assert direction.annotate({}) == {}
