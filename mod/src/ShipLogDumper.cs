using System;
using System.Collections.Generic;
using System.IO;
using Newtonsoft.Json;

namespace GameContextProvider
{
    /// <summary>
    /// Writes the whole ship log — entry names and fact text — to a JSON file, once.
    ///
    /// The save file records which fact ids a player holds, but not what any of them
    /// say. `CT_SUNLESS_CITY_X3` is a label, not knowledge. ShipLogManager has the real
    /// text loaded in memory, so one pass over it turns every id into something readable.
    ///
    /// This is static reference data: it describes the game, not the player. It is
    /// written once and reused, and it deliberately includes facts the player has not
    /// revealed — filtering by discovery is the consumer's job, not this dump's.
    /// </summary>
    public static class ShipLogDumper
    {
        public const int CurrentSchema = 1;

        public sealed class Dump
        {
            [JsonProperty("schema")] public int Schema = CurrentSchema;
            [JsonProperty("generated")] public string Generated;
            [JsonProperty("entry_count")] public int EntryCount;
            [JsonProperty("fact_count")] public int FactCount;
            [JsonProperty("entries")] public List<Entry> Entries = new List<Entry>();
        }

        public sealed class Entry
        {
            [JsonProperty("id")] public string Id;
            [JsonProperty("name")] public string Name;
            [JsonProperty("astro_object")] public string AstroObject;
            [JsonProperty("parent")] public string Parent;
            [JsonProperty("curiosity")] public string Curiosity;
            [JsonProperty("facts")] public List<Fact> Facts = new List<Fact>();
        }

        public sealed class Fact
        {
            [JsonProperty("id")] public string Id;
            [JsonProperty("text")] public string Text;

            /// <summary>A rumor points at a place; an explore fact is what you learned there.</summary>
            [JsonProperty("rumor")] public bool Rumor;

            /// <summary>Entry this rumor came from, when it has one.</summary>
            [JsonProperty("source")] public string Source;
        }

        /// <summary>
        /// Returns false when the log is not loaded yet, so the caller can try again on a
        /// later frame rather than writing an empty file.
        /// </summary>
        public static bool TryDump(ShipLogManager manager, string path, Action<string> log)
        {
            if (manager == null) return false;

            var entries = manager.GetEntryList();
            if (entries == null || entries.Count == 0) return false;

            var dump = new Dump { Generated = DateTime.UtcNow.ToString("o") };

            foreach (var entry in entries)
            {
                if (entry == null) continue;

                var record = new Entry
                {
                    Id = entry.GetID(),
                    Name = entry.GetName(false),
                    AstroObject = entry.GetAstroObjectID(),
                    Parent = entry.HasParent() ? entry.GetParentID() : null,
                    Curiosity = entry.GetCuriosityName().ToString(),
                };

                AddFacts(record, entry.GetRumorFacts(), rumor: true);
                AddFacts(record, entry.GetExploreFacts(), rumor: false);

                dump.EntryCount++;
                dump.FactCount += record.Facts.Count;
                dump.Entries.Add(record);
            }

            try
            {
                var temp = path + ".tmp";
                File.WriteAllText(temp, JsonConvert.SerializeObject(dump, Formatting.Indented));
                SnapshotWriter.AtomicReplace(temp, path);
                log?.Invoke($"ship log dumped: {dump.EntryCount} entries, {dump.FactCount} facts -> {path}");
                return true;
            }
            catch (Exception e)
            {
                log?.Invoke("ship log dump failed: " + e.Message);
                return false;
            }
        }

        private static void AddFacts(Entry record, List<ShipLogFact> facts, bool rumor)
        {
            if (facts == null) return;

            foreach (var fact in facts)
            {
                if (fact == null) continue;

                record.Facts.Add(new Fact
                {
                    Id = fact.GetID(),
                    Text = fact.GetText(),
                    Rumor = rumor,
                    Source = fact.HasSource() ? fact.GetSourceID() : null,
                });
            }
        }
    }
}
