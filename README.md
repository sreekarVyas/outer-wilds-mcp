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

- [x] Decompiled reference (`refs/`, 1,706 files)
- [x] Save reader — verified against a real save
- [x] MCP server, tools, adapter, resolver
- [x] Plugin builds clean against the installed game DLLs
- [ ] **BepInEx not yet installed — the live path is untested**
- [ ] Ontology is two seed entries; needs authoring by playing
- [ ] Ship log fact text (ids only for now)

## Setup

### Plugin

BepInEx 5.4.x (x64) must be installed into `D:\Games\Outer Wilds` first. Launch the
game once and confirm `BepInEx\LogOutput.log` appears before going further — doorstop
injection into this install is unverified.

```powershell
cd mod
dotnet build -c Release -p:DeployToGame=true
```

Override the game path if it moves:

```powershell
dotnet build -p:OwManagedDir="E:\Games\Outer Wilds\OuterWilds_Data\Managed" `
             -p:OwGameDir="E:\Games\Outer Wilds"
```

### Server

```powershell
cd mcp_server
pip install -e .
python tools/smoke.py     # works with the game closed
```

Register with Claude Code:

```json
{
  "mcpServers": {
    "game-context": {
      "command": "python",
      "args": ["-m", "gcp.server"],
      "env": { "PYTHONPATH": "c:/Users/kurud/Documents/Code/game-context-provider/mcp_server/src" }
    }
  }
}
```

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
