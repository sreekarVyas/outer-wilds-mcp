"""Tests for path resolution and game detection.

These matter more than most: a wrong path is the likeliest failure on a fresh install,
and its symptom ("game not running") points at the wrong problem entirely.
"""

from __future__ import annotations

import json

import pytest

from gcp import config


def make_game_dir(root, name="Outer Wilds"):
    """A directory that passes the Assembly-CSharp.dll marker check."""
    game = root / name
    managed = game / "OuterWilds_Data" / "Managed"
    managed.mkdir(parents=True)
    (managed / "Assembly-CSharp.dll").write_text("stub", encoding="utf-8")
    return game


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    """Isolate from this machine: no env vars, no real config file, no real Player.log."""
    for var in ("GCP_GAME_DIR", "GCP_DATA_DIR", "GCP_SNAPSHOT_PATH",
                "GCP_SHIPLOG_PATH", "GCP_SECTORS_PATH", "GCP_SAVE_PATH"):
        monkeypatch.delenv(var, raising=False)

    monkeypatch.setattr(config, "config_file_path", lambda: tmp_path / "nonexistent.toml")
    monkeypatch.setattr(config.Path, "home", staticmethod(lambda: tmp_path / "home"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    # Detectors that reach outside the sandbox are disabled unless a test opts in.
    monkeypatch.setattr(config, "_from_running_process", lambda: None)
    monkeypatch.setattr(config, "_from_steam", lambda: None)
    monkeypatch.setattr(config, "_from_epic", lambda: None)
    monkeypatch.setattr(config, "_from_gog", lambda: None)


# --------------------------------------------------------------------- game marker


def test_directory_without_assembly_is_rejected(tmp_path):
    (tmp_path / "Fake Game").mkdir()
    assert config._is_game_dir(tmp_path / "Fake Game") is False


def test_directory_with_assembly_is_accepted(tmp_path):
    assert config._is_game_dir(make_game_dir(tmp_path)) is True


# ----------------------------------------------------------------------- Player.log


def write_player_log(tmp_path, game_dir, name="Player.log"):
    log_dir = tmp_path / "home" / config.UNITY_LOG_DIR
    log_dir.mkdir(parents=True, exist_ok=True)
    managed = (game_dir / "OuterWilds_Data" / "Managed").as_posix()
    (log_dir / name).write_text(
        f"Mono path[0] = '{managed}'\nMono config path = '...'\n", encoding="utf-8")


def test_finds_game_from_player_log(tmp_path):
    """The case that makes non-store installs work: no registry, no manifest."""
    game = make_game_dir(tmp_path)
    write_player_log(tmp_path, game)

    result = config.find_game_dir()
    assert result.value == game
    assert result.source == "Player.log"
    assert result.ok


def test_falls_back_to_prev_log(tmp_path):
    game = make_game_dir(tmp_path)
    write_player_log(tmp_path, game, name="Player-prev.log")

    result = config.find_game_dir()
    assert result.value == game
    assert result.source == "Player-prev.log"


def test_player_log_pointing_at_a_moved_install_is_rejected(tmp_path):
    """The game was uninstalled or moved since it last ran."""
    ghost = tmp_path / "Gone"
    (ghost / "OuterWilds_Data" / "Managed").mkdir(parents=True)  # no Assembly-CSharp.dll
    write_player_log(tmp_path, ghost)

    assert config.find_game_dir().value is None


def test_no_sources_reports_what_was_tried(tmp_path):
    result = config.find_game_dir()
    assert result.value is None
    assert result.source == "not found"
    assert "Player.log" in result.problem
    assert "Steam" in result.problem


# ----------------------------------------------------------------------- precedence


def test_explicit_beats_everything(tmp_path, monkeypatch):
    detected = make_game_dir(tmp_path, "Detected")
    write_player_log(tmp_path, detected)
    chosen = make_game_dir(tmp_path, "Chosen")
    monkeypatch.setenv("GCP_GAME_DIR", str(make_game_dir(tmp_path, "FromEnv")))

    result = config.find_game_dir(chosen)
    assert result.value == chosen
    assert result.source == "explicit argument"


def test_env_beats_autodetect(tmp_path, monkeypatch):
    write_player_log(tmp_path, make_game_dir(tmp_path, "Detected"))
    from_env = make_game_dir(tmp_path, "FromEnv")
    monkeypatch.setenv("GCP_GAME_DIR", str(from_env))

    assert config.find_game_dir().value == from_env


def test_config_file_beats_autodetect(tmp_path, monkeypatch):
    write_player_log(tmp_path, make_game_dir(tmp_path, "Detected"))
    from_file = make_game_dir(tmp_path, "FromFile")

    toml = tmp_path / "config.toml"
    toml.write_text(f'game_dir = "{from_file.as_posix()}"\n', encoding="utf-8")
    monkeypatch.setattr(config, "config_file_path", lambda: toml)

    result = config.find_game_dir()
    assert result.value == from_file
    assert result.source == "config file"


def test_a_wrong_explicit_path_is_reported_not_silently_replaced(tmp_path):
    """Falling through to auto-detection would hide the user's mistake."""
    write_player_log(tmp_path, make_game_dir(tmp_path, "Detected"))
    wrong = tmp_path / "not-the-game"
    wrong.mkdir()

    result = config.find_game_dir(wrong)
    assert result.value == wrong
    assert result.ok is False
    assert "Assembly-CSharp.dll" in result.problem


# ------------------------------------------------------------------------ data dirs


def test_data_dir_defaults_under_local_app_data(tmp_path):
    result = config.data_dir()
    assert result.value == tmp_path / "localappdata" / "GameContextProvider" / "outer-wilds"
    assert result.source == "OS default"


def test_data_files_sit_in_the_data_dir(tmp_path):
    base = config.data_dir().value
    assert config.snapshot_path().value == base / "snapshot.json"
    assert config.shiplog_path().value == base / "shiplog.json"
    assert config.sectors_path().value == base / "sectors-seen.json"


def test_data_dir_env_moves_every_file(tmp_path, monkeypatch):
    monkeypatch.setenv("GCP_DATA_DIR", str(tmp_path / "elsewhere"))
    assert config.snapshot_path().value == tmp_path / "elsewhere" / "snapshot.json"
    assert config.shiplog_path().value == tmp_path / "elsewhere" / "shiplog.json"


def test_individual_file_env_overrides_the_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("GCP_DATA_DIR", str(tmp_path / "elsewhere"))
    monkeypatch.setenv("GCP_SNAPSHOT_PATH", str(tmp_path / "custom.json"))

    assert config.snapshot_path().value == tmp_path / "custom.json"
    assert config.shiplog_path().value == tmp_path / "elsewhere" / "shiplog.json"


# ----------------------------------------------------------------------------- save


def test_save_root_default(tmp_path):
    result = config.save_root()
    assert result.value == tmp_path / "home" / config.UNITY_LOG_DIR


def test_malformed_config_file_does_not_raise(tmp_path, monkeypatch):
    toml = tmp_path / "config.toml"
    toml.write_text("this is not = valid = toml", encoding="utf-8")
    monkeypatch.setattr(config, "config_file_path", lambda: toml)

    assert config.data_dir().value is not None  # falls through to the OS default
