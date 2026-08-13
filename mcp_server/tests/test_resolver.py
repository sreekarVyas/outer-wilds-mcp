"""Tests for semantic resolution."""

from __future__ import annotations

import json

import pytest

from gcp.adapters.outer_wilds.resolver import Resolver


@pytest.fixture
def ontology(tmp_path):
    (tmp_path / "locations.json").write_text(json.dumps({
        "Sector_StartingCamp": {"name": "the starting campfire", "sub_location": "Lower Village"},
        "TimberHearth": {"name": "Timber Hearth"},
    }), encoding="utf-8")

    (tmp_path / "bodies.json").write_text(json.dumps({
        "TimberHearth": {"name": "Timber Hearth"},
        "BrittleHollow": {
            "name": "Brittle Hollow",
            "regions": [
                {"name": "north pole region", "lat": [55, 90]},
                {"name": "the antimeridian strip", "lon": [170, -170]},
            ],
        },
    }), encoding="utf-8")

    return tmp_path


def snapshot(**kwargs):
    base = {"body": "TimberHearth", "sectors": [], "hazards": [], "player": {}}
    base.update(kwargs)
    return base


def test_innermost_sector_wins(ontology):
    result = Resolver(ontology).resolve(
        snapshot(sectors=["TimberHearth", "Sector_Village", "Sector_StartingCamp"])
    )
    assert result["location"] == "the starting campfire"
    assert result["resolved_by"] == "sector:Sector_StartingCamp"


def test_falls_outward_when_inner_sector_is_unknown(ontology):
    result = Resolver(ontology).resolve(snapshot(sectors=["TimberHearth", "Sector_Unmapped"]))
    assert result["location"] == "Timber Hearth"
    assert result["resolved_by"] == "sector:TimberHearth"


def test_ship_log_marker_beats_geometry(ontology):
    result = Resolver(ontology).resolve(snapshot(
        body="BrittleHollow",
        player={"lat": 70.0, "lon": 0.0, "radial": 300.0},
        nearby_entries=[
            {"id": "BH_OLD_SETTLEMENT", "name": "Old Settlement", "distance": 40.0},
            {"id": "BH_GRAVITY_CANNON", "name": "Gravity Cannon", "distance": 90.0},
        ],
    ))
    assert result["location"] == "Old Settlement"
    assert result["resolved_by"] == "ship_log_entry:BH_OLD_SETTLEMENT"
    assert result["landmarks"] == ["Gravity Cannon"]


def test_distant_marker_is_ignored(ontology):
    result = Resolver(ontology).resolve(snapshot(
        body="BrittleHollow",
        player={"lat": 70.0, "lon": 0.0, "radial": 300.0},
        nearby_entries=[{"id": "FAR", "name": "Somewhere Else", "distance": 900.0}],
    ))
    assert result["location"] == "north pole region"
    assert result["resolved_by"] == "region"


def test_longitude_band_wraps_the_antimeridian(ontology):
    resolver = Resolver(ontology)
    for lon in (175.0, -175.0):
        result = resolver.resolve(snapshot(
            body="BrittleHollow", player={"lat": 0.0, "lon": lon, "radial": 300.0}
        ))
        assert result["location"] == "the antimeridian strip", f"failed at lon={lon}"


def test_unresolved_reports_what_is_needed_to_fix_it(ontology):
    result = Resolver(ontology).resolve(snapshot(
        body="BrittleHollow",
        sectors=["Sector_Mystery"],
        player={"lat": 0.0, "lon": 0.0, "radial": 300.0},
    ))
    assert result["resolved_by"] == "unresolved"
    assert result["unresolved_sectors"] == ["Sector_Mystery"]
    assert result["hint"]["lat"] == 0.0


def test_container_sector_does_not_hide_the_place(ontology):
    """Being in the ship is a state, not a place. It must not win the location slot."""
    (ontology / "locations.json").write_text(json.dumps({
        "Ship": {"name": "your ship", "container": True, "landmarks": ["flight console"]},
        "TimberHearth": {"name": "Timber Hearth"},
    }), encoding="utf-8")

    result = Resolver(ontology).resolve(snapshot(
        sectors=["TimberHearth", "Sector_Village", "Ship"],
        nearby_entries=[{"id": "TH_VILLAGE", "name": "VILLAGE", "distance": 42.5}],
    ))

    assert result["location"] == "VILLAGE"
    assert result["inside"] == "your ship"
    assert result["resolved_by"] == "ship_log_entry:TH_VILLAGE"


def test_container_survives_an_unresolved_place(ontology):
    """With only the ship known, still report the body and note the ship."""
    (ontology / "locations.json").write_text(json.dumps({
        "Ship": {"name": "your ship", "container": True},
    }), encoding="utf-8")

    result = Resolver(ontology).resolve(snapshot(sectors=["Ship"]))
    assert result["location"] == "Timber Hearth"
    assert result["inside"] == "your ship"
    assert result["resolved_by"] == "unresolved"


def test_broad_sector_loses_to_a_near_marker(ontology):
    """The planet is true but imprecise; a marker 40 m away is better."""
    result = Resolver(ontology).resolve(snapshot(
        sectors=["TimberHearth"],
        nearby_entries=[{"id": "TH_VILLAGE", "name": "VILLAGE", "distance": 42.5}],
    ))
    assert result["location"] == "VILLAGE"


def test_broad_sector_wins_when_no_marker_is_near(ontology):
    result = Resolver(ontology).resolve(snapshot(
        sectors=["TimberHearth"],
        nearby_entries=[{"id": "FAR", "name": "Somewhere", "distance": 800.0}],
    ))
    assert result["location"] == "Timber Hearth"
    assert result["resolved_by"] == "sector:TimberHearth"


def test_hazards_from_state_and_ontology_are_merged(ontology):
    (ontology / "locations.json").write_text(json.dumps({
        "Sector_Cave": {"name": "a cave", "hazards": ["darkness"]}
    }), encoding="utf-8")

    result = Resolver(ontology).resolve(
        snapshot(sectors=["Sector_Cave"], hazards=["darkmatter"])
    )
    assert set(result["hazards"]) == {"darkness", "darkmatter"}


def test_ontology_hot_reloads(ontology):
    resolver = Resolver(ontology)
    assert resolver.resolve(snapshot(sectors=["Sector_New"]))["resolved_by"] == "unresolved"

    path = ontology / "locations.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["Sector_New"] = {"name": "a newly named place"}
    path.write_text(json.dumps(data), encoding="utf-8")
    # Force a differing mtime on filesystems with coarse timestamps.
    import os, time
    os.utime(path, (time.time() + 1, time.time() + 1))

    assert resolver.resolve(snapshot(sectors=["Sector_New"]))["location"] == "a newly named place"
