using System.Collections.Generic;
using Newtonsoft.Json;

namespace GameContextProvider
{
    /// <summary>
    /// The wire format written to disk for the Python side to consume.
    /// Immutable once built: the Unity thread constructs it, the writer thread
    /// only ever reads it. Do not add mutable collections after publication.
    ///
    /// Bump <see cref="Schema"/> whenever a field changes meaning.
    /// </summary>
    public sealed class StateSnapshot
    {
        public const int CurrentSchema = 1;

        [JsonProperty("schema")] public int Schema = CurrentSchema;

        /// <summary>Unix seconds when this snapshot was built. Lets the reader detect a frozen game.</summary>
        [JsonProperty("t")] public double Timestamp;

        [JsonProperty("scene")] public string Scene;

        /// <summary>False in menus, loading screens, cutscenes — nothing else is meaningful then.</summary>
        [JsonProperty("in_game")] public bool InGame;

        [JsonProperty("loop")] public LoopState Loop;
        [JsonProperty("body")] public string Body;
        [JsonProperty("sectors")] public List<string> Sectors;
        [JsonProperty("player")] public PlayerInfo Player;
        [JsonProperty("hazards")] public List<string> Hazards;
        [JsonProperty("ship")] public ObjectInfo Ship;
        [JsonProperty("probe")] public ObjectInfo Probe;

        /// <summary>
        /// Nearest ship-log entry locations, closest first. These carry the game's own
        /// display name for a place, so they replace guesswork about what a sector is.
        /// </summary>
        [JsonProperty("nearby_entries")] public List<EntryInfo> NearbyEntries;

        public sealed class EntryInfo
        {
            [JsonProperty("id")] public string Id;
            [JsonProperty("name")] public string Name;
            [JsonProperty("distance")] public float Distance;

            /// <summary>Degrees from where the player is looking: 0 ahead, +90 right, -90 left, ±180 behind.</summary>
            [JsonProperty("bearing")] public float? Bearing;

            /// <summary>Degrees above the local horizon: positive is up, negative is down.</summary>
            [JsonProperty("elevation")] public float? Elevation;
        }

        public sealed class LoopState
        {
            [JsonProperty("count")] public int Count;
            [JsonProperty("elapsed")] public float Elapsed;
            [JsonProperty("remaining")] public float Remaining;
            [JsonProperty("flowing")] public bool Flowing;
        }

        public sealed class PlayerInfo
        {
            /// <summary>Position in the current body's local frame. World space is useless here — planets orbit and spin.</summary>
            [JsonProperty("local")] public float[] Local;

            /// <summary>Degrees, derived from <see cref="Local"/>. Stable across orbit and rotation.</summary>
            [JsonProperty("lat")] public float Latitude;
            [JsonProperty("lon")] public float Longitude;

            /// <summary>Distance from the body's centre, metres. Subtract the body's surface radius for altitude.</summary>
            [JsonProperty("radial")] public float RadialDistance;

            /// <summary>Speed relative to the current body, m/s.</summary>
            [JsonProperty("speed")] public float Speed;

            [JsonProperty("grounded")] public bool Grounded;
            [JsonProperty("in_ship")] public bool InShip;
            [JsonProperty("suited")] public bool Suited;
            [JsonProperty("dead")] public bool Dead;
            [JsonProperty("zero_g")] public bool ZeroG;
            [JsonProperty("underwater")] public bool Underwater;
            [JsonProperty("in_dream")] public bool InDreamWorld;
            [JsonProperty("at_flight_console")] public bool AtFlightConsole;
        }

        public sealed class ObjectInfo
        {
            /// <summary>Straight-line distance from the player, metres. Null when the object does not exist yet.</summary>
            [JsonProperty("distance")] public float? Distance;

            /// <summary>Nearest body to this object, which is not necessarily the player's body.</summary>
            [JsonProperty("body")] public string Body;

            /// <summary>Degrees from where the player is looking: 0 ahead, +90 right, -90 left, ±180 behind.</summary>
            [JsonProperty("bearing")] public float? Bearing;

            /// <summary>Degrees above the local horizon: positive is up, negative is down.</summary>
            [JsonProperty("elevation")] public float? Elevation;
        }
    }
}
