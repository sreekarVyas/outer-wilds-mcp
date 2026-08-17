"""Resolves every path the server needs, and records how each was resolved.

Precedence, highest first:

    explicit argument > environment variable > config file > auto-detect > OS default

Every result carries its `source`, because a wrong path is the most likely failure on a
fresh install and "which value won, and why" is the only useful thing to know then.
That provenance is what makes `gcp doctor` worth running.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "GameContextProvider"
GAME_KEY = "outer-wilds"

# Written by Unity on every launch, whatever the store. See _from_player_log.
UNITY_LOG_DIR = "AppData/LocalLow/Mobius Digital/Outer Wilds"

# A directory is only the game if this exists inside it.
GAME_MARKER = Path("OuterWilds_Data") / "Managed" / "Assembly-CSharp.dll"


@dataclass(frozen=True)
class Resolved:
    """A path plus where it came from.

    `value` is None when nothing could be resolved. `problem` is set only when something
    is wrong — never for informational notes, so callers can treat it as a failure flag.
    """

    value: Path | None
    source: str
    problem: str | None = None

    @property
    def exists(self) -> bool:
        return self.value is not None and self.value.exists()

    @property
    def ok(self) -> bool:
        return self.exists and self.problem is None

    def __str__(self) -> str:
        return str(self.value) if self.value else "<unresolved>"


# --------------------------------------------------------------------------- base dirs


def _local_app_data() -> Path:
    """%LOCALAPPDATA% on Windows, an XDG-ish equivalent elsewhere."""
    raw = os.environ.get("LOCALAPPDATA")
    if raw:
        return Path(raw)
    if sys.platform == "win32":
        return Path.home() / "AppData" / "Local"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))


def _roaming_app_data() -> Path:
    raw = os.environ.get("APPDATA")
    if raw:
        return Path(raw)
    if sys.platform == "win32":
        return Path.home() / "AppData" / "Roaming"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))


def config_file_path() -> Path:
    return _roaming_app_data() / APP_NAME / "config.toml"


def _load_config_file() -> dict:
    path = config_file_path()
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        # A missing or malformed config must never stop the server starting. `doctor`
        # reports the problem; everything else falls through to the next source.
        return {}


# ------------------------------------------------------------------- game detection


def _is_game_dir(path: Path | None) -> bool:
    return path is not None and (path / GAME_MARKER).is_file()


def _from_player_log() -> tuple[Path | None, str | None]:
    """Read the install path out of Unity's own log.

    Line 1 of Player.log is:

        Mono path[0] = 'D:/Games/Outer Wilds/OuterWilds_Data/Managed'

    Unity writes it on every launch regardless of how the game was installed, so this
    finds repacks and other non-store copies that have no registry entry or manifest.
    It only requires that the game has been run once.

    Player-prev.log is the previous session's copy, used when the current log is being
    written or has been truncated.
    """
    log_dir = Path.home() / UNITY_LOG_DIR

    for name in ("Player.log", "Player-prev.log"):
        log = log_dir / name
        try:
            # The line is always first; reading the whole file would pull in megabytes.
            with log.open("r", encoding="utf-8", errors="replace") as handle:
                head = handle.readline()
        except OSError:
            continue

        match = re.search(r"Mono path\[0\]\s*=\s*'(.+?)'", head)
        if not match:
            continue

        managed = Path(match.group(1))
        # .../OuterWilds_Data/Managed -> the install root
        candidate = managed.parent.parent
        if _is_game_dir(candidate):
            return candidate, name

    return None, None


def _from_running_process() -> Path | None:
    """The install path of the running game, if it is running."""
    if sys.platform != "win32":
        return None

    try:
        result = subprocess.run(
            ["wmic", "process", "where", "name='OuterWilds.exe'", "get", "ExecutablePath"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    for line in result.stdout.splitlines():
        line = line.strip()
        if not line.lower().endswith("outerwilds.exe"):
            continue
        candidate = Path(line).parent
        if _is_game_dir(candidate):
            return candidate

    return None


def _steam_libraries() -> list[Path]:
    """Every Steam library folder, from the registry and libraryfolders.vdf."""
    steam = _registry_value(r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath")
    if steam is None:
        steam = _registry_value(r"SOFTWARE\Valve\Steam", "InstallPath")
    if steam is None:
        return []

    root = Path(steam)
    libraries = [root]

    vdf = root / "steamapps" / "libraryfolders.vdf"
    try:
        text = vdf.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return libraries

    # The format is nested key/value quotes; every "path" entry is a library root.
    libraries.extend(Path(p) for p in re.findall(r'"path"\s+"([^"]+)"', text))
    return libraries


def _from_steam() -> Path | None:
    for library in _steam_libraries():
        candidate = library / "steamapps" / "common" / "Outer Wilds"
        if _is_game_dir(candidate):
            return candidate
    return None


def _from_epic() -> Path | None:
    manifests = Path(r"C:\ProgramData\Epic\EpicGamesLauncher\Data\Manifests")
    try:
        items = list(manifests.glob("*.item"))
    except OSError:
        return None

    for item in items:
        try:
            data = json.loads(item.read_text(encoding="utf-8", errors="replace"))
        except (OSError, json.JSONDecodeError):
            continue

        location = data.get("InstallLocation")
        if location and _is_game_dir(Path(location)):
            return Path(location)

    return None


def _from_gog() -> Path | None:
    base = r"SOFTWARE\WOW6432Node\GOG.com\Games"
    for sub in _registry_subkeys(base):
        path = _registry_value(f"{base}\\{sub}", "path")
        if path and _is_game_dir(Path(path)):
            return Path(path)
    return None


def _registry_value(key: str, name: str) -> str | None:
    if sys.platform != "win32":
        return None
    try:
        import winreg
    except ImportError:
        return None

    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(hive, key) as handle:
                value, _ = winreg.QueryValueEx(handle, name)
                return str(value)
        except OSError:
            continue
    return None


def _registry_subkeys(key: str) -> list[str]:
    if sys.platform != "win32":
        return []
    try:
        import winreg
    except ImportError:
        return []

    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as handle:
            count = winreg.QueryInfoKey(handle)[0]
            return [winreg.EnumKey(handle, i) for i in range(count)]
    except OSError:
        return []


# The order is deliberate: Player.log reflects what was actually launched, whereas a
# launcher's manifest only reflects what it believes is installed.
_GAME_DETECTORS = [
    ("running process", _from_running_process),
    ("Steam", _from_steam),
    ("Epic", _from_epic),
    ("GOG", _from_gog),
]


def find_game_dir(explicit: Path | str | None = None) -> Resolved:
    """Locate the Outer Wilds install. Only needed for the mod build and for `doctor`."""
    # A path the user named explicitly is reported back even when wrong, with the reason
    # — silently falling through to auto-detection would hide their mistake.
    for value, source in (
        (explicit, "explicit argument"),
        (os.environ.get("GCP_GAME_DIR"), "GCP_GAME_DIR"),
        (_load_config_file().get("game_dir"), "config file"),
    ):
        if value:
            path = Path(value)
            problem = None if _is_game_dir(path) else "no OuterWilds_Data/Managed/Assembly-CSharp.dll here"
            return Resolved(path, source, problem)

    found, log_name = _from_player_log()
    if found:
        return Resolved(found, log_name or "Player.log")

    for label, detector in _GAME_DETECTORS:
        found = detector()
        if found:
            return Resolved(found, label)

    return Resolved(
        None, "not found",
        "tried: explicit, GCP_GAME_DIR, config file, Player.log, running process, Steam, Epic, GOG",
    )


# ------------------------------------------------------------------------ data paths


def data_dir(explicit: Path | str | None = None) -> Resolved:
    """Where the plugin writes and the server reads.

    Deliberately *not* inside the game folder. Both processes derive this same path from
    the OS, so the server never has to locate the game during normal operation.
    """
    if explicit:
        return Resolved(Path(explicit), "explicit argument")

    env = os.environ.get("GCP_DATA_DIR")
    if env:
        return Resolved(Path(env), "GCP_DATA_DIR")

    configured = _load_config_file().get("data_dir")
    if configured:
        return Resolved(Path(configured), "config file")

    return Resolved(_local_app_data() / APP_NAME / GAME_KEY, "OS default")


def _data_file(env_var: str, config_key: str, filename: str,
               explicit: Path | str | None) -> Resolved:
    if explicit:
        return Resolved(Path(explicit), "explicit argument")

    env = os.environ.get(env_var)
    if env:
        return Resolved(Path(env), env_var)

    configured = _load_config_file().get(config_key)
    if configured:
        return Resolved(Path(configured), "config file")

    base = data_dir()
    return Resolved(base.value / filename, f"data dir ({base.source})")


def snapshot_path(explicit: Path | str | None = None) -> Resolved:
    return _data_file("GCP_SNAPSHOT_PATH", "snapshot_path", "snapshot.json", explicit)


def shiplog_path(explicit: Path | str | None = None) -> Resolved:
    return _data_file("GCP_SHIPLOG_PATH", "shiplog_path", "shiplog.json", explicit)


def sectors_path(explicit: Path | str | None = None) -> Resolved:
    return _data_file("GCP_SECTORS_PATH", "sectors_path", "sectors-seen.json", explicit)


def save_root(explicit: Path | str | None = None) -> Resolved:
    """The folder holding save profiles.

    Path.home() rather than os.environ["USERPROFILE"]: the latter raises at *import*
    time when unset, taking the whole server down instead of degrading.
    """
    if explicit:
        return Resolved(Path(explicit), "explicit argument")

    env = os.environ.get("GCP_SAVE_PATH")
    if env:
        return Resolved(Path(env), "GCP_SAVE_PATH")

    configured = _load_config_file().get("save_path")
    if configured:
        return Resolved(Path(configured), "config file")

    return Resolved(Path.home() / UNITY_LOG_DIR, "OS default")
