"""Tests for turning fact ids back into readable text."""

from __future__ import annotations

import json

import pytest

from gcp.adapters.outer_wilds.shiplog_text import ShipLogText

DUMP = {
    "schema": 1,
    "generated": "2026-08-14T00:00:00Z",
    "entry_count": 2,
    "fact_count": 3,
    "entries": [
        {
            "id": "TEST_CITY",
            "name": "TEST CITY",
            "astro_object": "TEST_BODY",
            "parent": None,
            "curiosity": "None",
            "facts": [
                {"id": "TEST_CITY_R1", "text": "You heard a city exists.",
                 "rumor": True, "source": "TEST_CAMP"},
                {"id": "TEST_CITY_X1", "text": "The city is empty.",
                 "rumor": False, "source": None},
            ],
        },
        {
            "id": "TEST_CAMP",
            "name": "TEST CAMP",
            "astro_object": "TEST_BODY",
            "parent": None,
            "curiosity": "None",
            "facts": [
                {"id": "TEST_CAMP_X1", "text": "  Someone camped here.  ",
                 "rumor": False, "source": None},
            ],
        },
    ],
}


@pytest.fixture
def dump(tmp_path):
    path = tmp_path / "gcp-shiplog.json"
    path.write_text(json.dumps(DUMP), encoding="utf-8")
    return path


def test_available_when_dump_exists(dump):
    assert ShipLogText(dump).available is True


def test_unavailable_and_explains_why_when_missing(tmp_path):
    log = ShipLogText(tmp_path / "absent.json")
    assert log.available is False
    assert "no ship log dump" in log.warnings[0]


def test_fact_lookup(dump):
    fact = ShipLogText(dump).fact("TEST_CITY_R1")
    assert fact.text == "You heard a city exists."
    assert fact.rumor is True
    assert fact.entry_name == "TEST CITY"
    assert fact.source == "TEST_CAMP"


def test_text_is_stripped(dump):
    assert ShipLogText(dump).fact("TEST_CAMP_X1").text == "Someone camped here."


def test_unknown_fact_is_none(dump):
    assert ShipLogText(dump).fact("NOT_A_FACT") is None


def test_describe_marks_ids_it_cannot_resolve(dump):
    result = ShipLogText(dump).describe(["TEST_CITY_X1", "MYSTERY_X9"])
    assert result[0]["text"] == "The city is empty."
    assert result[1]["text"] is None
    assert result[1]["note"] == "not in ship log dump"


def test_group_by_entry(dump):
    grouped = ShipLogText(dump).group_by_entry(["TEST_CITY_R1", "TEST_CITY_X1", "TEST_CAMP_X1"])
    assert set(grouped) == {"TEST CITY", "TEST CAMP"}
    assert len(grouped["TEST CITY"]) == 2
    assert grouped["TEST CAMP"][0]["text"] == "Someone camped here."


def test_schema_mismatch_warns_but_still_loads(tmp_path):
    path = tmp_path / "gcp-shiplog.json"
    path.write_text(json.dumps({**DUMP, "schema": 99}), encoding="utf-8")

    log = ShipLogText(path)
    assert log.available is True
    assert "schema 99" in log.warnings[0]


def test_corrupt_dump_warns_rather_than_raising(tmp_path):
    path = tmp_path / "gcp-shiplog.json"
    path.write_text("{ not json", encoding="utf-8")

    log = ShipLogText(path)
    assert log.available is False
    assert "unreadable" in log.warnings[0]


def test_reloads_when_the_dump_changes(dump):
    import os
    import time

    log = ShipLogText(dump)
    assert log.fact("TEST_CITY_X1").text == "The city is empty."

    changed = json.loads(dump.read_text(encoding="utf-8"))
    changed["entries"][0]["facts"][1]["text"] = "The city is not empty after all."
    dump.write_text(json.dumps(changed), encoding="utf-8")
    os.utime(dump, (time.time() + 1, time.time() + 1))

    assert log.fact("TEST_CITY_X1").text == "The city is not empty after all."
