using System.IO;
using BepInEx;
using BepInEx.Configuration;
using UnityEngine;

namespace GameContextProvider
{
    /// <summary>
    /// BepInEx entry point. Holds all loader-specific code, so porting to OWML later
    /// means adding a sibling of this file — not touching the collector.
    /// </summary>
    [BepInPlugin(PluginGuid, PluginName, PluginVersion)]
    public sealed class Plugin : BaseUnityPlugin
    {
        public const string PluginGuid = "dev.gcp.outerwilds";
        public const string PluginName = "GameContextProvider";
        public const string PluginVersion = "0.1.0";

        private ConfigEntry<string> _outputPath;
        private ConfigEntry<float> _sampleInterval;

        private SnapshotWriter _writer;
        private DiscoveryLog _discoveries;
        private GameObject _host;

        private void Awake()
        {
            _outputPath = Config.Bind(
                "Output", "Path",
                Path.Combine(Paths.BepInExRootPath, "gcp-snapshot.json"),
                "Where the state snapshot is written. The MCP server reads this file.");

            _sampleInterval = Config.Bind(
                "Output", "SampleInterval", 0.1f,
                "Seconds between samples. 0.1 = 10 Hz.");

            _writer = new SnapshotWriter(_outputPath.Value, m => Logger.LogWarning(m));

            // A DontDestroyOnLoad host keeps the collector alive across scene loads —
            // otherwise it dies on every trip to the menu or the Eye.
            _host = new GameObject(PluginName + ".Host");
            DontDestroyOnLoad(_host);
            _host.hideFlags = HideFlags.HideAndDontSave;

            _discoveries = new DiscoveryLog(
                Path.Combine(Path.GetDirectoryName(_outputPath.Value) ?? ".", "gcp-sectors-seen.json"),
                m => Logger.LogWarning(m));

            var collector = _host.AddComponent<StateCollector>();
            collector.SampleInterval = _sampleInterval.Value;
            collector.OnSnapshot = _writer.Publish;
            collector.LogWarning = m => Logger.LogWarning(m);
            collector.Discoveries = _discoveries;

            foreach (var problem in StateCollector.SelfCheck())
            {
                Logger.LogError("SELF-CHECK FAILED: " + problem);
            }

            Logger.LogInfo($"{PluginName} {PluginVersion} running. Snapshot -> {_outputPath.Value}");
        }

        private void OnDestroy()
        {
            _writer?.Dispose();
            if (_host != null) Destroy(_host);
        }
    }
}
