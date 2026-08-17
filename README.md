# Game Context Provider

Exposes live Outer Wilds state to an AI assistant over MCP — as *meaning*, not coordinates.

```
game (Unity/Mono)
  └─ BepInEx plugin ──► gcp-snapshot.json ──► Python MCP server ──► assistant
                                              + data.owsave
```

The plugin reads state on the Unity main thread and writes a snapshot at 10 Hz.
The Python server resolves that into named places using a JSON ontology, and falls
back to the save file when the game is not running.

## Layout

| Path | What |
|---|---|
| `mod/` | BepInEx plugin (C#, `netstandard2.0`) |
| `mod/src/StateCollector.cs` | Reads game state. No BepInEx types — any loader can drive it |
| `mod/src/SnapshotWriter.cs` | Background-thread atomic file writer |
| `mod/src/Plugin.cs` | BepInEx entry point, the only loader-specific file |
| `mcp_server/` | Python 3.11 MCP server |
| `.../adapters/base.py` | `GameAdapter` protocol — game-agnostic |
| `.../outer_wilds/save_reader.py` | Parses `data.owsave`. Works with no mod and no game |
| `.../outer_wilds/resolver.py` | Sector id → place name |
| `.../ontology/outer_wilds/` | Editable JSON, hot-reloaded |
| `refs/` | Decompiled `Assembly-CSharp` — gitignored, never commit |

## Status

- [x] Save reader, resolver, adapter — 75 tests
- [x] Plugin verified live against Outer Wilds 1.1.10.47
- [x] Ship log text: 89 entries, 371 facts
- [x] MCP server verified over stdio, all 8 tools
- [x] Zero-config paths — game auto-detected, `gcp-doctor` for when it is not
- [ ] Ontology is 42 sectors, 14 confirmed and 28 inferred from sector ids
- [ ] Untested against 1.1.15.x, the version most players run
- [ ] No prebuilt release — installing needs the .NET SDK

## Setup

No paths to configure. The build finds the game itself, and the plugin and the server
agree on a data directory without either having to locate the other.

### 1. Plugin

Install [BepInEx 5.4.x (x64)](https://github.com/BepInEx/BepInEx/releases) into your
Outer Wilds folder, launch the game once, and confirm `BepInEx/LogOutput.log` appears.

```powershell
cd mod
dotnet build -c Release -p:DeployToGame=true
```

The build locates the game automatically — it reads the install path out of Unity's
`Player.log`, which works for Steam, Epic, GOG, and any other install, then falls back
to the Steam library. Override it only if that fails:

```powershell
dotnet build -p:OwManagedDir="E:\Games\Outer Wilds\OuterWilds_Data\Managed"
```

### 2. Server

```powershell
cd mcp_server
pip install .
gcp-doctor                # checks every path and says how to fix what is missing
```

Register with Claude Code — no `PYTHONPATH`, the package installs a console script:

```json
{
  "mcpServers": {
    "game-context": { "command": "gcp-server" }
  }
}
```

### 3. Check it

```powershell
python tools/check_mcp.py   # starts the server over stdio and calls every tool
pytest                      # 75 tests, no game required
```

## Configuration

Nothing is required. When a default is wrong, precedence is:

```
explicit argument  >  environment variable  >  config file  >  auto-detect  >  OS default
```

Config file at `%APPDATA%\GameContextProvider\config.toml`:

```toml
game_dir      = "E:/Games/Outer Wilds"
data_dir      = "E:/gcp-data"
snapshot_path = "..."
save_path     = "..."
```

Environment variables: `GCP_GAME_DIR`, `GCP_DATA_DIR`, `GCP_SNAPSHOT_PATH`,
`GCP_SHIPLOG_PATH`, `GCP_SECTORS_PATH`, `GCP_SAVE_PATH`.

Run `gcp-doctor` to see which source won for each path.

### Where files live

| File | Path |
|---|---|
| snapshot, ship log, sectors | `%LOCALAPPDATA%\GameContextProvider\outer-wilds\` |
| save | `%USERPROFILE%\AppData\LocalLow\Mobius Digital\Outer Wilds\*Saves\` |

The plugin writes to the per-user data directory rather than the game folder, so the
server derives the same path from the OS and never has to find the install.

## Authoring the ontology

This is the ongoing work, and it is data entry rather than programming.

1. Play. Call `get_current_context`.
2. When `resolved_by` is `"unresolved"`, the response carries `unresolved_sectors`.
3. Paste those ids into `ontology/outer_wilds/locations.json` and name them.
4. The file is hot-reloaded — no restart, no rebuild.

## Design notes

**Body-local coordinates.** Planets orbit and rotate, so a world-space position never
names the same place twice. The plugin transforms position into the current
`AstroObject`'s frame and derives lat/lon, which is stable forever.

**Sectors over geometry.** Outer Wilds maintains nested `Sector` volumes for content
streaming, and they already name places. Reading `SectorDetector._sectorList` gets
semantic location for free; geometric regions are only the fallback.

**Threading.** The Unity thread builds an immutable snapshot and publishes it through a
volatile field. The writer thread only reads it. Touching a Unity object off the main
thread crashes the process.

**Provenance.** Every payload carries `_meta.source` and `_meta.stale`. An assistant
that cannot tell live data from a twenty-minute-old save will confidently describe
where you used to be.

**Read-only.** The plugin calls getters only — no setters, no save writes, no input
simulation.

## Known gaps

- `Fact.revealed` assumes `revealOrder >= 0`. The save pre-seeds entries with
  `revealOrder: -1` *and* `read: true`, so this needs confirming against
  `ShipLogManager` in `refs/`.
- Body `surface_radius` values in `bodies.json` are placeholders. Measure them in game
  from the `radial` field while standing on the surface.
- Nearest-body detection uses centre distance. Fine on a planet, arbitrary in deep space.
- Built against **1.1.10.47**. A different game version needs a rebuild and a re-check
  of the APIs in `refs/`.
