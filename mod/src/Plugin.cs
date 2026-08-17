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

        private ConfigEntry<string> _dataDirectory;
        private ConfigEntry<float> _sampleInterval;

        private SnapshotWriter _writer;
        private DiscoveryLog _discoveries;
        private GameObject _host;

        private void Awake()
        {
            // Default to the per-user data directory, not the game folder: the MCP server
            // derives this same path from the OS, so it never has to locate the install.
            _dataDirectory = Config.Bind(
                "Output", "DataDirectory",
                AppPaths.DataDirectory,
                "Directory for snapshot, ship log, and sector files. The MCP server reads "
                + "these. Leave as-is unless you also set GCP_DATA_DIR for the server.");

            _sampleInterval = Config.Bind(
                "Output", "SampleInterval", 0.1f,
                "Seconds between samples. 0.1 = 10 Hz.");

            var directory = _dataDirectory.Value;
            _writer = new SnapshotWriter(
                Path.Combine(directory, AppPaths.SnapshotFile), m => Logger.LogWarning(m));

            // A DontDestroyOnLoad host keeps the collector alive across scene loads —
            // otherwise it dies on every trip to the menu or the Eye.
            _host = new GameObject(PluginName + ".Host");
            DontDestroyOnLoad(_host);
            _host.hideFlags = HideFlags.HideAndDontSave;

            _discoveries = new DiscoveryLog(
                Path.Combine(directory, AppPaths.SectorsFile), m => Logger.LogWarning(m));

            var collector = _host.AddComponent<StateCollector>();
            collector.SampleInterval = _sampleInterval.Value;
            collector.OnSnapshot = _writer.Publish;
            collector.LogWarning = m => Logger.LogWarning(m);
            collector.Discoveries = _discoveries;
            collector.ShipLogDumpPath = Path.Combine(directory, AppPaths.ShipLogFile);

            foreach (var problem in StateCollector.SelfCheck())
            {
                Logger.LogError("SELF-CHECK FAILED: " + problem);
            }

            Logger.LogInfo($"{PluginName} {PluginVersion} running. Data -> {directory}");
        }

        private void OnDestroy()
        {
            _writer?.Dispose();
            if (_host != null) Destroy(_host);
        }
    }
}
