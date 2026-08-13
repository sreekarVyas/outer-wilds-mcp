using System;
using System.Collections.Generic;
using System.IO;
using Newtonsoft.Json;

namespace GameContextProvider
{
    /// <summary>
    /// Accumulates every distinct sector key the player has ever entered.
    ///
    /// The snapshot file only holds the current instant, so anything between two reads
    /// is lost. Naming places is the long pole of this project, and the raw material is
    /// exactly this list — so it is captured continuously rather than sampled.
    ///
    /// Append-only across sessions: the file is loaded at startup and never pruned.
    /// </summary>
    public sealed class DiscoveryLog
    {
        private readonly string _path;
        private readonly Action<string> _logWarning;
        private readonly Dictionary<string, Entry> _seen = new Dictionary<string, Entry>();

        private bool _dirty;

        public sealed class Entry
        {
            [JsonProperty("sector")] public string Sector;
            [JsonProperty("first_seen")] public string FirstSeen;
            [JsonProperty("body")] public string Body;

            /// <summary>Full stack at first sighting — gives the parent context when naming it later.</summary>
            [JsonProperty("stack")] public List<string> Stack;
        }

        public DiscoveryLog(string path, Action<string> logWarning = null)
        {
            _path = path;
            _logWarning = logWarning;
            Load();
        }

        private void Load()
        {
            if (!File.Exists(_path)) return;

            try
            {
                var existing = JsonConvert.DeserializeObject<List<Entry>>(File.ReadAllText(_path));
                if (existing == null) return;
                foreach (var entry in existing)
                {
                    if (entry?.Sector != null) _seen[entry.Sector] = entry;
                }
            }
            catch (Exception e)
            {
                // A corrupt log must not stop the game from starting; begin a fresh one.
                _logWarning?.Invoke("discovery log unreadable, starting fresh: " + e.Message);
            }
        }

        /// <summary>Called from the Unity thread once per sample. Cheap unless something is new.</summary>
        public void Observe(IList<string> stack, string body)
        {
            if (stack == null || stack.Count == 0) return;

            foreach (var sector in stack)
            {
                if (string.IsNullOrEmpty(sector) || _seen.ContainsKey(sector)) continue;

                _seen[sector] = new Entry
                {
                    Sector = sector,
                    Body = body,
                    FirstSeen = DateTime.UtcNow.ToString("o"),
                    Stack = new List<string>(stack),
                };
                _dirty = true;
            }
        }

        /// <summary>Writes only when something new appeared, so this is idle almost always.</summary>
        public void FlushIfDirty()
        {
            if (!_dirty) return;
            _dirty = false;

            try
            {
                var all = new List<Entry>(_seen.Values);
                var temp = _path + ".tmp";
                File.WriteAllText(temp, JsonConvert.SerializeObject(all, Formatting.Indented));
                SnapshotWriter.AtomicReplace(temp, _path);
            }
            catch (Exception e)
            {
                _logWarning?.Invoke("discovery log write failed: " + e.Message);
            }
        }

        public int Count => _seen.Count;
    }
}
